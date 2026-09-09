# chat-system report — Streamlit chat over the indexed manuals, built and verified 2026-09-04

What was asked (`3-modules-plan.md`, module 3): the Streamlit chat UI over `retrieval/` and `users/` with a
conversation database (SQLAlchemy/Alembic; SQLite default, Postgres compose profile), streaming answers, citations with
every answer, fast/slow toggle, diagnostics on demand, a headless `chat-ask` CLI, README + DEPLOY + Makefile +
Dockerfile + compose; unit tests green, integration tests green against the live cluster + LiteLLM, `streamlit run`
answers the test questions with citations.

Stack during verification: OpenSearch 3.8.0 on `:9200` with CaaS `BHB-PLT-0001` and ZSD `BHB-PLT-0007` indexed,
bge-m3 embeddings and `gemini-dev` (gemini-3.7-flash) through LiteLLM on `:4000`, Streamlit 1.63.0, SQLAlchemy
2.0.52, Alembic 1.19.1, psycopg 3.3.5, Postgres 16 (`postgres:16-alpine`) in compose, Docker on WSL2.

## What was built

```
chat-system/
  pyproject.toml   chat-system 0.1.0; scripts chat-ask / chat-db / chat-doctor; deps streamlit, sqlalchemy, alembic, psycopg[binary], …
  requirements.txt -e ../opensearch-index -e ../users -e ../retrieval -e .[dev]
  config.yaml      CHAT__ defaults (db, retrieval k/k_graph/rewrite turns, limits, ui)      .env.example  DEV BOX + REMOTE blocks
  app.py           streamlit entry (calls chat_system.ui.app.main)                             .streamlit/config.toml
  Makefile         venv dev lint test test-ui test-integration doctor db-init/upgrade/revision/current run ask smoke
                   db-up db-down up down image-build up-enterprise logs health
  Dockerfile       context = repository root; layer 1 = union of the four pyproject dependency lists (tomllib), layer 2 = the
                   four packages --no-deps; uid 10001; RAG_CONFIG/OSI_CONFIG point at the copied config.yaml files
  compose.yaml     chat (profile local, host networking, SQLite in volume) · chat-enterprise (published port, Postgres) · postgres
  src/chat_system/ settings.py db.py models.py repository.py service.py catalog.py wiring.py cli.py
                   migrations/ (env.py, script.py.mako, versions/0001_initial.py — inside the package)
                   ui/ app.py auth.py sidebar.py chat.py
  scripts/         smoke.sh + smoke_questions.txt, wait_db.sh
  tests/unit/      conftest (fakes) + 11 test files, 59 tests (54 + 5 AppTest; 49 + 4 at the original verification)
                                                                                 tests/integration/  8 live tests
```

1,708 lines of source, 2,876 with tests and migrations. Root `.dockerignore` added (the image builds from the root).

## Verification

| Check | Result |
|---|---|
| `make lint` | clean (ruff, same rules as the other modules) |
| `make test` | **49 passed** (in-memory SQLite with the Alembic schema, fake retriever/LLM, mock users) — 54 after the 2026-09-09 update below |
| `CHAT_TEST_DB_URL=postgresql+psycopg://… make test` | **49 passed against Postgres 16** — found and fixed one portability bug (below) |
| `make test-ui` | **4 passed** — AppTest over the real `app.py` with a fake-backed service: answer + `Quellen (n)` expander + metric 0/10 → 1/10, turn cap disables the input, guardrail note, user switch → rita.read 0/5 — 5 after the update (picking a past conversation) |
| `make test-integration` | **8 passed** in 46 s — headless: 3 smoke questions answered with citations in the two books, follow-up rewritten and both forms stored, off-topic → guardrail without a model call, read-only user gets ZSD-only citations; UI: the real `app.py` over the real wiring answers with sources and diagnostics, rita.read sees one manual in the multiselect and ZSD-only sources |
| `make doctor` | db at revision 0001 · 2 manuals (bge-m3) · llm gemini-dev ok · budget k=12 → ~7,644 prompt tokens < 32,000 · users env → dev |
| `make smoke` | 6/6 through `chat-ask` (table below) |
| `make db-up` + `chat-db upgrade/current` on Postgres | schema created, `current=0001 head=0001 ok`; a two-turn conversation via `chat-ask --conversation` stored with `question_rewritten` ("Wer vertritt Marcel Ebert …"), `usage.count = 2`, `timestamptz` in UTC |
| `docker compose --profile local build` | image `chat-system:local`, 952 MB (python:3.12-slim + streamlit/pyarrow/pandas) |
| `make up` → `make health` → `exec chat chat-doctor` → `exec chat chat-ask …` | healthy after 2 s; doctor ok from inside (OpenSearch and LiteLLM on the host loopback, ontology mounted, `RAG_CONFIG` resolved); a real question answered from inside the container, SQLite created in the `chat-data` volume as uid `chat` |
| `make run` | Streamlit boots headless on 127.0.0.1, `/_stcore/health` ok after 2 s |

