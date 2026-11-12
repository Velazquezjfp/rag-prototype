# ADR-0013: Coverage measured against deliberately degraded input

> **Amended 2026-08-26.** Originally this ADR named a second, genuinely messy corpus on disk
> (three earlier anonymized extractions). Those files were removed from the repository. The
> **decision is unchanged** — honest measurement against degraded input — but the *mechanism*
> is now synthetic degradation, which is strictly better than the deleted files. Rationale for
> the change is in "Why synthetic is better" below.

## Context
The demo corpus is optimistic by construction. Two of five manuals were written specifically
to close the graph; identifiers are deliberately protected against line breaks so extraction
cannot split them; table captions match the extraction hints because both were authored
together. Real Confluence exports provide none of that.

The concern raised, and it is the strongest objection to the whole project: a perfectly
curated demo may not be replicable on real data, so a good demo number could mislead.

## Decision
Run the **same pipeline, same ontology, no tuning** over the fictional corpus at several
levels of deliberate degradation, and report `ontology_coverage` at each level.

`ontology_coverage` per document = populated classes and relations / defined classes and
relations.

Degradation is produced by `eval/degrade.py`, applied to the **converted document** rather
than to the PDFs. Six named defects, each mapped to the ontology element it attacks:

| Defect | Attacks |
|---|---|
| Flatten all headings to one level | section-aware chunking, `h3`/`h4` boundaries |
| Leave template sections unfilled | near-duplicate chunks; content never about the subject |
| Spell the same entity differently per document | entity resolution, every cross-document edge |
| Flatten tables to running text | ~70% of edges (`high_yield_tables`) |
| Break identifiers across line ends | the `identifiers` clause, `PARTNER_TICKET` |
| Drop partner-ticket cross-references | `INSTANCE_OF_FAILURE`, `PARTNER_TICKET` |

These are not invented. They are the defects the earlier real extractions actually exhibited.

## Why synthetic is better than the corpus it replaces
1. **Reproducible and versioned.** The deleted files were one accidental artifact of one
   anonymization run. A script is a controlled instrument.
2. **Dialled, so the output is a curve.** Coverage at several completeness levels answers the
   stakeholder's follow-up — *how good does a manual have to be* — instead of inviting it.
   Two data points cannot.
3. **Attributable.** Each defect is named, so a coverage drop maps to a cause. "Flattening the
   heading structure costs N points" is actionable feedback to the documentation owners, which
   is this ADR's second deliverable.
4. **No provenance question.** Everything derives from the fictional corpus.

## Scope limit
Degradation is applied after docling conversion. This measures **ontology coverage under
degraded content**. It does **not** measure docling robustness against badly-produced PDFs,
which remains unmeasured — state that rather than letting the curve imply otherwise.

## Second deliverable
Coverage doubles as a **documentation-quality audit**: the system reports which manuals are
too incomplete to be useful and which sections are missing. For an organisation with 20–30
living manuals that is independently valuable, and it is a by-product of work already being
done. It is why the ontology must stay normative (ADR-0002).

## Consequences
- Surfaced as **metadata in the UI**, openable on demand. Primary output stays the answer and
  its references only.
- Lives in `eval/`, so it runs in the same session as the golden set (ADR-0012).
- If this is ever dropped, the writeup must state explicitly that extraction yield on
  production manuals is unmeasured, because the alternative is implying that it transfers.
