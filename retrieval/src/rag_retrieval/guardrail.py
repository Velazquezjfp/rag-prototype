"""ADR-0011: answer "Dazu steht nichts in den Handbüchern." without calling the model when the evidence is weak.

Rank- and channel-based, never an absolute cosine threshold (REPORT §7: bge-m3 scores compress to ~0.96 for
everything). Evidence is strong when an exact channel fired (identifier or a resolved node label). Otherwise the
question has to show lexical overlap with the corpus AND one of the top hits must be found by two *search* channels.
The graph channel never counts here: in slow mode it is seeded from the very hits under suspicion."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .models import ChunkHit

SEARCH_CHANNELS = frozenset({"knn", "bm25", "identifier", "label"})


@dataclass(frozen=True)
class Verdict:
    weak_evidence: bool
    reason: str | None = None


def decide(
    *,
    enabled: bool,
    hits: Sequence[ChunkHit],
    identifier_hits: int,
    label_nodes: int,
    bm25_returned: int,
    top_n: int = 3,
    min_agreeing_channels: int = 2,
) -> Verdict:
    if not enabled:
        return Verdict(False)
    if identifier_hits > 0 or label_nodes > 0:
        return Verdict(False)
    if not hits:
        return Verdict(True, "no chunk found by any channel")
    if bm25_returned == 0:
        return Verdict(True, "no lexical overlap with the corpus (BM25 returned nothing)")
    top = list(hits[:top_n])
    if not any(len(set(h.channel_names) & SEARCH_CHANNELS) >= min_agreeing_channels for h in top):
        channels = sorted({c for h in top for c in h.channel_names if c in SEARCH_CHANNELS})
        return Verdict(True, f"top {len(top)} hits were each found by a single channel only ({', '.join(channels)})")
    return Verdict(False)
