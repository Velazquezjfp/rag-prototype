# ADR-0006: Reciprocal Rank Fusion; cross-encoder reranker deferred

## Context
Slow mode produces five ranked lists: dense kNN, BM25, `identifiers` term match, `node_labels`
term match, and graph-expanded chunks.

## Decision
Fuse with **Reciprocal Rank Fusion**, natively supported by OpenSearch hybrid search.
Deduplicate on `(doc_id, page, chunk_id)`, keeping the union of reasons a chunk was retrieved.

## Rationale
The score scales are not comparable. Cosine similarity, BM25 relevance and boolean term matches
cannot be meaningfully summed. RRF uses rank position only, so it needs no model, no VRAM and
no tuning — which is exactly right before a golden set exists to calibrate weights against.

Weighted score normalization was rejected: tuning weights without a golden set is guessing, and
once the golden set exists a cross-encoder is the better investment.

## Consequences
- Graph-expanded chunks join as one more ranked list, ordered by traversal depth then edge-type
  priority, so a depth-1 `DEPENDS_ON` neighbour outranks a depth-2 one.
- "Found by both hybrid search and the graph" is kept as a ranking signal, not discarded as a
  duplicate.
- A **cross-encoder reranker is the highest-value later addition** and is deliberately deferred
  until measurement exists.
