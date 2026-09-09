# REQ-001 — Robust question understanding without a model in the control path

| Field | Value |
|---|---|
| ID | REQ-001 |
| Module | `retrieval` (`rag_retrieval`) — owns R1–R5, R7 and the retrieval half of R6/R8 |
| Sibling document | [`chat-system/requirements/REQ-001-robust-question-understanding.md`](../../chat-system/requirements/REQ-001-robust-question-understanding.md) (R6, R8, R9 as seen by the chat) |
| Status | accepted 2026-09-08 · **phase 1 implemented 2026-09-08** (R5, R6, R7, R8); R1–R4 planned (phases 2–4) |
| Supersedes | the guardrail wording of `3-modules-plan.md` § "Guardrail"; amends ADR-0011 (documented here, ADR untouched) |
| Plan of record | `~/.claude/plans/partitioned-wondering-lake.md` (design D1–D8, phases 1–6, measured baseline) |

## 1. Motivation

Two mechanisms produce the identical sentence "Dazu steht nichts in den Handbüchern.":

1. the retrieval guardrail (`src/rag_retrieval/guardrail.py`, ADR-0011): weak evidence unless an identifier or an
   **exact** label/alias matched, or a top-3 fused chunk was found by two search channels;
2. rule 3 of the German system prompt (`src/rag_retrieval/prompt.py`): the model had to answer with exactly that
   sentence whenever the context did not contain "the answer" — applied literally by every model.

On the server (Gemma 4 26B via Ollama) general questions were pushed back although entities and facts had been
retrieved; the measured baseline on the dev box (2026-09-08, both books, `rag-retrieve ask`) showed that **all 14
on-topic regression questions pass the guardrail** and only off-topic questions are refused, so the pushback came
from rule 3 plus thinking/truncation. Beyond that symptom the system is fragile towards anything that is not a 100 %
match on an entity: typos, alias spellings, glossary terms, English words, and questions that name an *aspect*
(responsibility, procedure, firewall rules, components) without a subject.

The example questions below are a **regression set, not the design target**: the mechanisms must generalise.

## 2. Scope

In scope: question analysis, guardrail, prompt, answer path and CLI of this module. Out of scope: LangGraph or any
agentic loop; a model call inside question understanding; changes to `opensearch-index/` or `docling-graph/`; the
OpenAI-compatible endpoint stays (thinking control on Ollama is a deployment concern, see the sibling document).

## 3. Requirements

