"""Result types at the module boundary (pydantic: chat-system stores them as JSON and renders them).

A ``RetrievalResult`` is a superset of SPEC §7.1's ``list[Chunk]``: the fused, deduplicated chunks with the channels
that found each one, the same chunks grouped (table parts under one caption), the graph facts and entity cards from
the 1-hop expansion, citations with provenance for every source, the guardrail verdict and diagnostics."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, Field

Channel = Literal["knn", "bm25", "identifier", "label", "graph"]
Polarity = Literal["positive", "negative", "unknown"]
Mode = Literal["fast", "slow"]
MatchedBy = Literal["label", "identifier", "hit", "neighbour"]


def format_pages(pages: Iterable[int]) -> str:
    """``[8, 9]`` -> ``8–9``; ``[1, 2, 26]`` -> ``1–2, 26``; ``[]`` -> ``?``."""
    ps = sorted({int(p) for p in pages})
    if not ps:
        return "?"
    runs: list[tuple[int, int]] = []
    start = prev = ps[0]
    for p in ps[1:]:
        if p == prev + 1:
            prev = p
            continue
        runs.append((start, prev))
        start = prev = p
    runs.append((start, prev))
    return ", ".join(f"{a}" if a == b else f"{a}–{b}" for a, b in runs)


def cite(doc_id: str, pages: Iterable[int]) -> str:
    return f"{doc_id} S. {format_pages(pages)}"


class ChannelEvidence(BaseModel):
    channel: Channel
    rank: int
    score: float | None = None
    via: str | None = None  # the identifier / label that matched, or "DEPENDS_ON from Vault" for graph chunks


class ChunkHit(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str | None = None
    kind: str = "text"
    page_numbers: list[int] = Field(default_factory=list)
    heading_breadcrumb: list[str] = Field(default_factory=list)
    caption: str | None = None
    body_text: str = ""
    text: str = ""
    token_count: int = 0
    identifiers: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    node_labels: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
    rank: int
    fused_score: float
    channels: list[ChannelEvidence] = Field(default_factory=list)
    group_key: str

    @property
    def cite(self) -> str:
        return cite(self.doc_id, self.page_numbers)

    @property
    def channel_names(self) -> list[str]:
        seen: list[str] = []
        for c in self.channels:
            if c.channel not in seen:
                seen.append(c.channel)
        return seen


class ChunkGroup(BaseModel):
    """Table parts (same document, same caption) rendered as one source; text chunks are groups of one."""

    key: str
    doc_id: str
    doc_title: str | None = None
    kind: str = "text"
    caption: str | None = None
    heading_breadcrumb: list[str] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    parts: list[ChunkHit] = Field(default_factory=list)
    rank: int
    fused_score: float

    @property
    def cite(self) -> str:
        return cite(self.doc_id, self.pages)

    @property
    def channel_names(self) -> list[str]:
        seen: list[str] = []
        for p in self.parts:
            for c in p.channel_names:
                if c not in seen:
                    seen.append(c)
        return seen

    @property
    def token_count(self) -> int:
        return sum(p.token_count for p in self.parts)


class GraphFact(BaseModel):
    edge_id: str
    doc_ids: list[str]
    source_id: str
    source_label: str
    source_type: str | None = None
    relation: str
    relation_de: str | None = None
    target_id: str
    target_label: str
    target_type: str | None = None
    polarity: Polarity = "positive"
    qualifier: str | None = None
    quote: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    pages: list[int] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    via_start_node: str | None = None
    rendered: str


class EntityOccurrence(BaseModel):
    doc_id: str
    label: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    pages: list[int] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    quote: str | None = None


class EntityCard(BaseModel):
    node_ids: list[str]
    type: str
    label: str
    aliases: list[str] = Field(default_factory=list)
    occurrences: list[EntityOccurrence] = Field(default_factory=list)
    matched_by: MatchedBy
    rendered: str


class Citation(BaseModel):
    key: str  # "BHB-PLT-0007 S. 19"
    doc_id: str
    doc_title: str | None = None
    pages: list[int] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)


class ChannelStats(BaseModel):
    channel: Channel
    requested_k: int
    returned: int
    took_ms: int | None = None
    query_terms: list[str] = Field(default_factory=list)


class Diagnostics(BaseModel):
    question: str
    rewritten_question: str | None = None
    mode: Mode
    identifiers: list[str] = Field(default_factory=list)
    label_candidates: list[str] = Field(default_factory=list)
    resolved_labels: list[str] = Field(default_factory=list)
    partial_labels: list[str] = Field(default_factory=list)  # labels containing >= 2 question words
    start_nodes: list[str] = Field(default_factory=list)
    channels: list[ChannelStats] = Field(default_factory=list)
    timings_ms: dict[str, int] = Field(default_factory=dict)
    embedding_model: str | None = None
    indexed_embedding_models: list[str] = Field(default_factory=list)
    indexed_text_prefix: str | None = None
    warnings: list[str] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    question: str
    mode: Mode
    chunks: list[ChunkHit] = Field(default_factory=list)
    groups: list[ChunkGroup] = Field(default_factory=list)
    facts: list[GraphFact] = Field(default_factory=list)
    entities: list[EntityCard] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    weak_evidence: bool = False
    weak_evidence_reason: str | None = None
    diagnostics: Diagnostics


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class RenderedContext(BaseModel):
    text: str
    token_estimate: int
    included_chunk_ids: list[str] = Field(default_factory=list)
    included_edge_ids: list[str] = Field(default_factory=list)
    dropped_chunk_ids: list[str] = Field(default_factory=list)


class RewriteResult(BaseModel):
    original: str
    rewritten: str
    used_llm: bool
    error: str | None = None
