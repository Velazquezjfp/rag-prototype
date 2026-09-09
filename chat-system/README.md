# chat-system — module 5: chat over the indexed manuals

The Streamlit chat of the RAG prototype: a German question about the operations manuals goes through `rag_users`
(who is asking, what may they do), `rag_retrieval` (hybrid OpenSearch search + graph expansion + German prompt) and
the configured OpenAI-compatible model, and comes back streamed with citations on every answer. Conversations,
messages and the per-user daily usage live in a database (SQLite by default, Postgres via a compose profile,
ADR-0007); the backend (`ChatService`) never imports Streamlit, so the same turn runs headless through `chat-ask`.

Verified 2026-09-04 on the dev box (OpenSearch 3.8.0 with CaaS `BHB-PLT-0001` and ZSD `BHB-PLT-0007` indexed,
bge-m3 embeddings and `gemini-dev` through LiteLLM): 49 unit tests (also green against Postgres 16), 4 Streamlit
AppTest smokes, 8 live integration tests (6 headless, 2 driving the real `app.py`), the 6 smoke questions through
`chat-ask` including the guardrail question and the read-only user; the container image builds from the repository
root and answers a question from inside the container. Details and the answers: [`REPORT.md`](REPORT.md).

Updated 2026-09-09 ([`requirements/REQ-001`](requirements/REQ-001-robust-question-understanding.md), phase 1):
weak follow-ups are answered from the conversation instead of refused, a stream cut by `max_tokens` is stored and
shown as `length`, the search status line says what was used, the active manual filter is named in the prompt so
the model does not ask which manual, the history window is `RAG__RETRIEVAL__HISTORY_TURNS`, and picking a past
conversation in the sidebar loads it again (regression fix). Now 54 unit tests and 5 AppTest smokes.

## How a question is answered

```
sidebar user ─► AuthContext ─► Policy.check_message ─► reserve usage + store question ─► rewrite (history) ─►
   Retriever.retrieve(k, doc_ids) ─► weak_evidence? ─► first turn: "Dazu steht nichts in den Handbüchern." (no model call)
                                                     │  follow-up:  model with history + WEAK_FOLLOW_UP_NOTE_DE, nothing cited
                                                     └► build_messages ─► ChatClient.stream ─► persist answer + citations + diagnostics
```

1. **Identity** (`ui/auth.py`): with `CHAT__UI__ALLOW_USER_SWITCH=true` and the `env` adapter the sidebar offers the
   four mock users (the "simulated ingress" of ADR-0008); otherwise `rag_users.get_adapter(..., headers=st.context.headers)`
   reads the oauth2-proxy headers. `Unauthenticated` → `st.error` + `st.stop()`.
2. **Policy** (`service.ask`, phase 1): one `Policy.check_message` call decides `forbidden` (only unreadable manuals
   requested), `daily_cap`, `turn_cap` — refused turns persist nothing and count nothing. The effective manual filter
   (`Decision.doc_ids`) is what retrieval gets.
3. **Concurrency**: an in-process `BoundedSemaphore(CHAT__LIMITS__MAX_CONCURRENT_ANSWERS)`; above it the turn is
   refused as `busy` (SPEC: 10 concurrent users).
4. **Reservation**: `Repository.begin_turn` increments `usage(user_id, day)` and stores the user message in one
   transaction — the cap lives in the backend and survives a second browser tab (SPEC §10.2).
5. **Rewrite** (SPEC §8): from the second turn on, `rag_retrieval.rewrite_question` turns the follow-up into a
   standalone question from the last `CHAT__RETRIEVAL__HISTORY_TURNS_FOR_REWRITE` turns; both forms are stored
   (ADR-0011: `question_rewritten` on the assistant row).
6. **Retrieve**: `Retriever.retrieve(rewritten, use_graph, k = K_GRAPH|K, doc_ids)`.
7. **Guardrail** ([`requirements/REQ-001`](requirements/REQ-001-robust-question-understanding.md)): `weak_evidence`
   on a **first turn** → the canned sentence is streamed, `guardrail=True`, `llm_called=False`, the model is not
   called. `weak_evidence` on a **follow-up** → the model is called with the history and the weak note instead of
   the context (`weak_follow_up=True`, nothing cited). Otherwise `build_messages(result, raw question, history)`
   with the retrieval module's budget, the model's context limit and the `RAG__RETRIEVAL__HISTORY_TURNS` window.
