# ADR-0011: No compaction; hard turn cap plus query rewriting

## Context
The plan asked for auto-compaction or suggesting a new session, and specified "history, no
memory", without defining whether turn N's retrieval sees turn N-1.

## Decision
**No compaction.** A hard turn cap that suggests starting a new session. History is handled by
**query rewriting**: before retrieval, rewrite the question into a standalone question using the
last two turns, log both forms, retrieve on the rewritten one.

## Rationale
Qwen3-Coder-30B-A3B has a 262K context and the cap is 10 messages per user per day. A
conversation cannot plausibly overflow, so compaction is machinery for a condition that cannot
arise. Recording the omission deliberately is better than implementing it "just in case".

Query rewriting makes follow-ups like "und bei VPP?" work while keeping the retrieval layer
stateless, which preserves A/B integrity — a stateful retriever would make the fast/slow
comparison depend on conversation position.

## On-topic guardrail
**Retrieval-score threshold first, system prompt second.** If no chunk clears the threshold,
answer *"dazu steht nichts in den Handbüchern"* **without calling the model at all**.

A prompt-only guardrail is bypassable, and a coder model is less reliably steerable in German
than a general instruct model would be, so the guarantee must not live only there.

## Consequences
- Conversations are resumable, stored in Postgres.
- Both question forms are logged, which also feeds the fallback backlog.
