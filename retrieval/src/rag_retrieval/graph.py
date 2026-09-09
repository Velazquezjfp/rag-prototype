"""In-memory union of the per-document graphs stored in ``bhb-documents.graph`` (node-link JSON, ADR-0005).

Nodes are keyed by docling-graph's content-addressed ``node_id`` — the same entity in two manuals has the same id,
so the union is the cross-document graph without a merge step (REPORT §7: group by node_id, keep per-book attributes
side by side). Edges are keyed by their ``edge_id``; a fixture graph without ids gets them computed the way the
indexer does. One hop over ALL relation types (graph-retrieval-patterns §4.4); no networkx needed for that."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from opensearch_index.identity import edge_id as compute_edge_id
from opensearch_index.identity import norm_key
from opensearch_index.schemas import GraphEdge

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[\w][\w\-./]*", re.UNICODE)

# entity types that carry the answer most often; the rest sort after them (start-node and entity-card order)
TYPE_PRIORITY: tuple[str, ...] = (
    "ImpactStatement",
    "Incident",
    "Person",
    "Procedure",
    "Component",
    "System",
    "StartupStep",
    "FirewallRule",
    "Host",
)
# never seed the expansion from these: every chunk of a manual points at its Document node
LOW_VALUE_TYPES: frozenset[str] = frozenset({"Document", "Term"})


def type_rank(t: str | None) -> int:
    return TYPE_PRIORITY.index(t) if t in TYPE_PRIORITY else len(TYPE_PRIORITY)


def tokenize(text: str, *, split_compounds: bool = False) -> list[str]:
    """``norm_key`` tokens of a label or question: casefolded words, hyphen/slash compounds kept whole and,
    with ``split_compounds``, additionally their parts (``pki-ausfall`` -> ``pki``, ``ausfall``)."""
    out: list[str] = []
    for tok in TOKEN_RE.findall(norm_key(text)):
        out.append(tok)
        if split_compounds and re.search(r"[-/]", tok):
            out.extend(p for p in re.split(r"[-/]+", tok) if p)
    return out


@dataclass(frozen=True)
class GNode:
    id: str
    type: str
    label: str
    aliases: tuple[str, ...]
    attributes: Mapping[str, Any]
    quote: str | None
    pages: tuple[int, ...]
    chunk_ids: tuple[str, ...]
    doc_id: str


@dataclass(frozen=True)
class GEdge:
    id: str
    source: str
    target: str
    type: str
    polarity: str
    qualifier: str | None
    quote: str | None
    properties: Mapping[str, Any]
    pages: tuple[int, ...]
    chunk_ids: tuple[str, ...]
    doc_id: str

    def other(self, node_id: str) -> str:
        return self.target if self.source == node_id else self.source


@dataclass(frozen=True)
class DocInfo:
    doc_id: str
    title: str | None = None
    root_system: str | None = None
    embedding_model: str | None = None
    embedding_text_prefix: str | None = None
    embedding_dim: int | None = None
    counts: Mapping[str, int] = field(default_factory=dict)


@dataclass
class GraphStats:
    documents: list[str]
    node_ids: int
    node_records: int
    edge_ids: int
    edge_records: int
    shared_node_ids: int
    negative_edges: int
    labels: int
    nodes_by_type: dict[str, int]
    edges_by_type: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class GraphStore:
    def __init__(self) -> None:
        self.documents: dict[str, DocInfo] = {}
        self._nodes: dict[str, list[GNode]] = defaultdict(list)
        self._edges: dict[str, list[GEdge]] = defaultdict(list)
        self._adj: dict[str, set[str]] = defaultdict(set)
        self._label_index: dict[str, set[str]] = defaultdict(set)  # norm_key(label|alias) -> node ids
        self._label_forms: dict[str, set[str]] = defaultdict(set)  # norm_key -> original spellings
        self._token_index: dict[str, set[str]] = defaultdict(set)  # label token -> node ids
        self._label_tokens: dict[str, set[str]] = defaultdict(set)  # node id -> tokens of label + aliases

    # ------------------------------------------------------------------ loading

    @classmethod
    def from_blobs(cls, blobs: Iterable[tuple[str, dict[str, Any] | None]]) -> GraphStore:
        store = cls()
        for doc_id, graph in blobs:
            store.add_document(doc_id, graph)
        return store

    @classmethod
    def from_documents(cls, documents: Iterable[dict[str, Any]]) -> GraphStore:
        """From ``bhb-documents`` records (``_source`` with ``doc_id``, ``graph``, title, embedding fields)."""
        store = cls()
        for src in documents:
            doc_id = src.get("doc_id")
            if not doc_id:
                continue
            store.add_document(
                doc_id,
                src.get("graph"),
                info=DocInfo(
                    doc_id=doc_id,
                    title=src.get("title"),
                    root_system=src.get("root_system"),
                    embedding_model=src.get("embedding_model"),
                    embedding_text_prefix=src.get("embedding_text_prefix"),
                    embedding_dim=src.get("embedding_dim"),
                    counts=src.get("counts") or {},
                ),
            )
        return store

    def add_document(self, doc_id: str, graph: dict[str, Any] | None, *, info: DocInfo | None = None) -> None:
        self.documents[doc_id] = info or DocInfo(doc_id=doc_id)
        if not graph:
            log.warning("document %s has no graph blob", doc_id)
            return
        for n in graph.get("nodes") or []:
            prov = n.get("provenance") or {}
            node = GNode(
                id=n["id"],
                type=n.get("type") or "?",
                label=n.get("label") or n["id"],
                aliases=tuple(a for a in (n.get("aliases") or []) if a),
                attributes=dict(n.get("attributes") or {}),
                quote=n.get("quote"),
                pages=tuple(int(p) for p in prov.get("pages") or []),
                chunk_ids=tuple(prov.get("chunk_ids") or []),
                doc_id=doc_id,
            )
            self._nodes[node.id].append(node)
            for form in (node.label, *node.aliases):
                key = norm_key(form)
                if key:
                    self._label_index[key].add(node.id)
                    self._label_forms[key].add(form)
                for tok in tokenize(form, split_compounds=True):
                    self._token_index[tok].add(node.id)
                    self._label_tokens[node.id].add(tok)
        for e in graph.get("edges") or []:
            eid = e.get("id") or compute_edge_id(GraphEdge.model_validate(e))
            prov = e.get("provenance") or {}
            edge = GEdge(
                id=eid,
                source=e["source"],
                target=e["target"],
                type=e.get("type") or "?",
                polarity=e.get("polarity") or "positive",
                qualifier=e.get("qualifier"),
                quote=e.get("quote"),
                properties=dict(e.get("properties") or {}),
                pages=tuple(int(p) for p in prov.get("pages") or []),
                chunk_ids=tuple(prov.get("chunk_ids") or []),
                doc_id=doc_id,
            )
            self._edges[eid].append(edge)
            self._adj[edge.source].add(eid)
            self._adj[edge.target].add(eid)

    # ------------------------------------------------------------------ lookups

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def node(self, node_id: str) -> GNode | None:
        occ = self._nodes.get(node_id)
        return occ[0] if occ else None

    def occurrences(self, node_id: str) -> list[GNode]:
        return list(self._nodes.get(node_id, ()))

    def label(self, node_id: str) -> str:
        n = self.node(node_id)
        return n.label if n else node_id

    def type_of(self, node_id: str) -> str | None:
        n = self.node(node_id)
        return n.type if n else None

    def label_forms_of(self, node_id: str) -> set[str]:
        forms: set[str] = set()
        for n in self.occurrences(node_id):
            forms.add(n.label)
            forms.update(n.aliases)
        return forms

    def resolve(self, key: str) -> set[str]:
        """Node ids whose label or alias normalizes (``norm_key``) to ``key``."""
        return set(self._label_index.get(key, ()))

    def label_forms(self, key: str) -> set[str]:
        return set(self._label_forms.get(key, ()))

    @property
    def label_index(self) -> Mapping[str, set[str]]:
        return self._label_index

    def label_tokens(self, node_id: str) -> set[str]:
        return set(self._label_tokens.get(node_id, ()))

    def nodes_with_token(self, token: str) -> set[str]:
        """Node ids whose label or an alias contains this (normalized) word."""
        return set(self._token_index.get(token, ()))

    def edge(self, edge_id: str) -> list[GEdge]:
        return list(self._edges.get(edge_id, ()))

    def edge_ids_of(self, node_id: str) -> set[str]:
        return set(self._adj.get(node_id, ()))

    def title(self, doc_id: str) -> str | None:
        info = self.documents.get(doc_id)
        return info.title if info else None

    @property
    def titles(self) -> dict[str, str]:
        return {d: i.title for d, i in self.documents.items() if i.title}

    # ------------------------------------------------------------------ expansion

    def expand(
        self, start_nodes: Iterable[str], *, doc_ids: Collection[str] | None = None
    ) -> dict[str, list[GEdge]]:
        """One hop: every edge touching a start node, over all relation types; ``edge_id -> occurrences``
        (the same assertion in two books = one key, two occurrences). ``doc_ids`` restricts to those books."""
        out: dict[str, list[GEdge]] = {}
        for nid in start_nodes:
            for eid in self._adj.get(nid, ()):
                if eid in out:
                    continue
                occ = [e for e in self._edges[eid] if doc_ids is None or e.doc_id in doc_ids]
                if occ:
                    out[eid] = occ
        return out

    def neighbours(self, node_id: str, *, doc_ids: Collection[str] | None = None) -> set[str]:
        return {e.other(node_id) for occ in self.expand([node_id], doc_ids=doc_ids).values() for e in occ}

    def nodes_of_type(self, types: Collection[str], *, doc_ids: Collection[str] | None = None) -> list[str]:
        """Node ids of these types (ordered by type position, casefolded label, id); ``doc_ids`` keeps only nodes
        with an occurrence in those books. Full scan — the graph is small and in memory (REQ-002 R3, REQ-001 D3)."""
        order = {t: i for i, t in enumerate(types)}
        wanted = set(doc_ids) if doc_ids is not None else None
        out: list[tuple[int, str, str]] = []
        for nid, occ in self._nodes.items():
            first = occ[0]
            if first.type not in order:
                continue
            if wanted is not None and not any(n.doc_id in wanted for n in occ):
                continue
            out.append((order[first.type], first.label.casefold(), nid))
        return [nid for _, _, nid in sorted(out)]

    # ------------------------------------------------------------------ stats

    def stats(self) -> GraphStats:
        by_type: dict[str, int] = defaultdict(int)
        for occ in self._nodes.values():
            by_type[occ[0].type] += 1
        edges_by_type: dict[str, int] = defaultdict(int)
        negative = 0
        for occ in self._edges.values():
            edges_by_type[occ[0].type] += 1
            if occ[0].polarity == "negative":
                negative += 1
        return GraphStats(
            documents=sorted(self.documents),
            node_ids=len(self._nodes),
            node_records=sum(len(o) for o in self._nodes.values()),
            edge_ids=len(self._edges),
            edge_records=sum(len(o) for o in self._edges.values()),
            shared_node_ids=sum(1 for o in self._nodes.values() if len({n.doc_id for n in o}) > 1),
            negative_edges=negative,
            labels=len(self._label_index),
            nodes_by_type=dict(sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))),
            edges_by_type=dict(sorted(edges_by_type.items(), key=lambda kv: (-kv[1], kv[0]))),
        )
