# ADR-0004: Retrieval is a pure function with fast/slow modes; no agent framework

## Context
LangGraph and Google ADK were both considered, including for asking the user which system they
meant when a question is ambiguous.

## Decision
`retrieve(question: str, use_graph: bool) -> list[Chunk]` — pure and typed. Orchestration in
plain Python. Two modes: **fast** (hybrid query only) and **slow** (plus typed traversal).
Traversal is **intent-routed** via `docs/retrieval-intents.md`, not model-chosen.

## Rationale
For a fixed two-step pipeline, a framework adds a dependency to negotiate through Artifactory
and a mental model, and buys nothing. Asking the user which system they meant is an `if`
statement on the number of candidate `System` nodes, not an agent loop.

Intent-routing over model-chosen traversal: it is deterministic and explainable — "it followed
the dependency edges" is a sentence a stakeholder accepts, which centrality or a model's choice
is not — and an unrecognised question degrades to fast mode, a shallower correct answer rather
than a failure.

The perceived "the assistant is exploring the graph" behaviour is achieved by streaming a
status line during expansion, with no framework involved.

## Consequences
- The A/B measures **traversal vs no traversal**, not "graph vs vectors", because the
  identifier and node-label clauses use the graph's identity layer in both modes. State this
  in the eval so the comparison cannot be called a strawman.
- Wrapping `retrieve` in LangGraph later is a wrapper, not a rewrite.
- Rejected: expanding along all 32 relations, and centrality-based importance. Hubs are
  declared data (`expected_graph_shape.hub_systems`), not a computed heuristic.
