# ADR-0012: Split evaluation — deterministic metrics on target, Claude judge externally

## Context
The answering model is fixed to Qwen3-Coder-30B-A3B-Instruct. RAGAS answer metrics need an LLM
judge, and a model judging its own German output is not a defensible number. The target
environment has no external network.

## Decision
- **Deterministic retrieval metrics** (context precision, context recall against known-correct
  source chunks) run **on Qwen3-Coder in the target environment**.
- **Answer-quality metrics** (faithfulness, answer correctness, answer relevancy) run with
  **Claude Opus 5** (`claude-opus-5`) as the RAGAS judge, externally.

## Rationale
The air gap does not constrain evaluation, because the demo corpus is **entirely fictional**
and documented as such on every page (`TESTDOKUMENT · DIESES DOKUMENT IST FIKTIV`), with every
invented name enumerated in its README. There is nothing confidential to protect.

Deterministic metrics need no LLM and are the numbers that must hold where the system lives.
State the split explicitly in the writeup; it reads as rigour rather than as a gap.

## Golden set
Built as a separate module in `eval/`, runnable independently once the system exists.

The seven `competency_questions` are acceptance criteria and question *templates*, not a golden
set — Q1 alone instantiates five times with three different renewal paths. Instantiate the
templates with a quota each, plus three categories the templates do not cover: **negation**
(≥7, one per `negative_assertion`), **table lookup** (from the 14 `high_yield_tables`), and
**the deliberate conflict** (48 vs 38 minutes for the Vault incident, where the correct answer
explains both). Target 60–80 items.

Generate with Claude, then **verify every answer against the source page by hand**. An
unverified LLM-generated golden set measures the pipeline against a model's reading rather than
against the document. At Opus 5 rates the exercise costs single-digit dollars, so cost is not a
factor in any of these choices.
