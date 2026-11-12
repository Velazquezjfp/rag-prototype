# ADR-0001: Real typed edges from mandated sections, not a synthetic root

## Context
The initial plan proposed per-document graphs joined to one artificial "Operative System"
parent node, on the assumption that real cross-document relationships were unknown. The
docling-graph process diagram had also deferred edges entirely to a "Phase 2".

## Decision
Extract real typed edges from the sections the Betriebshandbuch template mandates:
`Anbindung an andere Schnittstellen`, `Schnittstellen`, `Basisdienste`, `Vernetzung`.

## Rationale
Cross-document edges demonstrably exist in the source material. In the original anonymized
corpus, `vup-anonymisiert.txt` names MARiS directly in its `Schnittstellen` section, and MARiS
is the subject of another manual. In the fictional corpus the couplings are explicit and
documented. Because the template *requires* those sections, the edges are structurally
guaranteed in future manuals, so the approach generalizes rather than being corpus-specific.

docling-graph supports edges natively via its `edge()` helper, which adds `edge_label` metadata
to the schema, so the "no edges" position cost capability for no technical reason.

## Consequences
- A star topology through a meaningless root is rejected: it gives every document pair a
  length-2 path, so "which systems use the Git-Server" returns everything.
- It also could not show a graph gain in the measurement, since the retrieval it enables is
  equivalent to a metadata filter.
- The platform hub node is real and documented (CaaS-Plattform, ZSD), so no invention needed.
