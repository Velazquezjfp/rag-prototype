# ADR-0010: Figures may confirm edges, never create them

## Context
27 diagrams, and the demo must show that the system understands them. granite VLM is in the
ingestion pipeline.

## Decision
The VLM does two separate jobs per figure. **Describe:** a German description indexed as a
normal citeable chunk carrying its `Abbildung` caption. **Confirm:** asked whether specific
candidate edges *already extracted from tables and text* are visible; a yes raises confidence
and adds the figure as a second provenance source.

Figures never create edges.

## Rationale
A VLM inventing `DEPENDS_ON` from a box-and-arrow picture is unverifiable, and that is exactly
how a confident wrong cross-reference reaches a live demo. A VLM confirming an edge already
found in a table is cheap corroboration with no downside.

`ontology.yaml → figures.note` independently agrees: the images *"bestätigen"* RUNS_ON,
LOCATED_IN, DEPENDS_ON and PRECEDES.

## Consequences
- `images_scale = 3.0` (~216 dpi) is mandatory. Diagrams are embedded at ~4500 px but laid out
  at 180 mm; a lower render factor makes labels unreadable.
- Validate the docling render against `demo-corpus/diagramme-png/` before trusting VLM output.
- Descriptions are what make diagram-sourced answers possible *and* referenceable — without
  them a figure can never be cited.
