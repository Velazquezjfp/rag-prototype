"""Identity of everything we write: the logical document id, node identity keys, edge ids, and the run
fingerprint that makes ingestion idempotent."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from .ontology import IdentityRule, Ontology
from .schemas import Chunk, GraphEdge, GraphNode, ProcessResponse

SOFT_HYPHEN = "­"
# copied from docling_graph_service.normalize (title stripping for Person identity keys)
_TITLES = re.compile(r"^(?:(?:dr|prof|dipl\.?-ing|mag|herr|frau|hr|fr)\.?\s+)+", re.IGNORECASE)


def clean_text(text: str) -> str:
    """Remove soft hyphens (docling keeps U+00AD from hyphenated PDF words) so regexes and BM25 see whole tokens."""
    return text.replace(SOFT_HYPHEN, "")


def norm_key(text: str, *, strip_titles: bool = False) -> str:
    """Matching key: whitespace-collapsed, casefolded, trailing punctuation removed (same as dgs ``norm_key``)."""
    s = " ".join(str(text).replace(" ", " ").split()).strip().rstrip(".,;:")
    if strip_titles:
        s = _TITLES.sub("", s)
    return s.casefold()


def normalize_identity(value: str, mode: str | None) -> str:
    s = " ".join(str(value).replace(" ", " ").split()).strip()
    if mode == "upper":
        return s.upper()
    if mode == "casefold":
        return s.casefold()
    if mode == "strip_titles_then_casefold":
        return norm_key(s, strip_titles=True)
    return norm_key(s)


def node_identity(node: GraphNode, rule: IdentityRule | None, root_system: str | None) -> tuple[str, str]:
    """``(identity, identity_norm)``: the ontology identity value(s) of a node, raw and normalized.

    Composite keys are joined with ``|``; missing keys fall back to the label. Classes with ``scope: system`` get the
    document's root system prefixed to the normalized form (``zentrale sicherheitsdienste::dispatcher``)."""
    keys = rule.keys if rule else ("label",)
    values = []
    for k in keys:
        v = node.label if k == "label" else node.attributes.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        values.append(_scalar(v))
    if not values:
        values = [node.label]
    identity = "|".join(values)
    mode = rule.normalize if rule else None
    identity_norm = "|".join(normalize_identity(v, mode) for v in values)
    if rule and rule.scope == "system" and root_system:
        identity_norm = f"{norm_key(root_system)}::{identity_norm}"
    return identity, identity_norm


