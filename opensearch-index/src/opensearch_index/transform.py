"""``ProcessResponse`` -> index documents: chunks (with identifiers and the graph reverse index), nodes, the
document record with the graph blob. Pure functions; nothing here talks to OpenSearch."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .identity import clean_text, edge_id, node_identity
from .mappings import SCOPE_DOCUMENT, IndexNames
from .ontology import Ontology
from .schemas import GraphResult, ProcessResponse


class VectorError(ValueError):
    pass


@dataclass
class ChunkLinks:
    node_ids: set[str] = field(default_factory=set)
    node_labels: set[str] = field(default_factory=set)
    node_types: set[str] = field(default_factory=set)
    edge_ids: set[str] = field(default_factory=set)


@dataclass
class IndexBatch:
    doc_id: str
    doc_id_source: str
    doc_sha256: str
    run_id: str
    indexed_at: str
    chunks: list[dict[str, Any]]
    nodes: list[dict[str, Any]]
    document: dict[str, Any]
    edge_ids: list[str]

    @property
    def sha12(self) -> str:
        return self.doc_sha256[:12]

    @property
    def counts(self) -> dict[str, int]:
        return {"chunks": len(self.chunks), "nodes": len(self.nodes), "edges": len(self.edge_ids), "documents": 1}


def node_doc_id(sha12: str, node_id: str) -> str:
    """``_id`` of a node record: per-document (the dgs node id itself is shared across documents)."""
    return f"{sha12}:{node_id}"


def extract_identifiers(text: str | None, regexes: dict[str, re.Pattern[str]]) -> list[str]:
    if not text:
        return []
    s = clean_text(text)
    found: set[str] = set()
    for rx in regexes.values():
        found.update(rx.findall(s))
    return sorted(found)


def compute_edge_ids(graph: GraphResult | None) -> list[str]:
    """One id per edge, parallel to ``graph.edges``; a duplicate within one document is a data error."""
    if graph is None:
        return []
    ids = [edge_id(e) for e in graph.edges]
    seen: dict[str, int] = {}
    for i, eid in enumerate(ids):
        if eid in seen:
            e = graph.edges[i]
            raise ValueError(f"duplicate edge {e.source} -{e.type}-> {e.target} ({e.polarity}) at positions {seen[eid]} and {i}")
        seen[eid] = i
    return ids


def reverse_index(graph: GraphResult | None, edge_ids: list[str]) -> dict[str, ChunkLinks]:
    """chunk_id -> nodes/edges anchored to it (graph-retrieval-patterns §2.2). Edge endpoints are added to the
    evidence chunk of the edge too, because an edge's chunk is not always in either node's chunk list."""
    links: dict[str, ChunkLinks] = defaultdict(ChunkLinks)
    if graph is None:
        return links
    by_id = {n.id: n for n in graph.nodes}

    def add_node(cid: str, nid: str) -> None:
        n = by_id.get(nid)
        if n is None:
            return
        link = links[cid]
        link.node_ids.add(n.id)
        link.node_types.add(n.type)
        link.node_labels.add(n.label)
        link.node_labels.update(a for a in n.aliases if a)

    for n in graph.nodes:
        for cid in n.provenance.chunk_ids:
            add_node(cid, n.id)
    for e, eid in zip(graph.edges, edge_ids, strict=True):
        for cid in e.provenance.chunk_ids:
            links[cid].edge_ids.add(eid)
            add_node(cid, e.source)
            add_node(cid, e.target)
    return links


def _attr_text(attributes: dict[str, Any]) -> str:
    parts: list[str] = []
    for v in attributes.values():
        if isinstance(v, list | tuple):
            parts.extend(str(x) for x in v if x is not None)
        elif isinstance(v, dict):
            parts.extend(str(x) for x in v.values() if x is not None)
        elif v is not None:
            parts.append(str(v))
    return " ".join(parts)


def build_batch(
    resp: ProcessResponse,
    *,
    doc_id: str,
    doc_id_source: str,
    run_id: str,
    ontology: Ontology,
    embedding_model: str,
    embedding_dim: int,
    embedding_text_prefix: str,
    indexed_at: str,
) -> IndexBatch:
    sha = resp.document.sha256
    graph = resp.graph
    edge_ids = compute_edge_ids(graph)
    links = reverse_index(graph, edge_ids)
    root_system = ontology.root_system(doc_id)
    common = {"doc_id": doc_id, "doc_sha256": sha, "run_id": run_id, "indexed_at": indexed_at}

    # ---- chunks
    bad: list[str] = []
    chunks: list[dict[str, Any]] = []
    for c in resp.chunks:
        link = links.get(c.chunk_id, ChunkLinks())
        doc: dict[str, Any] = {
            **common,
            "chunk_id": c.chunk_id,
            "text": clean_text(c.text),
            "body_text": clean_text(c.body_text),
            "heading_breadcrumb": [clean_text(h) for h in c.heading_breadcrumb],
            "heading_level": c.heading_level,
            "kind": c.kind,
            "caption": clean_text(c.caption) if c.caption else None,
            "page_numbers": c.page_numbers,
            "dom_paths": c.dom_paths,
            "bboxes": [b.model_dump() for b in c.bboxes],
            "token_count": c.token_count,
            "identifiers": extract_identifiers(f"{c.text}\n{c.caption or ''}", ontology.regexes),
            "node_ids": sorted(link.node_ids),
            "node_labels": sorted(link.node_labels),
            "node_types": sorted(link.node_types),
            "edge_ids": sorted(link.edge_ids),
        }
        if c.embedding is not None:
            if len(c.embedding) != embedding_dim:
                bad.append(f"{c.chunk_id}: dim {len(c.embedding)} != {embedding_dim}")
            elif math.fsum(x * x for x in c.embedding) == 0.0:
                bad.append(f"{c.chunk_id}: zero vector")
            doc["embedding"] = c.embedding
            doc["embedding_model"] = embedding_model
        chunks.append(doc)
    if bad:
        raise VectorError("invalid embeddings (check OSI__EMBEDDING__DIM against the run): " + "; ".join(bad[:5]))

    # ---- nodes
    nodes: list[dict[str, Any]] = []
    degree: dict[str, int] = defaultdict(int)
    if graph:
        for e in graph.edges:
            degree[e.source] += 1
            degree[e.target] += 1
        for n in graph.nodes:
            identity, identity_norm = node_identity(n, ontology.identity.get(n.type), root_system)
            doc = {
                **common,
                "node_id": n.id,
                "scope": SCOPE_DOCUMENT,
                "type": n.type,
                "label": n.label,
                "aliases": n.aliases,
                "identity": identity,
                "identity_norm": identity_norm,
                "attributes_text": _attr_text(n.attributes),
                "quote": n.quote,
                "identifiers": extract_identifiers(
                    " ".join([n.label, *n.aliases, _attr_text(n.attributes)]), ontology.regexes
                ),
                "chunk_ids": n.provenance.chunk_ids,
                "pages": n.provenance.pages,
                "match": n.provenance.match,
                "degree": degree.get(n.id, 0),
                "provenance": n.provenance.model_dump(),
            }
            if n.attributes:
                doc["attributes"] = n.attributes
            nodes.append(doc)

    # ---- document (+ graph blob)
    own = None
    related: list[str] = []
    if graph:
        for n in graph.nodes:
            if n.type != "Document":
                continue
            value = n.attributes.get("doc_id")
            if isinstance(value, str) and value.strip().upper() == doc_id:
                own = n
            elif isinstance(value, str) and value.strip():
                related.append(value.strip().upper())
    blob = None
    if graph:
        blob = graph.model_dump()
        for e, eid in zip(blob["edges"], edge_ids, strict=True):
            e["id"] = eid
    attrs = own.attributes if own else {}
    document = {
        **common,
        "doc_id_source": doc_id_source,
        "scope": SCOPE_DOCUMENT,
        "name": resp.document.name,
        "format": resp.document.format,
        "pages": resp.document.pages,
        "tables": resp.document.tables,
        "pictures": resp.document.pictures,
        "title": _opt_str(attrs.get("title")) or (own.label if own else None),
        "version": _opt_str(attrs.get("version")),
        "valid_from": _opt_str(attrs.get("valid_from")),
        "classification": _opt_str(attrs.get("classification")),
        "ci_id": _opt_str(attrs.get("ci_id")),
        "root_system": root_system,
        "related_doc_ids": sorted(set(related)),
        "markdown": resp.markdown,
        "graph": blob,
        "degraded": resp.degraded.model_dump(),
        "errors": resp.errors,
        "warnings": resp.warnings,
        "timings_s": resp.timings_s,
        "versions": resp.versions,
        "counts": {"chunks": len(chunks), "nodes": len(nodes), "edges": len(edge_ids), "documents": 1},
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
        "embedding_text_prefix": embedding_text_prefix,
    }
    return IndexBatch(
        doc_id=doc_id,
        doc_id_source=doc_id_source,
        doc_sha256=sha,
        run_id=run_id,
        indexed_at=indexed_at,
        chunks=chunks,
        nodes=nodes,
        document=document,
        edge_ids=edge_ids,
    )


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def bulk_actions(batch: IndexBatch, names: IndexNames) -> Iterator[dict[str, Any]]:
    """Bulk actions with deterministic ids: ``index`` overwrites, so re-running is an upsert."""
    for c in batch.chunks:
        yield {"_op_type": "index", "_index": names.chunks, "_id": c["chunk_id"], "_source": c}
    for n in batch.nodes:
        yield {"_op_type": "index", "_index": names.nodes, "_id": node_doc_id(batch.sha12, n["node_id"]), "_source": n}
    yield {"_op_type": "index", "_index": names.documents, "_id": batch.doc_id, "_source": batch.document}
