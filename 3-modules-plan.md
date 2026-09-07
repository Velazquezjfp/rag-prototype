# Plan: retrieval + chat-system + users modules (Phase 3 of the RAG prototype)

## Status (2026-09-04)

- **Module 1 `retrieval/` — DONE and verified** (`retrieval/README.md`, `retrieval/REPORT.md`; 104 unit + 13 live
  integration tests). Deltas to the plan below that chat-system must know: `RetrievalSettings` gained
  `graph_seed_per_channel` (2), `graph_min_sources` (2), `partial_label_min_tokens` (2), `partial_label_max_nodes` (8),
  `graph_max_start_nodes` is 30; `LLMSettings.max_tokens` default is **4000** (gemini-3.7-flash spends ~1300 reasoning
  tokens first — 1500 truncated answers); `ChatClient.complete_full()` returns `Completion(text, finish_reason, usage)`;
  `build_messages(..., max_history_turns=3)` counts user/assistant *pairs*; `Diagnostics.partial_labels` added;
  `estimate_tokens` = len/2.6. Guardrail counts search channels only and the graph expansion is skipped when weak.
  Fake clients for tests live in `retrieval/tests/unit/fake_search_client.py` (`FakeSearchClient`, `FakeEmbedder`,
  `FakeLLM`) — reuse them in chat-system's unit tests.
- **Module 2 `users/` — DONE and verified** (`users/README.md`, `users/REPORT.md`; 39 unit tests, ruff clean; the
  read-only filter was pushed through the live retriever: ZSD-only chunks/facts/citations, `forbidden` never reaches
  retrieval). Deltas to the plan below that chat-system must know: `Policy.check_message(ctx, usage, *, today,
  turns_in_conversation, requested_doc_ids=None)` also decides `"forbidden"` and returns `Decision.doc_ids`
  (`None` = all, `()` iff forbidden) — one call per turn; check order forbidden → daily_cap → turn_cap;
  `remaining_today` = cap − used *before* the checked message; unknown groups grant nothing (only-unknown →
  `DEFAULT_LIMITS`); `Decision.message_de` / `REASON_TEXT_DE` carry the German refusal wording; `MemoryUsageStore`
  for tests; `python -m rag_users [--json]` prints directory/rules/current user (for `chat-doctor`);
  `get_adapter(settings=None, headers=None)`. `AuthContext.email` defaults to "" (header adapter without e-mail).
- **Module 3 `chat-system/` — DONE and verified** (`chat-system/README.md`, `DEPLOY.md`, `REPORT.md`; 49 unit tests
  green on SQLite AND Postgres 16, 4 AppTest smokes, 8 live integration tests incl. 2 that drive the real `app.py`,
  6 smoke questions via `chat-ask`, image `chat-system:local` built from the repo root and answering from inside the
  container). Deltas: migrations live in `src/chat_system/migrations/` (needed for the --no-deps image install);
  `Repository.begin_turn` = reservation + user message in one transaction; `TurnStream` persists once with
  finish_reason stop|guardrail|aborted|error (error refunds usage); citations stored enriched (breadcrumb, channels,
  snippet); guardrail turns store/show no citations; usage upsert uses CASE (max(a,b) is an aggregate on Postgres);
  root README numbering: this is module 5. Phase 3 is complete; remaining ideas are in the READMEs' limitations.

## Context

Modules 1 (`docling-graph/`) and 2 (`opensearch-index/`) plus `integration/` are done. Two manuals are indexed
locally (CaaS `BHB-PLT-0001`, ZSD `BHB-PLT-0007`: 232 chunks, 460 node records, 60 shared node ids). Nothing
yet turns a question into an answer: `osi search` can only kNN from a *stored* vector, `search.py` returns a narrow
field set (no `text`/`body_text`/`node_ids`/`edge_ids`), there is no query-side embedding client, no graph
expansion, no prompt builder, no UI.

The user wants, in this session, three new sibling modules built and tested end to end:

1. **`retrieval/`** (user's "result management"): question → hybrid OpenSearch search + 1-hop graph expansion →
   deduped, provenance-carrying result → German prompt injection; plus the OpenAI-compatible chat client with
   streaming, query rewriting and the "dazu steht nichts in den Handbüchern" guardrail. Pure library + CLI.
2. **`chat-system/`**: Streamlit chat UI over `retrieval`, conversation DB (SQLAlchemy; SQLite default,
   Postgres compose profile), streaming answers, citations with every answer, fast/slow toggle, diagnostics on
   demand, headless `chat-ask` CLI, README + DEPLOY + Makefile + Dockerfile + compose.
3. **`users/`**: mock auth/policy module shaped like SPEC §10.2's seam (`AuthContext{user_id, email, groups}`,
   one adapter, two implementations), hardcoded users, daily message cap per group, allowed books per group
   (flagged as an addition beyond the SPEC).

Graph visualisation, real auth, the merge module, eval, and intent routing stay out of scope. Done means: unit
tests green in all three modules, integration tests green against the live cluster + LiteLLM, `streamlit run`
answers test questions about the two books with citations, and a short retrieval report records how the 8
ground-truth questions fared.

**User decisions (2026-09-04):** SQLite default + Postgres profile · test LLM `gemini-dev` via LiteLLM :4000 ·
folder `retrieval/` (package `rag_retrieval`) · users mock enforces daily cap + per-group book access.

## Verified environment (design against this)

| Thing | Value |
|---|---|
| Python / tooling | 3.12.3, pip + PEP-621 hatchling, **no uv**; ruff line 100 py312; `from __future__ import annotations` |
| OpenSearch | `http://localhost:9200`, no auth, 3.8.0; aliases `bhb-chunks/-nodes/-documents/-manifest`, pipeline `bhb-rrf` |
| Embeddings | `bge-m3` (1024, **no prefix**) via LiteLLM `http://localhost:4000/v1`, key `sk-123456789`; server = e5-large with `passage:`/`query:` |
| Chat LLM | LiteLLM `gemini-dev` (default), `granite4`; Ollama direct `http://localhost:11434/v1` (`gemma4:e2b`) |
| Streamlit | not installed anywhere → new venv `chat-system/.venv` |
| Containers | Docker locally; remote = rootless podman behind `docker` alias, SELinux, no `--wait`, `depends_on` list form |
| Fixtures | `out/remote-zsd/{response,graph}.json`, `out/remote-caas/…`, `opensearch-index/tests/data/response_small.json` |
| Settings pattern | copy `opensearch-index/src/opensearch_index/settings.py` (env prefix + `__` + `.env` + `config.yaml`) |

