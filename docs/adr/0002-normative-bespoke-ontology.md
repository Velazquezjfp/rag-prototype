# ADR-0002: The ontology stays bespoke and normative; OWL is generated

## Context
An OWL artifact is required for sharing with other teams. LinkML was initially recommended,
since it compiles one YAML source into JSON Schema, OWL, SHACL and Pydantic, and docling-graph
accepts it. Then an existing `ontology.yaml` was found: 873 lines, 26 classes, 32 relations,
with a working bespoke generator.

## Decision
Keep `ontology.yaml` in its own format as the single source of truth. Add
`ontology_to_owl.py` alongside the existing `ontology_to_pydantic.py`, sharing the loader.
**LinkML is rejected.**

## Rationale
LinkML cannot express the file's most valuable content: `relations[].polarity`,
`negative_assertions`, `extraction_rule_negation`, `cues_de` anchor texts, `table_hints`,
`high_yield_tables`, `competency_questions` with traversal paths, `expected_graph_shape`,
`identity.normalize` rules, and `conflict_policy`. Porting would either destroy these or bury
them in `annotations` blocks no generator reads.

The OWL requirement is read-only viewing, not round-tripping, so a generated OWL file
satisfies it completely. Interposing LinkML would mean maintaining a translation into a format
that cannot hold the best content, for no gain over generating OWL directly.

## Also decided
The ontology is **normative, not descriptive**: it states what a Betriebshandbuch *should*
contain. This is deliberate. It is why the ontology may be cleaner than reality, and it is
what makes it usable as a documentation-quality yardstick (see ADR-0013).

An agent may *draft* ontology extensions from real manuals. It may not own the identity rules,
conflict policy, negation policy or competency questions — those are judgment. An
agent-derived ontology would be descriptive and would encode the current mess as the target.

## Consequences
- The OWL export carries classes, relations with domain/range, enums and labels only.
- Exactly one generated Pydantic model, produced by `make`. Delete hand-maintained copies.
- Rename `ontology_2_pydantic.py` to `ontology_to_pydantic.py` to match its own docstring.