| # | Requirement | Level | Phase | Status |
|---|---|---|---|---|
| R1 | **Approximate entity linking.** Question tokens ≥ 5 chars that match no label exactly are matched fuzzily (string similarity ≥ `fuzzy_min_ratio`, default 0.86) against the label/alias token vocabulary of the in-memory graph; a hit on a complete label key counts as a *fuzzy subject node*, otherwise it becomes an anchor for partial label matches. Glossary `Term` nodes matched in the question are followed through the entities named in their `definition` (*glossary subject nodes*). Interpretations are recorded in the diagnostics and told to the model (`FUZZY_NOTE_DE`). | MUST | 2 | planned |
| R2 | **Aspect vocabulary as data.** Classes, relations and table captions of the ontology (`label_de`, `cues_de`, `table_hints`, `extraction.high_yield_tables`) plus a supplement in `config.yaml` (`vocabulary.aspects`, `vocabulary.ignore`) map question words to node types and relation types with the same normaliser (casefold, compound join/split, one German inflection suffix). New vocabulary is a YAML edit, not code. | MUST | 3 | planned |
| R3 | **Strategy matrix.** Subject found → neighbourhood expansion (today's slow mode). No subject but aspects → **overview**: all nodes of the aspect classes and all edges of the aspect relations of the allowed books, capped (`overview_max_entities` 30, `overview_max_facts` 30, `overview_max_chunks` 10, `overview_min_sources` 4), provenance chunks as the graph list, `mode="overview"`, independent of the graph toggle. Neither → search only. | MUST | 4 | planned |
| R4 | **Guardrail evidence.** Strong evidence additionally when partial, fuzzy or glossary subject nodes exist, or an overview found ≥ 1 item. The off-topic stops stay (no hit at all; BM25 returned nothing → no model call). The two-channel agreement rule stays with default 2 (`RAG__GUARDRAIL__MIN_AGREEING_CHANNELS`). Reasons name the deciding layer. | MUST | 2–3 | planned |
| R5 | **Graded prompt.** Rule 1 permits reusing and transforming earlier answers of the same conversation (script, summary, table) without adding facts. Rule 3 answers partial matches and subject-less questions by saying what the manuals contain (with sources) and asking in one sentence which system or Handbuch is meant, **naming the systems/Handbücher of the context as options**; the exact sentence "Dazu steht nichts in den Handbüchern." is reserved for the case where neither context nor earlier answers contain anything. `OVERVIEW_INSTRUCTION_DE` (compact one-line-per-entry tables, one closing question) is appended only for overview results. | MUST | 1 | **implemented** |
| R6 | **Follow-up rule.** Weak evidence refuses without a model call only on a first turn. With conversation history the model is called with the history and `WEAK_FOLLOW_UP_NOTE_DE` instead of the context (no sources rendered, nothing cited). `answer()` and `rag-retrieve ask --history-file` implement it (exit code 2 only without history). | MUST | 1 | **implemented** |
| R7 | **Conversation window.** `RetrievalSettings.history_turns` (default 3; `RAG__RETRIEVAL__HISTORY_TURNS=10` on the server) is the number of user/assistant pairs `build_messages` carries; the rewrite window stays `CHAT__RETRIEVAL__HISTORY_TURNS_FOR_REWRITE`. | MUST | 1 | **implemented** |
| R8 | **Truncation is visible.** `ChatClient.stream()` returns a `TokenStream` whose `finish_reason` is known after the iteration (`length` = cut by `max_tokens`); consumers stay duck-typed (`getattr(stream, "finish_reason", None)`). The CLI prints a note. | MUST | 1 | **implemented** |

## 4. Acceptance — behaviour classes, not answer texts

| Class | Meaning | Questions (regression set) | Verified by |
|---|---|---|---|
| `subject` | a subject node resolved (exact, fuzzy or glossary) → neighbourhood expansion, strong evidence | Wie entsiegle ich den Vault? · Keycloack neu starten (typo) · Key Cloak Neustart · Was ist Break-Glass? (glossary) · ZSD Server (alias) · TLS-Zertifikat erneuern | phase 2: `test_linking.py`, `test_regression_questions.py` |
| `overview` | no subject, aspects found → complete capped listing, strong evidence | Wie mache ich ein Update? · Wer ist verantwortlich? · Welche Befehle sind verfügbar? · Zeig alle Komponenten, die hier laufen. · Wie prüfe ich ein Update/Backup? · Welche Firewall-Regeln sind konfiguriert? · Wer ist verantwortlich und wie kontaktiere ich ihn? · Welche Wartungsfenster gibt es? · Wer ist für Grafana verantwortlich? (unknown subject: overview + "Grafana kommt nicht vor") · firewall rules (English) | phase 4: `test_retriever.py`, `make questions` |
| `search` | neither → four channels, graded prompt asks back with options | Was ist hier dokumentiert? · Mach ein Script mit diesen Befehlen (first turn) | phase 1: `test_prompt.py` (rule texts) |
| `follow-up` | weak evidence with history → model answers from the conversation | Mach ein Script mit diesen Befehlen (after an answer with commands) | phase 1: `test_embed_chat.py::test_answer_weak_follow_up_calls_the_model_with_the_note`, `test_cli.py::test_ask_weak_follow_up_with_history_calls_the_model` |
| `refuse` | off-topic: BM25 empty → canned sentence, model not called | Wie backe ich einen Apfelkuchen? · Wie ist das Wetter? | `test_retriever.py::test_weak_evidence_skips_graph_expansion`, `test_cli.py::test_ask_guardrail_exit_code_2` |

Measured baseline before phase 1 (dev box, bge-m3, gemini-dev): every on-topic question above already passes the
guardrail; "Wer ist verantwortlich?" returns 23 of 27 RESPONSIBLE_FOR facts; "Welche Firewall-Regeln sind
konfiguriert?" returns 8 of 28 FirewallRule cards and the model's enumeration was truncated at 4000 tokens. Phases
2–4 must keep every on-topic question non-weak, move the class questions to `overview`, and give the typo/glossary
questions subject nodes.

## 5. Configuration

| Key | Default | Phase |
|---|---|---|
| `RAG__RETRIEVAL__HISTORY_TURNS` | 3 (server: 10) | 1 |
| `RAG__LLM__MAX_TOKENS` | 4000 — enumerating answers and reasoning models need more; truncation is now visible (R8) | 1 (existing) |
| `RAG__RETRIEVAL__FUZZY_MIN_RATIO` / `FUZZY_MIN_CHARS` / `GLOSSARY_EXPANSION` | 0.86 / 5 / true | 2 |
| `RAG__RETRIEVAL__OVERVIEW_ENABLED` / `OVERVIEW_MAX_ENTITIES` / `OVERVIEW_MAX_FACTS` / `OVERVIEW_MAX_CHUNKS` / `OVERVIEW_MIN_SOURCES` | true / 30 / 30 / 10 / 4 | 3–4 |
| `config.yaml` `vocabulary.aspects`, `vocabulary.ignore` | seed list in the plan | 3 |
| `RAG__GUARDRAIL__MIN_AGREEING_CHANNELS` | 2; **server: 1** since 2026-09-09 — with e5 embeddings and a book filter the top-3 fused chunks are rarely found by two channels ("Wer ist verantwortlich?" on CaaS was refused); off-topic stays refused via the BM25 stop. Phases 2–4 replace the rule with evidence sources | 1 (setting) |

## 6. Affected files and tests (phase 1)

`src/rag_retrieval/prompt.py` (rules 1 and 3, `OVERVIEW_INSTRUCTION_DE`, `WEAK_FOLLOW_UP_NOTE_DE`,
`build_messages(weak_note=)`), `chat.py` (`TokenStream`, `ChatClient.stream`, `answer(max_history_turns=)` +
follow-up rule), `cli.py` (exit-2 condition, hints), `settings.py` + `config.yaml` (`history_turns`), `models.py`
(`Mode` widened by `overview`), `__init__.py` (exports), `.env.example`. Tests: `tests/unit/test_prompt.py`,
`test_embed_chat.py`, `test_cli.py`, `test_settings.py`.

## 7. Traceability

ADR-0011 ("retrieval-score threshold first, system prompt second; refuse without a model call") is amended by R4–R6:
the no-model-call guarantee holds for off-topic questions and for weak first turns; partial/fuzzy/glossary evidence,
overview findings and conversation history count as evidence. `docs/` is not edited; this document is the record.
Related prose: `README.md` (steps 5, 8, 9, configuration and CLI tables), `REPORT.md` § "Guardrail vs. graph
channel", `../TECHNICAL-REPORT.md` § 6.6/6.7, `../3-modules-plan.md` § "Guardrail" (superseded).

## 8. Risks

Rule 3 is softer: a borderline question may be answered from loosely related context instead of refused — every
answer carries sources, and the off-topic stop keeps the no-model-call guarantee. Fuzzy matching (R1) can misread
short or common words — minimum length, threshold, stopwords, identifiers excluded, interpretation shown. Ontology
cues contain generic words — `vocabulary.ignore`. Overviews are long — caps, compact-table instruction, visible
truncation; reasoning models still spend part of `max_tokens` thinking.