8. **Stream + persist**: `TurnStream.tokens()` streams the model deltas (`st.write_stream` in the UI, stdout in the
   CLI) and persists the assistant row exactly once — `finish_reason` `stop`, `length` (cut by `max_tokens`: text
   kept, the UI says "Antwort vom Modell gekürzt"), `guardrail`, `aborted` (the consumer stopped: partial text
   kept) or `error` (model failed: German error text stored, usage refunded). The status line of the search names
   what was used ("… (Graph)", "Keine belastbaren Treffer · … · Modell nicht aufgerufen", "Keine neuen Treffer ·
   Antwort aus dem Gesprächsverlauf"). Citations are
   stored enriched (breadcrumb, channels, snippet), diagnostics as JSON (`rag_retrieval.Diagnostics` + rewrite,
   filter, model, timings, facts, entities, prompt size). The 10th turn marks the conversation `capped`.

## Quick start (dev box)

```bash
cd chat-system
cp .env.example .env        # DEV BOX block active: SQLite, user switch on, OpenSearch :9200, LiteLLM :4000 (bge-m3, gemini-dev)
make dev                    # .venv with opensearch-index, users, retrieval (siblings, editable) + this package
make doctor                 # DB + schema, indexed manuals, LLM probe, resolved user, prompt budget vs context limit
make db-init                # alembic upgrade head on CHAT__DB__URL (also done automatically at startup, db.auto_upgrade)
make ask Q="Auf welchen Servern läuft ZSD?" ARGS="--no-graph"
make ask Q="Was passiert, wenn Vault versiegelt ist?" ARGS="--user otto.ops"
make ask Q="Was war bei ZSDSUP-0247?" ARGS="--user rita.read"      # read-only group: ZSD sources only
make ask Q="Wie backe ich einen Apfelkuchen?"                          # guardrail: canned answer, no model call
make run                    # http://127.0.0.1:8501
make test && make test-ui && make test-integration
make smoke                  # scripts/smoke_questions.txt through chat-ask -> out/smoke/
```

In the UI: pick a user in the sidebar, ask; open **Quellen (n)** under an answer for document, pages, breadcrumb,
channels and a snippet per source; tick **Diagnostik anzeigen** for mode, rewritten question, channel table,
timings, facts (negatives in red) and entities; toggle **Graph-Modus (langsam)**; restrict **Handbücher**; resume an
earlier conversation from the **Gespräche** list; **Neues Gespräch** starts over. A capped conversation shows the
notice and a disabled input.

## Users and limits (mock)

From `rag_users` (see [`../users/README.md`](../users/README.md)): `dev`/`otto.ops` (bavd-ops: 10 messages/day, 10
turns, all manuals), `rita.read` (bavd-readonly: 5/5, ZSD only), `anna.admin` (admin: 100/20, all). The sidebar
metric **Nachrichten heute** shows `used/cap`; refusals appear as warnings with the German reason. The daily counter
is per calendar day in UTC (`usage.day`).

## Configuration (`CHAT__SECTION__KEY`)

`config.yaml` here holds the defaults; `CHAT_CONFIG=<file>` selects another one, `./config.yaml` of the working
directory is consulted too (the osi chain). Environment and `.env` override per key. One `.env`, three prefixes:
`CHAT__*` (this table), `RAG__*` (OpenSearch, embeddings **and the model** — the LLM is configured once, there),
`USERS__*` (adapter, dev user, header names).

| Section | Keys (defaults) | Notes |
|---|---|---|
| `db` | `url` `sqlite:///./data/chat.db`, `echo` false, `auto_upgrade` true | Postgres: `postgresql+psycopg://chat:<pw>@127.0.0.1:5432/chat` (`make db-up`) |
| `retrieval` | `k` 8, `k_graph` 12, `history_turns_for_rewrite` 2, `use_graph_default` true | how the chat calls retrieval; retrieval internals stay in `RAG__RETRIEVAL__*` |
| `limits` | `max_concurrent_answers` 10 | in-process semaphore; per-user caps come from `rag_users.Policy` |
| `ui` | `title` Betriebshandbuch-Assistent, `allow_user_switch` false (true in the dev `.env`), `show_diagnostics_default` false, `conversation_list_limit` 20 | the user switch is only offered with `USERS__ADAPTER=env` |

Small Ollama models: `RAG__LLM__CONTEXT_LIMIT_TOKENS=4096`, `RAG__RETRIEVAL__CONTEXT_TOKEN_BUDGET=2500`,
`CHAT__RETRIEVAL__K=4`, `CHAT__RETRIEVAL__K_GRAPH=6` — `chat-doctor` warns when `k × 512 + 1500` exceeds the context limit.

Large served context (server): `RAG__RETRIEVAL__HISTORY_TURNS=10`. When kNN and BM25 rarely agree on the top hits
(e5 embeddings plus a book filter refused "Wer ist verantwortlich?"): `RAG__GUARDRAIL__MIN_AGREEING_CHANNELS=1` — off-topic
questions stay refused via the BM25 stop (REQ-001, until phases 2–4 add evidence sources).

## CLI

| Command | What it does |
|---|---|
| `chat-ask "Frage" [--graph/--no-graph] [--user dev] [--conversation ID] [--doc-id X …] [--json]` | one turn through the real service: streams the answer, then `Quellen:` and the remaining quota; `--conversation` continues (and rewrites); exit 2 on a refusal, 1 on an unknown user |
| `chat-db upgrade [rev]` · `chat-db revision -m "…"` · `chat-db current` | Alembic on `CHAT__DB__URL` (migrations ship inside the package); `current` exits 1 when an upgrade is needed |
| `chat-doctor [--json]` | DB reachable + revision vs head, indexed manuals via `bhb-documents`, LLM `/models` probe, resolved user + limits, prompt budget warning; exit 1 on a failure |

## Database

```
conversations  id uuid4 (app) · user_id (index) · title (first question, ≤ 80 chars) · use_graph_default · doc_ids JSON
               turn_count · status open|capped · created_at/updated_at (UTC, tz-aware on both dialects)
messages       id · conversation_id (FK, cascade) · seq (unique per conversation) · role user|assistant · content
               question_rewritten · use_graph · citations JSON · diagnostics JSON · guardrail · finish_reason · model · latency_ms · created_at
usage          (user_id, day) PK · count · updated_at                       -- SPEC §10.2 usage(user_id, day, count)
```

SQLite runs with WAL, `busy_timeout` 5 s and foreign keys on; JSON columns are JSONB on Postgres; the usage upsert is
UPDATE → INSERT → UPDATE-on-conflict (portable, no dialect-specific `ON CONFLICT`). `make db-up` starts Postgres 16
in compose; the unit tests re-run against it with `CHAT_TEST_DB_URL=postgresql+psycopg://chat:chat@127.0.0.1:5432/chat`.

## Tests

```bash
make test               # 54 unit tests, no services: in-memory SQLite with the Alembic schema, FakeRetriever (canned
                        # RetrievalResults incl. weak_evidence), FakeLLM (tokens / rewrite / failures), the mock users,
                        # the status line as a pure function (test_ui_labels.py)
make test-ui            # 5 Streamlit AppTest smokes over app.py with a fake-backed service (answer + Quellen, cap, guardrail,
                        # user switch, picking a past conversation)
make test-integration   # 8 live tests: 3 smoke questions + rewrite + guardrail + read-only filter headless, 2 driving the real app.py
CHAT_TEST_DB_URL=postgresql+psycopg://chat:chat@127.0.0.1:5432/chat make test     # the same unit tests on Postgres
```

`tests/unit/test_no_ui_imports.py` fails if any backend module imports streamlit.

## Deployment

`make up` runs the UI as a container with host networking (dev box or a server with SSH tunnels), `make up-enterprise`
publishes a port and uses the compose Postgres. The image is built from the repository root (the four module folders
go in; root `.dockerignore` keeps venvs, data, `.env`, tests and the corpus out). Remote steps, rootless podman and
SELinux notes: [`DEPLOY.md`](DEPLOY.md).

## Limitations and next steps

- Mock identity (four users in code). Real auth = oauth2-proxy in front + `USERS__ADAPTER=header` (ADR-0008); the
  sidebar switch is then never shown.
- The daily-cap reservation is read-then-increment: two tabs sending at exactly the same instant on the last allowed
  message can both pass. A conditional `UPDATE … WHERE count < cap` would close that; not needed for the prototype.
- The concurrency semaphore is per process (`replicas: 1` in compose). Several replicas need a shared counter.
- No compaction (ADR-0011): the turn cap bounds a conversation; history in the prompt is the last 3 pairs
  (`build_messages`), the rewrite sees the last 2.
- All citations of a retrieval are stored and shown (one per document/pages plus one per fact — up to ~16 for a
  graph-mode answer); marking the ones the model actually referenced in its text is an easy next step.
- Streamlit 1.63.0 (`streamlit>=1.50,<2`); `st.context.headers` (1.37+) is what the header adapter reads.