### Smoke questions through `chat-ask` (gemini-dev, defaults: k 8 fast / 12 graph)

| # | user | mode | question | result |
|---|---|---|---|---|
| 1 | otto.ops | fast | Auf welchen Servern läuft ZSD? | 7.1 s; IAM/PKI VMs, Vault in the CaaS namespace, ports from Tabelle 5 — cites ZSD S. 8–10 |
| 2 | otto.ops | graph | Was war bei ZSDSUP-0247? | 5.3 s; incident, partner tickets CAASUP-0351/DDSUP-1201, both durations (38/48 min) explained — ZSD S. 22–23, CaaS S. 21, 23 |
| 3 | otto.ops | graph | Was passiert, wenn Vault versiegelt ist? | 3.7 s; per consumer incl. **"VPP: nicht betroffen, da Keystores und Wallet lokal"** with sources [CaaS S. 12; ZSD S. 19]; unseal per SOP-ZSD-05 |
| 4 | otto.ops | graph | Wer ist für IAM/Keycloak zuständig und wie eskaliere ich? | 4.3 s; Kai Ostermann (1315), three escalation levels — ZSD S. 1–2, 26 |
| 5 | otto.ops | graph | Wie backe ich einen Apfelkuchen? | 0.2 s; **guardrail**: "Dazu steht nichts in den Handbüchern.", `llm_called=False`, counted as a message, no citations (after the fix below) |
| 6 | rita.read | graph | Was war bei ZSDSUP-0247? | 4.3 s; same incident from the ZSD book only — all 16 citations `BHB-PLT-0007`, the partner ticket named but CaaS never cited |

Latency is dominated by the model (retrieval 0.2–0.4 s incl. the embedding call, as in `retrieval/REPORT.md`); the
rewrite adds one short model call (~1–2 s with gemini-dev) from the second turn on.

## Decisions and deltas to the plan

1. **Migrations live inside the package** (`src/chat_system/migrations/`), not in a top-level `migrations/` folder:
   `pip install --no-deps .` in the image copies only the package, and `chat-db`/`ensure_schema` find the scripts via
   `Path(__file__)`. `alembic.ini` points there for the bare `alembic` command. `ensure_schema(engine)` runs
   `upgrade head` over the engine's own connection (Alembic's shared-connection recipe), so in-memory SQLite in tests
   gets the same schema as production.
2. **`TurnStream` persists exactly once**, whichever way it ends: `stop`, `length` (since 2026-09-09), `guardrail`, `aborted` (generator closed by
   `st.write_stream` — partial text kept, usage counted), `error` (model failed — German error text stored, usage
   refunded). A failure *before* streaming (retrieval, prompt too large) also stores an error row and refunds, and
   the user's question is kept. The semaphore is released exactly once via the same path.
3. **Citations are stored enriched** (`enrich_citations`): breadcrumb/caption, channels and a 240-char snippet from
   the source group, the rendered facts for edge citations — so a replayed conversation shows the same `Quellen`
   panel as the live turn without re-running retrieval.
4. **Guardrail turns cite nothing** — found by the smoke run: the retrieval result of a weak question still carries
   the kNN chunks (kNN always returns k) and the CLI printed nine "sources" under "Dazu steht nichts in den
   Handbüchern." The fake retriever now reproduces that shape and the unit test asserts `citations == []`.
5. **Postgres portability bug found by running the suite on Postgres:** the usage upsert used `max(count + by, 0)`
   — a scalar on SQLite, an aggregate on Postgres (`function max(integer, integer) does not exist`). Replaced by a
   `CASE`; the same 49 tests pass on both. Everything else (JSON→JSONB variant, `TZDateTime`, uuid ids, unique seq)
   ran unchanged on Postgres.
6. **UI state handling**: widgets are keyed (`use_graph`, `doc_ids_pick`, `show_diagnostics`, `conversation_pick`)
   and initialised in `session_state` before creation, so resuming a conversation can set the toggle/filter from
   the stored conversation without Streamlit's "default value + session state" warning; a user switch resets the
   conversation state; `st.rerun()` after a turn refreshes quota, title and list without re-streaming.
