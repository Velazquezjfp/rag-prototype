# ADR-0003: Entity resolution is deterministic, from ontology identity keys

## Context
Cross-document edges only exist if the same real entity extracted from two manuals resolves to
one node. Across 30 manuals, a shared service will appear as `Git-Server`, `Git Server`,
`GitServer`, `Bitbucket` and worse.

## Decision
Resolution is driven entirely by `ontology.yaml → classes.*.identity`. No LLM canonicalization
at ingest. Unmapped mentions go to a review queue and fail `expected_graph_shape`.

## Rationale
The ontology already specifies this per class, with more care than a generic scheme would:
`Person` merges on `strip_titles_then_casefold`, keeping the title in the label; `System` on
casefolded `label` with `ci_id` as secondary key; `Host` on `hostname`; `Incident` on
`ticket_id`; `Component`, `MaintenanceWindow` and `FailureMode` are `scope: system` so two
systems may each have a "Dispatcher".

LLM clustering was rejected for the prototype because it is non-deterministic across runs, it
fails precisely on German compounds and abbreviations, and a wrong merge produces a confidently
wrong cross-reference in front of stakeholders — the worst available failure.

## Consequences
- Model the vocabulary as `permissible_values` so unmapped mentions are validation errors, not
  silent new nodes.
- Because every key is content-based, re-ingesting one updated manual replaces that document's
  subgraph without renumbering anything else. This is how "the manuals are alive" is handled.
- An LLM *suggester* proposing vocabulary additions for human acceptance is roadmap.