Live-data facts that shape the design (verified by the design agent against the cluster and fixtures):
- `terms` on `node_labels` applies the `lc` normalizer (lowercase only); `norm_key()` casefolds ß→ss. Match
  question n-grams with `norm_key`, but send `label.lower()` to OpenSearch.
- Chunk `_id == chunk_id` → neighbour chunks via `mget`. `token_count` (≤512) is stored → prompt budgeting
  without tiktoken.
- One chunk can carry 25+ `node_ids` → start-node expansion must be capped.
- "VPP is unaffected by Vault" is **not** a negative edge; it lives in `ImpactStatement` nodes with
  `attributes.severity == "keine"` (degree 0). Graph context must therefore include **entity cards** (node
  attributes), not only edges. Real negative edges: ZSD `Vault —DEPENDS_ON→ PKI/Keycloak` (qualifier "für
  Vault-Unseal", p. 19), `VPP —TENANT_OF→ CaaS-Plattform` (p. 19), CaaS `… —IMPACT_OF→ VPP` (p. 19).
- Same person under two node_ids ("Kai Ostermann" / "Ostermann" alias) → group by node_id, then by norm label.
- Fixture `graph.json` edges lack `id`; indexed blobs have it → compute missing via `opensearch_index.identity.edge_id`.
- Server-side `hybrid` + `bhb-rrf` loses per-clause attribution and cannot take the graph list → fuse client-side.

---

## Module 1: `retrieval/` — package `rag_retrieval`, CLI `rag-retrieve`

### Layout

```
retrieval/
  pyproject.toml        name "rag-retrieval", hatchling, >=3.12,<3.13, script rag-retrieve = "rag_retrieval.cli:app"
  requirements.txt      -e ../opensearch-index ; -e .[dev]     (integration/requirements.txt pattern)
  config.yaml           defaults (RAG_CONFIG > packaged default; ./config.yaml deliberately NOT consulted, see contract decisions)
  .env.example          DEV BOX block uncommented; REMOTE SERVER block commented (e5 query prefix, tunnels)
  Makefile              venv dev lint test test-integration ask graph-stats check
  README.md             what it does, quick start, API, config table, CLI table, retrieval report link, limitations
  REPORT.md             results of the 8 ground-truth questions (fast vs slow), written at the end
  src/rag_retrieval/
    __init__.py         re-exports: retrieve, Retriever, RetrievalResult, ChunkHit, GraphFact, EntityCard,
                        build_messages, render_context, rewrite_question, answer, ChatClient, Message, NO_EVIDENCE_ANSWER
    settings.py         RAG__ prefix; reuse opensearch_index.settings.OpenSearchSettings verbatim
    llm_http.py         copy of docling-graph llm_http.LLMClient + trust_env=False + post_sse() streaming
    embed.py            QuestionEmbedder(client, model, dim, query_prefix).embed(text) -> list[float]
    chat.py             ChatClient.complete()/stream()/probe(); rewrite_question(); answer(); NO_EVIDENCE_ANSWER
    models.py           pydantic result types (cross-module boundary) + Channel/Polarity literals
    graph.py            GraphStore: load blobs from bhb-documents, union by node_id, adjacency, label index, expand()
    query.py            analyze_question(): identifiers (ontology regexes) + label n-gram resolution -> QueryPlan
    search.py           channel query bodies + msearch/mget returning full _source minus embedding/bboxes
    fusion.py           rrf(), dedupe by chunk_id with channel union, group_hits() for table parts
    facts.py            edges -> GraphFact (German rendering, polarity, relation label_de), nodes -> EntityCard
    guardrail.py        decide() -> (weak_evidence, reason)
    prompt.py           SYSTEM_PROMPT_DE, render_context(), build_messages(), estimate_tokens()
    retriever.py        Retriever class + module-level retrieve()
    cli.py              typer: ask | graph-stats | entities | check
  tests/
    conftest.py         sys.path insert; fixtures: ontology, response_small, fake index via transform.build_batch,
                        GraphStore from out/remote-*/graph.json (skip if absent)
    unit/fake_search_client.py + test_*.py
    integration/test_live_retrieve.py   gated RAG_INTEGRATION=1 (RAG_INTEGRATION_URL default localhost:9200)
```

Deps: `opensearch-py>=3.2,<4`, `pydantic>=2.7`, `pydantic-settings>=2.4`, `pyyaml>=6`, `httpx>=0.27`,
`typer>=0.12`; dev `pytest`, `pytest-timeout`, `ruff`. `opensearch-index` comes from the editable install (not on
PyPI). **No** networkx (dict adjacency suffices for 1 hop), no tiktoken, no openai SDK, no docling-graph import.

### Settings (`RAG__SECTION__KEY`)

```python
opensearch: OpenSearchSettings                      # reused from opensearch_index.settings
index:      prefix="bhb"
embedding:  base_url="http://localhost:4000/v1", api_key="", model="bge-m3", dim=1024, query_prefix="", timeout_s=30, max_attempts=3
llm:        base_url="http://localhost:4000/v1", api_key="", model="gemini-dev", temperature=0.0, max_tokens=1500,
            timeout_s=120, max_attempts=2, context_limit_tokens=32000
retrieval:  k_per_channel=20, final_k=10, rrf_rank_constant=60, graph_seed_hits=5, graph_max_start_nodes=25,
            graph_max_facts=40, graph_max_chunks=15, graph_max_entities=15, label_max_ngram=4, label_min_chars=3,
            context_token_budget=6000, max_facts_in_prompt=25
guardrail:  enabled=True, min_agreeing_channels=2, top_n=3
ontology:   path="../user-manual-books/handbuch_daten/Ontologie/ontology.yaml"
```
Dev `.env`: `RAG__EMBEDDING__API_KEY=sk-123456789`, `RAG__LLM__API_KEY=sk-123456789`. Server block:
`RAG__EMBEDDING__MODEL=intfloat/multilingual-e5-large`, `RAG__EMBEDDING__QUERY_PREFIX="query: "`, tunnels.

### Public API (exact)

```python
# models.py (pydantic)
Channel = Literal["knn", "bm25", "identifier", "label", "graph"]; Polarity = Literal["positive","negative","unknown"]
class ChannelEvidence: channel, rank, score|None, via|None      # via = matched identifier / label / "DEPENDS_ON from Vault"
class ChunkHit: chunk_id, doc_id, doc_title, kind, page_numbers, heading_breadcrumb, caption, body_text, text,
                token_count, identifiers, node_ids, node_labels, edge_ids, rank, fused_score, channels, group_key
                @property cite -> "BHB-PLT-0007 S. 19" / "S. 8–9"
class ChunkGroup: key, doc_id, doc_title, kind, caption, heading_breadcrumb, pages, chunk_ids, parts, rank, fused_score
class GraphFact: edge_id, doc_ids, source_id/label/type, relation, relation_de, target_id/label/type, polarity,
                 qualifier, quote, properties, pages, chunk_ids, via_start_node, rendered
class EntityOccurrence: doc_id, label, attributes, pages, chunk_ids, quote
class EntityCard: node_ids, type, label, aliases, occurrences, matched_by: Literal["label","identifier","hit"], rendered
class Citation: key, doc_id, doc_title, pages, chunk_ids, edge_ids
class ChannelStats: channel, requested_k, returned, took_ms, query_terms
class Diagnostics: question, rewritten_question, mode, identifiers, label_candidates, resolved_labels, start_nodes,
                   channels, timings_ms, embedding_model, indexed_embedding_models, indexed_text_prefix, warnings
class RetrievalResult: question, mode: Literal["fast","slow"], chunks, groups, facts, entities, citations,
                       weak_evidence: bool, weak_evidence_reason: str|None, diagnostics
class Message: role: Literal["system","user","assistant"], content
class RenderedContext: text, token_estimate, included_chunk_ids, included_edge_ids, dropped_chunk_ids
class RewriteResult: original, rewritten, used_llm, error|None

# retriever.py
class Retriever:
    def __init__(self, settings: Settings, *, client=None, embedder=None, graph=None, ontology=None)
    def retrieve(self, question: str, *, use_graph: bool = True, k: int | None = None,
                 doc_ids: list[str] | None = None) -> RetrievalResult
    def reload_graph(self) -> GraphStats          # swaps GraphStore under a lock (ADR-0005 reload)
    def check(self) -> dict[str, Any]             # aliases, embedding probe+dim, model/prefix mismatch, LLM probe
def retrieve(question, *, use_graph=True, k=None, doc_ids=None, retriever=None) -> RetrievalResult   # lru-cached default Retriever

# prompt.py
SYSTEM_PROMPT_DE: str
def render_context(result, *, token_budget=None, max_facts=None) -> RenderedContext
def build_messages(result, question, history: list[Message] | None = None, *, system_prompt=None,
                   token_budget=None, max_history_turns=6) -> list[dict[str, str]]     # ValueError above context_limit_tokens
def estimate_tokens(text) -> int                  # len // 3 (conservative for German)

# chat.py
class ChatClient:
    def __init__(self, settings: LLMSettings, *, transport: httpx.BaseTransport | None = None)
    def complete(self, messages, *, model=None, max_tokens=None) -> str
    def stream(self, messages, *, model=None) -> Iterator[str]          # SSE deltas
    def probe(self) -> str
def rewrite_question(history: list[Message], question: str, llm: ChatClient, *, max_turns: int = 2) -> RewriteResult
NO_EVIDENCE_ANSWER = "Dazu steht nichts in den Handbüchern."
def answer(result, question, llm, history=None, *, stream=False, force=False) -> str | Iterator[str]
    # weak_evidence and not force -> NO_EVIDENCE_ANSWER, no model call (ADR-0011)
```
`rewrite_question` returns the question unchanged (`used_llm=False`) on empty history and falls back to the
original on any LLM error. The chat client lives here so the CLI answers end to end and chat-system only wraps.

### Retrieval algorithm (`Retriever.retrieve`)

1. **Analyze** (`query.analyze_question`): identifiers = `opensearch_index.transform.extract_identifiers(question,
   ontology.regexes)` plus the `host` regex over `question.lower()`. Labels: tokenize
   `[\w][\w\-./]*`, n-grams 1..4, `norm_key()` each, look up in `GraphStore.label_index` (norm_key of every label
   and alias); unigrams need ≥3 chars and not in a small German stop/question-word list; longest match wins.
   `label_terms` = original labels/aliases `.lower()`. No LLM, no OpenSearch call.
2. **Embed** the (rewritten) question with `query_prefix`; assert dim. Model/prefix mismatch vs
   `bhb-documents.embedding_model/embedding_text_prefix` → `Diagnostics.warnings` + log, never fail.
3. **Channels** in one `client.msearch` (all `_source.excludes = [embedding, bboxes]`, `size=k`):
   `knn` (`filter: terms doc_id` inside the knn clause when `doc_ids`), `bm25` multi_match `text^2, body_text,
   caption` (bool filter on doc_id), `identifier` = bool/should of `term identifiers` (only if any), `label` = same
   on `node_labels` (only if any). `via` computed client-side by intersecting hit fields with query terms.
4. **Fuse** (`fusion.rrf`, rank_constant 60): score = Σ 1/(60+rank); ties → more channels, best rank, chunk_id.
   Dedupe by chunk_id keeping the union of `ChannelEvidence`. Fast mode returns `final_k` here.
5. **Graph channel** (slow): start nodes = label-resolved node_ids ∪ node_ids of top `graph_seed_hits` fused
   chunks, capped at 25 with priority label-resolved > in ≥2 seed chunks > type priority (ImpactStatement,
   Incident, Person, Procedure, Component, System, StartupStep, FirewallRule, Host, rest) > seed rank. One hop over
   **all** edge types in the union adjacency (edges tagged with doc_id; identical `edge_id` in two books merged
   into one fact with `doc_ids`). Facts capped at 40, ordered label-resolved first, negative before positive,
   then relation priority (DEPENDS_ON, IMPACT_OF, RESPONSIBLE_FOR, ESCALATES_TO, PARTNER_TICKET, PRECEDES,
   RUNS_ON, GOVERNED_BY, TENANT_OF, others). Entity cards = start + reached nodes with attributes, grouped by
   node_id (occurrence per doc_id, conflicts side by side) then by norm label/alias; cap 15. Graph chunk list =
   provenance chunk_ids of kept facts, then of label-resolved nodes, then of neighbours; cap 15; `mget`.
   Re-run RRF over the five lists → `final_k`.
6. **Group** table parts: key `doc_id|caption` for tables with caption, else per chunk. Pages = union.
7. **Citations**: one per (doc_id, pages) of included groups plus per fact. Timings per stage in diagnostics.

### Prompt (German) and context rendering

System prompt (final wording in `prompt.py`): answer only from context; cite as `[BHB-PLT-0007 S. 19]`; if not
covered answer exactly "Dazu steht nichts in den Handbüchern."; render NICHT / "keine Auswirkung" facts as
negations with their reason; on conflicting manuals give both with sources; German, concise, identifiers verbatim.

`render_context` order: **Entitäten** (entity cards: `Label (Type) — k: v; … [doc S. x]`), **Fakten**
(`A —REL (label_de)→ B (props) [doc S. x; Kante id]`; negatives `: NICHT (qualifier) — „quote“`; unknown
`(unsicher)`), **Quellen** (`### Quelle n · doc „title“ · S. x · breadcrumb|caption (n Teile) · chunk ids` then
body_text; table parts: header once, rows of all parts). Budget: facts/entities first, then groups by rank using
stored `token_count` (+~40/header) until `context_token_budget`; dropped ids reported. `build_messages` =
system + last 6 history messages + `Kontext:\n…\n\nFrage: …`.

### Guardrail (`guardrail.decide`)

`weak_evidence` iff enabled AND no identifier hits, no label-resolved nodes, no graph facts AND (BM25 returned 0
hits OR none of the top 3 fused chunks was found by ≥2 channels). Reasons: "no lexical overlap with the corpus" /
"only the kNN channel found the top hits". Never consults absolute cosine (REPORT §7). `answer()` short-circuits
to `NO_EVIDENCE_ANSWER`; `force=True` overrides for debugging.

### CLI (`typer`, `osi` shape; callback `--url/--prefix/--ontology/--log-level` set `RAG__*` and clear cache)

- `rag-retrieve ask "Frage" [--graph/--no-graph] [--k] [--doc …] [--json] [--answer] [--stream] [--force]
  [--model] [--show-context] [--budget] [--history-file]` → identifiers, labels, start nodes, ranked groups with
  `via knn#2 bm25#1 graph(DEPENDS_ON from Vault)`, facts (NICHT prefixed), entities, guardrail verdict, timings;
  exit 2 on weak evidence with `--answer`.
- `rag-retrieve graph-stats [--json]`, `rag-retrieve entities "Vault"`, `rag-retrieve check`.

### Tests

Unit (no services): `fake_search_client.py` (knn = cosine over 8-dim stored vectors, multi_match = token
overlap, term/terms/bool, msearch, mget, get; content from `transform.build_batch(response_small, dim=8)`);
`test_query` (identifiers incl. host/zone/uppercase doc id; label n-grams, stopwords, ß lowercase vs casefold);
`test_search_bodies` (excludes, doc_id filter placement, empty clauses omitted); `test_fusion` (RRF math,
tie-breaks, channel union, table grouping on ZSD Tabelle 4/5 → pages 8–9, header dedupe); `test_graph` (real
graphs, skip if absent: 60 shared ids, edge id computation, Vault 1-hop yields the two negative DEPENDS_ON edges,
PRECEDES chain = 11 edges, label index "vault" → System/Component/Host, start-node cap); `test_facts` (negative
rendering with quote, label_de, Kai Ostermann alias merge, attribute conflicts kept, severity=keine card);
`test_prompt` (order, budget drops + dropped ids, headers, build_messages shape, ValueError over limit);
`test_guardrail` (5 cases); `test_embed`/`test_chat` (httpx.MockTransport: bearer, prefix, dim mismatch, 503
retry, trust_env False, SSE parsing, rewrite no-LLM path + fallback, answer short-circuit); `test_retriever`
(fast vs slow on response_small, diagnostics, mismatch warning); `test_cli` (CliRunner).

Integration (`RAG_INTEGRATION=1`, live, read-only): embed one question (dim 1024), `check()` ok, then fast and
slow on the ground-truth table below asserting doc_ids/pages in top groups, facts and `weak_evidence`.

### Ground-truth questions (pages verified in fixtures/live index) — also the chat test script

| # | Question | Expect |
|---|---|---|
| 1 | Wer ist für IAM/Keycloak zuständig und wie eskaliere ich? | BHB-PLT-0007 S. 1–2 (Kai Ostermann, 1315), S. 26 (Rollen/Eskalation); fact `Kai Ostermann —ESCALATES_TO→ Dr. Annika Reuß (level=2)` |
| 2 | Was passiert, wenn Vault versiegelt ist? | BHB-PLT-0001 S. 19 (Tabelle 12, VPP "keine"), S. 12, 15; BHB-PLT-0007 S. 19, 15; slow: entity `Vault versiegelt \| VPP` severity=keine, negative `Vault —DEPENDS_ON→ PKI/Keycloak NICHT` |
| 3 | Was war bei ZSDSUP-0247? | identifier channel; BHB-PLT-0007 S. 22–23; BHB-PLT-0001 S. 21, 23; facts PARTNER_TICKET → CAASUP-0351, DDSUP-1201 |
| 4 | In welcher Reihenfolge fährt der Verbund nach einem Totalausfall an? | BHB-PLT-0001 S. 20 (Tabelle 13); ≥8 PRECEDES facts; BHB-PLT-0007 S. 17 |
| 5 | Auf welchen Servern und Ports läuft ZSD? | BHB-PLT-0007 S. 8–9 (Tabelle 4), S. 9–10 (Tabelle 5); fast-mode control |
| 6 | Wer darf Vault entsiegeln und wie? | BHB-PLT-0007 S. 15 (SOP-ZSD-05, Marcel Ebert), S. 17; BHB-PLT-0001 S. 15, 19–20 |
| 7 | Ich will den Dispatcher neu starten – was hängt daran? | BHB-PLT-0007 S. 11–12, 19; BHB-PLT-0001 S. 14–15; partial until BHB-PLT-0042 indexed |
| 8 | Wie erneuere ich ein TLS-Zertifikat? | BHB-PLT-0007 S. 15–17; BHB-PLT-0001 S. 16 |
| G | Wie backe ich einen Apfelkuchen? | `weak_evidence == True`, no model call |
| R | history "Wer ist für Vault zuständig?" + "und bei Keycloak?" | rewritten question mentions Keycloak + zuständig |

### Gotchas to encode

Lucene kNN: set both `k` and `size`, filter inside the knn clause. `node_labels` terms use `.lower()`. Never
query `attributes` (flat_object); read from the in-memory graph. `trust_env=False` on both httpx clients.
Ollama-backed models have small `num_ctx` → keep budget 6000, default `gemini-dev`. `Retriever` holds no
per-request state (Streamlit calls it from many sessions; chat-system builds one via `st.cache_resource`).
`retrieve()` returns `RetrievalResult` (a superset of SPEC's `list[Chunk]`) — note in README. Add a one-line ADR
addendum note in `retrieval/README.md` that 1-hop over all relations follows graph-retrieval-patterns §4.4 rather
than ADR-0004's intent allowlist.

---

## Cross-module contract decisions (reconciled between the two designs)

- **One `.env` per running module, three prefixes.** `chat-system/.env` carries `CHAT__*`, `RAG__*` and `USERS__*`
  keys (pydantic-settings reads `.env` from CWD, so running Streamlit from `chat-system/` feeds all three
  Settings classes). `retrieval/.env` exists for the standalone CLI.
- **`config.yaml` collision:** `rag_retrieval.settings.config_path()` resolves `RAG_CONFIG` > packaged default
  (`retrieval/config.yaml`) and **skips `./config.yaml`** — otherwise it would load `chat-system/config.yaml`
  when run from that folder. chat-system keeps the full `CHAT_CONFIG > ./config.yaml > packaged` chain.
- **LLM config lives once, in `RAG__LLM__*`.** chat-system has no `llm` section; `wiring.build_service()` builds
  `ChatClient(rag_settings.llm)` and passes it to `rewrite_question` and answer streaming. Switching the model
  = `RAG__LLM__MODEL` in `chat-system/.env`.
- **Guardrail:** the service checks `result.weak_evidence` itself, yields `rag_retrieval.NO_EVIDENCE_ANSWER`,
  persists `guardrail=True, llm_called=False`; `rag_retrieval.answer()` exists for the CLI path.
- **No adapter layer in chat-system.** The service imports `rag_retrieval` types directly (pydantic, stable);
  `retriever` and `llm` are duck-typed constructor args so tests inject fakes. Citations/facts persisted as
  `result.citations`/`result.facts` `model_dump()`.
- **`doc_ids` filter** flows: users `Policy.effective_doc_ids(ctx, requested)` → `retrieve(..., doc_ids=…)` →
  knn filter + bool filter (see retrieval step 3).

---

## Module 2: `users/` — package `rag_users` (mock; "roughly one file")

```
users/
  pyproject.toml   name "rag-users", hatchling, deps pydantic>=2.7, pydantic-settings>=2.4; dev pytest, ruff
  README.md        what is mocked, env vars, how to swap the adapter; flags allowed_doc_ids as an ADDITION beyond SPEC §10.2
  Makefile         venv dev test lint (normally installed into chat-system/.venv)
  src/rag_users/__init__.py   (~150 lines, everything below)
  tests/test_users.py
```

```python
class AuthContext(BaseModel, frozen=True): user_id: str; email: str; groups: tuple[str, ...]
class Unauthenticated(Exception)
USERS: dict[str, AuthContext] = {"dev": (dev@bavd.example, ("bavd-ops",)), "otto.ops": (…, ("bavd-ops",)),
                                 "rita.read": (…, ("bavd-readonly",)), "anna.admin": (…, ("admin","bavd-ops"))}
class AuthAdapter(Protocol): def current(self) -> AuthContext
class EnvAuthAdapter(user_id)                              # USERS__DEV_USER; unknown -> Unauthenticated
class HeaderAuthAdapter(headers, *, user_header="X-Forwarded-User", email_header="X-Forwarded-Email",
                        groups_header="X-Forwarded-Groups")   # missing user header -> Unauthenticated; groups split ","
class GroupLimits(frozen): daily_messages: int; max_turns_per_conversation: int; allowed_doc_ids: tuple[str,...] | None
RULES = {"admin": (100, 20, None), "bavd-ops": (10, 10, None), "bavd-readonly": (5, 5, ("BHB-PLT-0007",))}
DEFAULT_LIMITS = GroupLimits(10, 10, None)                # SPEC: 10 messages/user/day
class UsageStore(Protocol): count(user_id, day) -> int; increment(user_id, day, by=1) -> int
class Decision(frozen): allowed: bool; reason: Literal["ok","daily_cap","turn_cap","forbidden"]; remaining_today: int; limits
class Policy:
    def limits_for(self, ctx) -> GroupLimits              # max across groups; None doc filter wins
    def check_message(self, ctx, usage: UsageStore, *, today: date, turns_in_conversation: int) -> Decision
    def effective_doc_ids(self, ctx, requested: list[str] | None) -> list[str] | None   # intersection; [] = forbidden
class UsersSettings(BaseSettings):  # USERS__ prefix, .env, extra ignore
    adapter: Literal["env","header"]="env"; dev_user="dev"; header_user/email/groups = X-Forwarded-*
def get_settings() -> UsersSettings; def get_adapter(settings, headers: Mapping | None = None) -> AuthAdapter
```
Tests: env adapter identity; unknown dev user raises; header adapter parsing (case-insensitive, comma groups,
missing header raises); `limits_for` max-over-groups and None-dominates; daily cap and turn cap refusals with
`remaining_today`; `effective_doc_ids` intersection and `[]` for readonly asking CaaS only; `get_adapter` honours
`USERS__ADAPTER`.

---

## Module 3: `chat-system/` — package `chat_system`

### Layout

```
chat-system/
  README.md  DEPLOY.md  Makefile  Dockerfile  compose.yaml  .env.example  .gitignore  pyproject.toml  alembic.ini
  requirements.txt       -e ../opensearch-index ; -e ../users ; -e ../retrieval ; -e .[dev]
  config.yaml            CHAT__ defaults; CHAT_CONFIG selects another file
  app.py                 `from chat_system.ui.app import main; main()`  -> streamlit run app.py
  .streamlit/config.toml [server] headless=true address="127.0.0.1" port=8501; [browser] gatherUsageStats=false; [client] toolbarMode="viewer"
  src/chat_system/
    settings.py          CHAT__ prefix (copy of osi settings.py)
    db.py                make_engine(url) (SQLite: WAL + busy_timeout + check_same_thread=False), session factory,
                         TZDateTime TypeDecorator, ensure_schema() (alembic upgrade head when db.auto_upgrade)
    models.py            SQLAlchemy 2.x DeclarativeBase: Conversation, Message, Usage
    repository.py        Repository + UsageRepo (implements rag_users.UsageStore)
    service.py           ChatService, TurnStream, TurnRefused, Quota  (never imports streamlit — enforced by test)
    catalog.py           list_documents() from bhb-documents (doc_id, title, version, root_system), 5-min cache
    wiring.py            build_service(settings) -> ChatService with real Retriever/ChatClient (lazy imports)
    cli.py               typer: chat-ask | chat-db (upgrade|revision|current) | chat-doctor
    ui/app.py (main)  ui/auth.py  ui/sidebar.py  ui/chat.py
  migrations/env.py  script.py.mako  versions/0001_initial.py
  scripts/wait_db.sh  scripts/smoke_questions.txt
  tests/unit/  tests/integration/   data/ (gitignored: chat.db)
```
Deps: `streamlit>=1.50,<2` (resolves 1.63.0 today; record in README), `sqlalchemy>=2.0.30,<3`,
`alembic>=1.13,<2`, `psycopg[binary]>=3.2,<4`, `pydantic`, `pydantic-settings`, `pyyaml`, `typer`, `httpx`. Sibling
packages only in `requirements.txt` (keeps the Dockerfile tomllib dependency-layer trick working). Scripts:
`chat-ask`, `chat-db`, `chat-doctor`. Ruff/pytest config as opensearch-index; markers `integration`, `ui`.

### Settings (`CHAT__SECTION__KEY`)

| Section | Keys (defaults) |
|---|---|
| `db` | `url` (`sqlite:///./data/chat.db`), `echo` (false), `auto_upgrade` (true) |
| `retrieval` | `k` (8), `k_graph` (12), `history_turns_for_rewrite` (2), `use_graph_default` (true) |
| `limits` | `max_concurrent_answers` (10) — in-process `BoundedSemaphore`; caps per user come from `rag_users.Policy` |
| `ui` | `title` ("Betriebshandbuch-Assistent"), `allow_user_switch` (true in dev .env, false remote), `show_diagnostics_default` (false), `conversation_list_limit` (20) |

### DB schema (portable, ADR-0007 leak list avoided)

```
conversations  id String(36) PK uuid4 (app-generated) · user_id String(128) NOT NULL (index) · title String(200)
               use_graph_default Boolean · doc_ids JSON NULL · turn_count Integer default 0 · status String(16) 'open'|'capped'
               created_at/updated_at TZDateTime (UTC-aware on both dialects)
messages       id Integer PK · conversation_id FK ON DELETE CASCADE · seq Integer, UNIQUE(conversation_id, seq)
               role 'user'|'assistant' · content Text · question_rewritten Text NULL (assistant rows: both forms, ADR-0011)
               use_graph Boolean NULL · citations JSON · diagnostics JSON · guardrail Boolean default false
               finish_reason String(16) ('stop'|'length'|'aborted'|'error'|'guardrail') · model String(64) · latency_ms Integer
               created_at TZDateTime
usage          user_id String(128), day Date, PK(user_id, day) · count Integer default 0 · updated_at TZDateTime
```
`usage.increment` = UPDATE … count+by; rowcount 0 → INSERT; IntegrityError → retry UPDATE (portable, no dialect
upsert). Alembic `env.py` reads `get_settings().db.url`, `render_as_batch=True`, `compare_type=True`.

### Repository and service (exact signatures)

```python
class Repository(session_factory):
    create_conversation(user_id, *, use_graph, doc_ids) -> Conversation
    get_conversation(conversation_id, user_id) -> Conversation | None        # user scoping = authorisation
    list_conversations(user_id, *, limit=20) -> list[Conversation]           # updated_at desc
    list_messages(conversation_id) -> list[Message]                          # by seq
    add_user_message(conversation_id, content) -> Message                    # seq, turn_count+=1, title on first
    add_assistant_message(conversation_id, content, *, question_rewritten, use_graph, citations, diagnostics,
                          guardrail, finish_reason, model, latency_ms) -> Message
    mark_capped(conversation_id) -> None
    usage() -> UsageRepo                                                     # count(), increment(by=1|-1)

@dataclass class TurnResult: conversation_id, message_id, answer, citations: list[dict], facts: list[dict], diagnostics,
                             guardrail, question_raw, question_rewritten, use_graph, finish_reason, latency_ms,
                             remaining_today, turns_left
@dataclass(frozen) class Quota: used_today, daily_cap, max_turns
class TurnRefused(Exception): reason: Literal["daily_cap","turn_cap","forbidden","busy"]; message_de; remaining_today

class ChatService(repo, policy, retriever, llm, settings, clock=utcnow):
    documents(ctx) -> list[dict]                        # catalog ∩ policy allowed_doc_ids
    quota(ctx) -> Quota
    start_conversation(ctx, *, use_graph, doc_ids) -> Conversation
    list_conversations(ctx) -> list[Conversation]
    resume(ctx, conversation_id) -> tuple[Conversation, list[Message]]      # TurnRefused("forbidden") if not owner
    ask(ctx, conversation_id, question, *, use_graph, doc_ids) -> TurnStream
class TurnStream: citations, facts, diagnostics, guardrail, question_rewritten, result, done
    tokens() -> Iterator[str]        # persists partial text + finish_reason="aborted" on GeneratorExit/BaseException
    abort() -> None                  # idempotent; UI calls in finally
    collect() -> TurnResult          # CLI/tests
```
`ask()` phases: (1) `policy.check_message` + `effective_doc_ids` → `TurnRefused` (nothing persisted/counted);
`mark_capped` at the turn cap; (2) semaphore non-blocking → `busy`; (3) one transaction: `usage.increment`
(reservation, survives a second tab) + `add_user_message`; (4) `rewrite_question` if history (last 2 turns),
both forms kept; (5) `retrieve(rewritten, use_graph, k, doc_ids)`; (6) `weak_evidence` → stream yields
`NO_EVIDENCE_ANSWER`, persist `guardrail=True`, `llm_called=False`; else `build_messages(result, raw, history)`;
(7) `tokens()` streams `llm.stream(messages)`, measures first-token/total latency; (8) `add_assistant_message`,
release semaphore; on LLM error persist `finish_reason="error"` and refund usage (`by=-1`).
Diagnostics JSON = `result.diagnostics.model_dump()` + `{rewritten_question, use_graph, doc_ids, weak_evidence,
llm_called, model, timings_ms{rewrite, retrieve, first_token, total}, prompt_chars, facts}`.

CLI: `chat-ask "Frage" [--graph/--no-graph] [--user dev] [--conversation ID] [--doc-id X …] [--json]` streams
tokens, then `Quellen:` lines; `chat-db upgrade|revision -m|current`; `chat-doctor` (DB + alembic head,
OpenSearch documents via catalog, LLM `/models` probe with `trust_env=False`, resolved user + limits, warning when
`k × 512 + 1500 > context_limit_tokens`).

### Streamlit UI event flow

1. `main()`: `st.set_page_config(title, layout="wide")`; `svc = get_service()` (`@st.cache_resource`: settings,
   engine, `ensure_schema()`, Retriever, ChatClient once per process); `ctx = ui.auth.resolve()`: sidebar
   `selectbox` over `rag_users.USERS` when `ui.allow_user_switch` (the "simulated ingress"), else
   `get_adapter(users_settings, headers=st.context.headers).current()`; `Unauthenticated` → `st.error` + `st.stop()`.
2. Sidebar: `user_id · groups`; `st.metric("Nachrichten heute", "used/cap")`; "Neues Gespräch" button;
   conversation `selectbox` (title · date) → `resume`; `st.toggle("Graph-Modus (langsam)")`;
   `st.multiselect("Handbücher", svc.documents(ctx))` (empty = all allowed); `st.checkbox("Diagnostik anzeigen")`.
3. Main: replay `messages` via `st.chat_message`; assistant rows get `st.expander("Quellen (n)")` (`[n] **doc_id**
   title · S. pages · breadcrumb`, quote, channel tags) and, when enabled, `st.expander("Diagnostik")` (mode,
   rewritten question, channel counts, timings, facts with negatives as `:red[NICHT …]`, model, weak_evidence).
4. Capped conversation → `st.info(...)` + `st.chat_input(disabled=True)`.
5. `st.chat_input` submit → create conversation if none → user bubble → `with st.status("Suche in den
   Handbüchern …")`: `turn = svc.ask(...)` (`TurnRefused` → `st.warning`) → `with st.chat_message("assistant")`:
   `try: st.write_stream(turn.tokens()) finally: if not turn.done: turn.abort()` → references/diagnostics →
   append to state → `st.rerun()` (quota + list refresh; history never re-streams).

### Tests

Unit (`tests/unit/conftest.py`: in-memory SQLite `StaticPool`, `FakeRetriever` returning canned
`RetrievalResult`s incl. `weak_evidence` switch, `FakeLLM` yielding tokens/raising, `Policy()`, ctx fixtures;
`CHAT_TEST_DB_URL` reruns repository tests on Postgres): `test_repository` (scoping, seq, JSON round trip,
UTC-aware datetimes, increment UPDATE/INSERT + refund); `test_service_flow` (tokens streamed, assistant row with
citations/diagnostics/rewritten; rewrite skipped on first turn, called with last 2 turns after; use_graph and
effective doc_ids reach retrieve; raw question to build_messages); `test_service_limits` (11th message refused
without persisting; second conversation shares counter; turn cap marks capped; readonly + CaaS-only →
forbidden; LLM error → error + refund; semaphore → busy); `test_service_guardrail` (canned sentence, LLM calls 0);
`test_service_abort` (partial content, aborted); `test_cli` (CliRunner, `wiring.build_service` monkeypatched);
`test_migrations` (upgrade head on tmp SQLite, `compare_metadata` empty); `test_no_ui_imports`;
`test_ui_smoke` (marker `ui`, `AppTest.from_file("app.py")`, fake service, chat_input → assistant message +
`Quellen` expander; cap text after limit).

Integration (`CHAT_INTEGRATION=1`, real wiring, tmp SQLite): the 3 smoke questions ("Auf welchen Servern läuft
ZSD?" fast, "Was war bei ZSDSUP-0247?", "Was passiert, wenn Vault versiegelt ist?" graph) → non-empty answer,
≥1 citation with doc_id in the two books, both question forms in DB; off-topic question → guardrail,
`llm_called=False`.

### Deployment artefacts

- **Makefile:** `venv dev lint test test-ui test-integration doctor db-init db-upgrade db-revision run ask smoke
  db-up db-down up down image-build up-enterprise logs health` (`run` = `streamlit run app.py --server.address
  ${CHAT_BIND:-127.0.0.1} --server.port ${CHAT_PORT:-8501}`; `health` = `curl -fsS --noproxy '*'
  http://127.0.0.1:8501/_stcore/health`; `db-up` = `compose --profile postgres up -d postgres` + `wait_db.sh`).
- **compose.yaml** (x-build anchor from opensearch-index, `context: ..`, `dockerfile: chat-system/Dockerfile`):
  `chat` (profile `local`, `network_mode: host`, `env_file: .env`), `chat-enterprise` (profile `enterprise`,
  `${CHAT_BIND:-127.0.0.1}:${CHAT_PORT:-8501}:8501`, `CHAT__DB__URL=postgresql+psycopg://chat:…@postgres:5432/chat`,
  `depends_on: [postgres]` list form, `replicas: 1` comment), `postgres` (profile `postgres`,
  `postgres:16-alpine`, `127.0.0.1:5432`, **named volume** `chat-pgdata` — no rootless chown dance).
- **Dockerfile:** `python:3.12-slim`, `BASE_IMAGE/PIP_INDEX_URL/PIP_TRUSTED_HOST` args, `STREAMLIT_*` env
  (telemetry off, headless, no file watcher); layer 1 installs the union of the four `pyproject` dependency
  lists (tomllib + glob); layer 2 copies `opensearch-index/`, `users/`, `retrieval/`, `chat-system/` sources and
  `pip install --no-deps` all four; uid 10001; `WORKDIR /app/chat-system`; `ENTRYPOINT ["streamlit","run","app.py"]`.
  Root `.dockerignore` excludes `**/.venv **/data **/.env **/tests out/ venv-rag/ user-manual-books/ *.tar.gz`.
- **`.env.example`** DEV BOX block (active): `CHAT__DB__URL=sqlite:///./data/chat.db` (+ commented Postgres
  line), `CHAT__UI__ALLOW_USER_SWITCH=true`, `RAG__OPENSEARCH__URL`, `RAG__EMBEDDING__API_KEY`, `RAG__LLM__API_KEY`,
  `RAG__LLM__MODEL=gemini-dev` (comments: `granite4` CPU/slow → `CHAT__RETRIEVAL__K=4`,
  `RAG__LLM__CONTEXT_LIMIT_TOKENS=4096`; Ollama direct `http://localhost:11434/v1` + `gemma4:e2b`),
  `USERS__ADAPTER=env`, `USERS__DEV_USER=dev`, `POSTGRES_PASSWORD`. REMOTE block: tunnel `localhost:11435/v1`,
  e5 `query: ` prefix, `SELINUX_LABEL=,Z`, `ALLOW_USER_SWITCH=false`, build args, no proxy vars.
- **README.md** ("chat-system — module 4: chat over the indexed manuals"): verified paragraph (after smoke),
  how a question is answered (8 phases), quick start, users & limits (mock), configuration table, CLI table,
  development, limitations/next. **DEPLOY.md** §0–§6 in the existing skeleton (Postgres or SQLite, rsync of the
  four folders, `.env`, image build via Artifactory/proxy, run variants, rootless podman notes, troubleshooting).
- **Root README** module table: replace the "retrieval / UI … next modules" row with `retrieval/`, `users/`,
  `chat-system/` rows. No git init for the new folders unless asked.

---

## Sequencing

1. `users/` → tests green (no deps).
2. `retrieval/`: settings, llm_http, embed, chat → models, graph, query, search, fusion, facts, guardrail,
   prompt, retriever, cli → unit tests green → `RAG_INTEGRATION=1` live tests → `rag-retrieve ask` on the 8
   questions fast and slow (+ `--answer` with gemini-dev on 3–4) → `retrieval/REPORT.md`.
3. `chat-system/`: settings, db/models/repository, Alembic 0001, repository + migration tests → service, cli,
   fakes, unit tests → UI + AppTest smoke → `make doctor`, `make smoke`, integration test → Postgres path once
   (`make db-up`, `CHAT__DB__URL=postgresql+psycopg://…`, repository tests with `CHAT_TEST_DB_URL`) → Dockerfile,
   compose (`docker compose --profile local build` verified), `.env.example`, README, DEPLOY.
4. Root README table; memory note update.

## Verification (end to end)

```bash
# users
cd users && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/python -m pytest -q
# retrieval
cd ../retrieval && make venv dev && make test && make check
RAG_INTEGRATION=1 make test-integration
.venv/bin/rag-retrieve ask "Was passiert, wenn Vault versiegelt ist?" --graph --answer --stream
.venv/bin/rag-retrieve ask "Was war bei ZSDSUP-0247?" --no-graph
.venv/bin/rag-retrieve ask "Wie backe ich einen Apfelkuchen?" --answer     # -> guardrail, exit 2
.venv/bin/rag-retrieve graph-stats
# chat-system
cd ../chat-system && cp .env.example .env && make dev && make doctor && make db-init
make ask Q="Auf welchen Servern läuft ZSD?"
make ask Q="Was passiert, wenn Vault versiegelt ist?" ARGS="--graph --user otto.ops"
make ask Q="Was war bei ZSDSUP-0247?" ARGS="--user rita.read"               # readonly: ZSD only
make test && make test-ui && CHAT_INTEGRATION=1 make test-integration
make run    # http://127.0.0.1:8501 — ask the 8 questions, toggle Graph-Modus, open Quellen/Diagnostik, resume a conversation
make db-up && CHAT__DB__URL=postgresql+psycopg://chat:chat@localhost:5432/chat make db-upgrade && CHAT_TEST_DB_URL=… make test
docker compose --profile local build          # image builds from repo-root context
```
Acceptance: all unit + integration suites green; the fast/slow toggle visibly changes the Vault answer (slow
shows the negative DEPENDS_ON facts and the VPP "keine" entity); every assistant message shows citations with
doc_id + page; the off-topic question never calls the model; `retrieval/REPORT.md` records per-question hits,
channels, facts and observations; existing modules (`docling-graph/`, `opensearch-index/`) are **not modified**.
