"""Client-side reciprocal rank fusion over the channel lists (SPEC §7.5), deduplication by chunk id with the union
of channel evidence, and grouping of table parts under one caption.

Fused here rather than by the ``bhb-rrf`` search pipeline because the pipeline returns one score and cannot take
the graph list — the per-channel ranks are what the UI shows and what the guardrail reasons about."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .models import ChannelEvidence, ChunkGroup, ChunkHit


@dataclass
class RawHit:
    chunk_id: str
    score: float | None
    source: dict[str, Any]
    via: str | None = None


@dataclass
class FusedHit:
    chunk_id: str
    fused_score: float
    channels: list[ChannelEvidence] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)

    @property
    def best_rank(self) -> int:
        return min(c.rank for c in self.channels)


def rrf(lists: Mapping[str, Sequence[RawHit]], *, rank_constant: int = 60) -> list[FusedHit]:
    """``score = Σ 1/(rank_constant + rank)`` over the lists a chunk appears in (ranks 1-based per list).

    Ties: more channels first, then the better best-rank, then chunk id (deterministic)."""
    scores: dict[str, float] = defaultdict(float)
    evidence: dict[str, list[ChannelEvidence]] = defaultdict(list)
    sources: dict[str, dict[str, Any]] = {}
    for channel, hits in lists.items():
        seen: set[str] = set()
        rank = 0
        for h in hits:
            if h.chunk_id in seen:
                continue
            seen.add(h.chunk_id)
            rank += 1
            scores[h.chunk_id] += 1.0 / (rank_constant + rank)
            evidence[h.chunk_id].append(ChannelEvidence(channel=channel, rank=rank, score=h.score, via=h.via))  # type: ignore[arg-type]
            if h.source and (h.chunk_id not in sources or len(h.source) > len(sources[h.chunk_id])):
                sources[h.chunk_id] = h.source
    fused = [
        FusedHit(chunk_id=cid, fused_score=scores[cid], channels=evidence[cid], source=sources.get(cid, {}))
        for cid in scores
    ]
    fused.sort(key=lambda f: (-round(f.fused_score, 12), -len(f.channels), f.best_rank, f.chunk_id))
    return fused


def group_key_of(source: Mapping[str, Any]) -> str:
    """Table parts of one table share ``doc_id`` and ``caption``; everything else is its own group."""
    if source.get("kind") == "table" and source.get("caption"):
        return f"{source.get('doc_id')}|table|{str(source['caption']).strip()}"
    return str(source.get("chunk_id"))


def to_chunk_hits(
    fused: Sequence[FusedHit], *, titles: Mapping[str, str] | None = None, limit: int | None = None
) -> list[ChunkHit]:
    titles = titles or {}
    out: list[ChunkHit] = []
    for i, f in enumerate(fused[:limit] if limit else fused, start=1):
        s = f.source
        if not s:
            continue
        out.append(
            ChunkHit(
                chunk_id=f.chunk_id,
                doc_id=s.get("doc_id", "?"),
                doc_title=titles.get(s.get("doc_id", "")),
                kind=s.get("kind") or "text",
                page_numbers=list(s.get("page_numbers") or []),
                heading_breadcrumb=list(s.get("heading_breadcrumb") or []),
                caption=s.get("caption"),
                body_text=s.get("body_text") or "",
                text=s.get("text") or "",
                token_count=int(s.get("token_count") or 0),
                identifiers=list(s.get("identifiers") or []),
                node_ids=list(s.get("node_ids") or []),
                node_labels=list(s.get("node_labels") or []),
                edge_ids=list(s.get("edge_ids") or []),
                rank=i,
                fused_score=f.fused_score,
                channels=list(f.channels),
                group_key=group_key_of(s),
            )
        )
    return out


def group_hits(hits: Sequence[ChunkHit]) -> list[ChunkGroup]:
    """Groups in the order of their best part; parts inside a group in chunk-id (= document) order."""
    by_key: dict[str, list[ChunkHit]] = {}
    for h in hits:
        by_key.setdefault(h.group_key, []).append(h)
    groups: list[ChunkGroup] = []
    for key, parts in by_key.items():
        parts_sorted = sorted(parts, key=lambda p: p.chunk_id)
        best = min(parts, key=lambda p: p.rank)
        pages = sorted({p for part in parts for p in part.page_numbers})
        groups.append(
            ChunkGroup(
                key=key,
                doc_id=best.doc_id,
                doc_title=best.doc_title,
                kind=best.kind,
                caption=best.caption,
                heading_breadcrumb=best.heading_breadcrumb,
                pages=pages,
                chunk_ids=[p.chunk_id for p in parts_sorted],
                parts=parts_sorted,
                rank=best.rank,
                fused_score=max(p.fused_score for p in parts),
            )
        )
    groups.sort(key=lambda g: g.rank)
    for i, g in enumerate(groups, start=1):
        g.rank = i
    return groups
