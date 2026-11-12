# ADR-0009: multilingual-e5-large, and its 512-token cap drives chunking

## Context
BGE-M3 was recommended for its dense-plus-sparse output matching the hybrid design.
`multilingual-e5-large` was already available internally, which dominates.

## Decision
Use `multilingual-e5-large`. 512-token max sequence length, 1024 dimensions, XLM-RoBERTa,
100 languages, CPU-capable at this corpus size.

## Rationale
Availability beats a leaderboard margin. Losing BGE-M3's sparse output costs nothing, because
OpenSearch BM25 was always going to be the lexical channel.

## Two non-negotiable consequences
1. **Prefixes are mandatory.** `query: ` on questions, `passage: ` on indexed chunks. The model
   is trained that way and omitting them causes silent quality degradation. The *rewritten*
   standalone question is what receives `query: `.
2. **512 tokens truncates silently.** sentence-transformers cuts at `max_seq_length` with no
   warning, so an over-long table chunk never has its tail embedded and retrieval simply never
   finds those rows. This is the most likely quiet quality bug in the system.

## Chunking consequences
- Target ~250 German words per chunk. German compounds tokenize to several subwords each under
  XLM-R, roughly 1.5–2.2 tokens per word, so 512 tokens is only ~230–340 words.
- **Hard cap asserted by tokenizer count, not character count**, failing the build on breach.
- **Wide tables split by row groups, repeating caption and header row on each part.** Required
  for the port matrices, `BHB-PLT-0007` Tabelle 6, and `BHB-PLT-0001` Tabellen 12 and 13.
- One-row-per-chunk rejected: it destroys the row-to-row context that makes `PRECEDES` and the
  impact matrix meaningful, and floods top-k with near-identical fragments.
- Summarizing long tables rejected: a summary is unciteable at row level, breaking the
  reference requirement.

## Swappability
Put the embedder behind an interface declaring `dim` and `max_tokens`. Swapping to BGE-M3 is an
index-mapping change plus a full re-index — minutes at 205 pages.