def _scalar(v: Any) -> str:
    if isinstance(v, list | tuple):
        return ", ".join(_scalar(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, sort_keys=True, ensure_ascii=False)
    return str(v)


def edge_id(edge: GraphEdge) -> str:
    """Deterministic edge id: content hash of the assertion (same across documents that assert the same edge)."""
    payload = [
        edge.source,
        edge.target,
        edge.type,
        edge.polarity,
        edge.qualifier or "",
        edge.quote or "",
        sorted(edge.provenance.chunk_ids),
    ]
    return hashlib.sha256(canonical_json(payload)).hexdigest()[:16]


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def vector_digest(chunks: list[Chunk], ndigits: int = 4) -> str:
    """Digest of all vectors in chunk_id order, rounded so float noise between identical runs does not count."""
    h = hashlib.sha256()
    dims: set[int] = set()
    for c in sorted(chunks, key=lambda c: c.chunk_id):
        if c.embedding is None:
            h.update(b"None;")
            continue
        dims.add(len(c.embedding))
        h.update(json.dumps([round(x, ndigits) for x in c.embedding], separators=(",", ":")).encode())
        h.update(b";")
    return f"{sorted(dims)}:{h.hexdigest()}"


def run_fingerprint(
    resp: ProcessResponse,
    edge_ids: list[str],
    *,
    ontology_fingerprint: str,
    embedding_model: str,
    embedding_dim: int,
    mapping_version: int,
) -> str:
    """``run_id``: sha256 over everything that ends up in the indices. Identical output => identical run_id,
    independent of element order; any change in text, vectors (beyond 1e-4), graph, models or mapping => new run_id."""
    graph = resp.graph
    payload = {
        "doc_sha256": resp.document.sha256,
        "document": resp.document.model_dump(),
        "chunks": [
            {k: v for k, v in c.model_dump().items() if k != "embedding"}
            for c in sorted(resp.chunks, key=lambda c: c.chunk_id)
        ],
        "vectors": vector_digest(resp.chunks),
        "nodes": sorted((n.model_dump() for n in graph.nodes), key=lambda d: d["id"]) if graph else None,
        "edges": sorted(
            ({**e.model_dump(), "id": eid} for e, eid in zip(graph.edges, edge_ids, strict=True)),
            key=lambda d: d["id"],
        )
        if graph
        else None,
        "graph_meta": {k: graph.meta.get(k) for k in ("template_schema_hash", "ontology", "docling_graph_version")}
        if graph
        else None,
        "degraded": resp.degraded.model_dump(),
        "versions": resp.versions,
        "embedding": {"model": embedding_model, "dim": embedding_dim},
        "ontology_fingerprint": ontology_fingerprint,
        "mapping_version": mapping_version,
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


# --------------------------------------------------------------------------- document id


class DocIdUnresolved(ValueError):
    pass


@dataclass
class DocIdResolution:
    doc_id: str
    source: str  # override | ontology_file | page1_regex | documents_edge
    candidates: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


_ORDER = ("override", "ontology_file", "page1_regex", "documents_edge")


def resolve_doc_id(resp: ProcessResponse, ontology: Ontology, override: str | None = None) -> DocIdResolution:
    """Logical document id (``BHB-PLT-0007``), never guessed.

    Order: explicit override > ontology ``meta.documents`` by file name > exactly one document-id regex hit on the
    title page (page-1 chunks; later pages cite *other* manuals) > ``attributes.doc_id`` of the source node of the
    single ``DOCUMENTS`` edge. Disagreements are reported as warnings; no candidate raises ``DocIdUnresolved``."""
    cands: dict[str, str] = {}
    warnings: list[str] = []
    if override:
        cands["override"] = override.strip().upper()
    meta = ontology.doc_for_file(resp.document.name)
    if meta:
        cands["ontology_file"] = meta.doc_id

    rx = ontology.doc_id_regex
    hits = {m.upper() for c in resp.chunks if c.page_numbers == [1] for m in rx.findall(clean_text(c.text))}
    if len(hits) == 1:
        cands["page1_regex"] = next(iter(hits))
    elif len(hits) > 1:
        warnings.append(f"title page names several document ids {sorted(hits)}; ignored")

    if resp.graph:
        docs_edges = [e for e in resp.graph.edges if e.type == "DOCUMENTS"]
        if len(docs_edges) == 1:
            src = next((n for n in resp.graph.nodes if n.id == docs_edges[0].source), None)
            value = src.attributes.get("doc_id") if src else None
            if isinstance(value, str) and value.strip():
                cands["documents_edge"] = value.strip().upper()
        elif len(docs_edges) > 1:
            warnings.append(f"{len(docs_edges)} DOCUMENTS edges; ignored")

    for method in _ORDER:
        if method in cands:
            chosen = cands[method]
            others = {m: v for m, v in cands.items() if v != chosen}
            if others:
                warnings.append(f"doc_id {chosen} ({method}) disagrees with {others}")
            return DocIdResolution(doc_id=chosen, source=method, candidates=cands, warnings=warnings)
    raise DocIdUnresolved(
        f"cannot determine the document id of {resp.document.name!r} (not in the ontology's meta.documents, no "
        f"unique document id on page 1, no DOCUMENTS edge); pass --doc-id"
    )


def is_zero_vector(v: list[float]) -> bool:
    return math.fsum(x * x for x in v) == 0.0