7. **`chat-doctor`** adds the `budget` check from the plan (`k × 512 + 1500` vs `RAG__LLM__CONTEXT_LIMIT_TOKENS`) and
   warns when the user switch is enabled together with the header adapter.
8. **Numbering**: the root README counts retrieval = module 3, users = module 4, so this is "module 5" (the plan text
   said 4).
9. Not done: no Postgres run of the *integration* suite (SQLite tmp file there; the repository/service tests cover
   the dialect); no browser-driven test (AppTest drives the real script instead); no oauth2-proxy in front.

## Contract points for whoever touches this next

- One `.env` in `chat-system/` with `CHAT__*`, `RAG__*`, `USERS__*`; the model is `RAG__LLM__MODEL` only.
- `wiring.build_service(settings)` is the only place the real neighbours are constructed; everything else takes the
  service. Tests replace `chat_system.ui.app.SERVICE_FACTORY` and clear `get_service`.
- `Repository.begin_turn` is the reservation; `UsageRepo.increment(by=-1)` the refund; `UsageRepo` satisfies
  `rag_users.UsageStore` (checked with `isinstance` at runtime).
- `TurnStream` is the object the UI and the CLI share: `tokens()`, `abort()`, `collect()`, `to_result()`, plus
  `citations`/`facts`/`diagnostics`/`result`/`guardrail`/`question_rewritten` readable before streaming.
- Diagnostics JSON keys the UI renders: `mode, model, llm_called, weak_evidence(_reason), weak_follow_up, finish_reason,
  rewritten_question, doc_ids, identifiers, resolved_labels, partial_labels, channels[],
  timings_ms{rewrite,retrieve,first_token,stream,total}, prompt_chars, facts[], entities[], warnings[], error`.

## Update 2026-09-09 — REQ-001 phase 1 and two fixes

Recorded in [`requirements/REQ-001-robust-question-understanding.md`](requirements/REQ-001-robust-question-understanding.md)
(chat side) and its retrieval counterpart. What changed in this module:

- **Follow-up rule** (`service.ask` step 6): a weak retrieval verdict refuses only on a first turn; with history the
  model is called with the conversation and the retrieval module's weak note instead of the context. Such turns cite
  nothing (`TurnStream.citations == []`), carry `weak_follow_up=True` and finish as `stop`. Live: "Mach ein Script mit
  diesen Befehlen" after the Vault-unseal answer yields a bash script of the SOP-ZSD-05 commands.
- **Truncation persisted** (`TurnStream.tokens`): `finish_reason` is read from the stream after the iteration
  (duck-typed; `rag_retrieval.TokenStream` provides it) and a cut answer is stored as `length`; the UI caption and
  the `chat-ask` summary line show it. Live with `RAG__LLM__MAX_TOKENS=200`: `[length · … · Antwort gekürzt (max_tokens)]`.
- **Status line** (`ui/chat.status_label`): "Keine belastbaren Treffer · schwache Evidenz · Modell nicht aufgerufen",
  "Keine neuen Treffer · Antwort aus dem Gesprächsverlauf", or the counts with the mode in words; Diagnostik shows
  `Folgefrage ohne neue Evidenz` and `Antwort gekürzt`. Tested as a pure function (`test_ui_labels.py`): the
  `st.status` element does not survive the rerun that follows a turn, so AppTest cannot see its final label.
- **History window and manual filter in the prompt**: `ask()` passes `max_history_turns` from
  `RAG__RETRIEVAL__HISTORY_TURNS` and `doc_ids=effective_doc_ids`, so the prompt starts with `Handbuch-Filter: …` for
  a sidebar pick or a read-only group and the model does not ask which manual.
- **Sidebar fix**: picking a past conversation did nothing — the "keep the widget in step" sync overwrote the pick
  with the current conversation before the selectbox rendered. The pick is now loaded in the selectbox `on_change`
  callback; the sync only handles programmatic changes (`test_picking_a_past_conversation_loads_it`).

Verification after the update: `make lint` clean, `make test` **54 passed**, `make test-ui` **5 passed**, `make smoke`
6 questions ok (the guardrail question still refused without a model call), live `chat-ask` follow-up and truncation
checks as above. Server note: `RAG__GUARDRAIL__MIN_AGREEING_CHANNELS=1` there (e5 embeddings plus a book filter made
the two-channel agreement rule refuse "Wer ist verantwortlich?"); settings are read once per process, so a `.env`
change needs a full restart of `make run`, not a reinstall.
