# rag-prototype

RAG system over German IT operations manuals (Betriebshandbücher): documents are parsed once into
Markdown + provenance-carrying chunks + an ontology-grounded knowledge graph; retrieval combines vector
search over the chunks with graph traversal, every answer citable down to page and table. The corpus is a
fictional five-manual universe (`user-manual-books/`) built for exactly this pipeline; the full architecture
lives in [`SPEC.md`](SPEC.md) and `docs/adr/`.

A study-oriented technical report of the whole system (ontology, graph building, storage, retrieval, results) is
[`TECHNICAL-REPORT.md`](TECHNICAL-REPORT.md). Changes to agreed behaviour are recorded as requirement documents in
`<module>/requirements/` (first: [`retrieval/requirements/REQ-001-robust-question-understanding.md`](retrieval/requirements/REQ-001-robust-question-understanding.md)
and its [chat-system counterpart](chat-system/requirements/REQ-001-robust-question-understanding.md)).

## Components

| Path | What it is | Status |
|---|---|---|
| [`docling-graph/`](docling-graph/) | **Module 1: ingestion & graph-extraction microservice.** FastAPI + Docker; one `POST /v1/process` turns a PDF into Markdown, embedded chunks and a knowledge graph, all model calls on remote OpenAI-compatible endpoints | done, verified on the ZSD manual |
| [`opensearch-index/`](opensearch-index/) | **Module 2: OpenSearch store.** Compose node (k-NN, data persisted in the module folder) + `osi` CLI that indexes the `out/` products idempotently: chunks + vectors + identifiers + graph reverse index, nodes, the graph blob per document, a manifest per document; same output = no-op, new extraction = replace | done, verified on the ZSD run (`osi verify/bootstrap/ingest/status/search`) |
| `user-manual-books/handbuch_daten/` | test corpus: 5 PDFs, the ontology (`Ontologie/ontology.yaml` — the service's standard input format), reference diagrams | fixed test data |
| `docs/`, `SPEC.md`, `NEXT-STEPS.md` | architecture decisions, overall spec, roadmap | living docs |
| [`integration/`](integration/) | **Phase 2, step 1: process → index orchestration.** One command per manual (or per directory): docling-graph `POST /v1/process` → `out/<run>/` → `osi` ingest; `cross_book_report.py` shows what several books share (shared node ids, cross-book edges, the documented cycle) | script + tests done, smoked locally (`integration/REPORT.md`); CaaS run on the server next |
| [`retrieval/`](retrieval/) | **Module 3: retrieval + prompt injection.** `rag_retrieval` library + `rag-retrieve` CLI: question → four OpenSearch channels fused client-side (RRF) → 1-hop graph expansion over the union graph of all books (facts with polarity, entity cards, provenance) → German context block + citations; guardrail (ADR-0011, amended by REQ-001: graded prompt, follow-up rule, visible truncation), OpenAI-compatible chat client with streaming and question rewriting | done, verified on both books (`retrieval/REPORT.md`: 8 ground-truth questions, 111 unit + 13 integration tests) |
| [`users/`](users/) | **Module 4: auth/policy seam (mock).** `rag_users` library: `AuthContext{user_id, email, groups}` from an env adapter (fixed identity) or the oauth2-proxy header adapter (SPEC §10.2, ADR-0008); hardcoded users, per-group daily message cap, turn cap and allowed manuals (addition beyond the SPEC) as a `doc_ids` filter for retrieval; usage counting stays in the chat backend (`UsageStore` protocol) | done, verified (`users/REPORT.md`: 39 unit tests, read-only filter pushed through the live retriever) |
| [`chat-system/`](chat-system/) | **Module 5: the chat.** Streamlit UI + `ChatService` backend over `retrieval` and `users`: streamed answers with citations on every answer, fast/slow (graph) toggle, per-manual filter, diagnostics on demand, conversations resumable; SQLAlchemy/Alembic DB (SQLite default, Postgres compose profile); `chat-ask` headless CLI, `chat-db`, `chat-doctor`; Dockerfile + compose (host-network `local`, published-port `enterprise`) | done, verified (`chat-system/REPORT.md`: 49 unit tests also on Postgres, 4 AppTest, 8 live tests, 6 smoke questions, container run) |

Key documents inside `docling-graph/`:

| File | Content |
|---|---|
| [`README.md`](docling-graph/README.md) | service usage, API + ontology contract, configuration, verified ZSD results |
| [`service-flow.md`](docling-graph/service-flow.md) | phase-by-phase flow diagram (tools per step, inputs, outputs) |
| [`DEPLOY.md`](docling-graph/DEPLOY.md) | remote deployment: files, image build/transfer, `.env`, compose profiles, RHEL notes |
| [`graph-retrieval-patterns.md`](docling-graph/graph-retrieval-patterns.md) | how the output is structured, what to index, retrieval design for the next modules |

## Quick start (chat over the indexed manuals)

```bash
cd chat-system && cp .env.example .env && make dev && make doctor && make run    # http://127.0.0.1:8501
make ask Q="Was passiert, wenn Vault versiegelt ist?"                                   # headless
```

Needs the OpenSearch node with the manuals indexed (`opensearch-index`) and the embedding/LLM endpoint from `.env`.

## Quick start (ingestion service)

```bash
cd docling-graph
cp .env.example .env                       # pick your machine block (endpoints, models, ontology path)
docker compose --profile local up -d       # endpoints on the host's loopback (LiteLLM / SSH tunnels)
curl -s localhost:8080/healthz
python3 scripts/process_via_api.py ../user-manual-books/handbuch_daten/handbuch/Betriebshandbuch_ZSD.pdf \
    --url http://localhost:8080 --out out/zsd
```

Profiles: `local` = model endpoints on the host's loopback (dev box or SSH tunnels on a server, host
networking); `enterprise` = real remote endpoints (published port, Artifactory/proxy build args). Details and
the decision table: [`docling-graph/DEPLOY.md`](docling-graph/DEPLOY.md) §4.

## Visualizing results

Every processed document lands as one folder (`graph.json`, `chunks.json`, `markdown.md`, `summary.json`)
under the `--out` root. A dependency-free viewer (Python stdlib + one HTML page, no frontend libraries)
serves them for inspection:

```bash
cd docling-graph
python3 scripts/serve_viewer.py --dir out          # then open http://127.0.0.1:8081
```

- **run picker** — every subfolder of `--dir` that contains results;
- **Graph tab** — nodes grouped by ontology class with search; the selected node's attributes, aliases,
  quote and provenance (pages, table/figure, section); its incoming/outgoing edges with polarity, qualifier,
  quote and typed properties (negative edges marked red); a 1-hop SVG neighbourhood — click any neighbour or
  edge to navigate; the right panel shows the **verbatim source chunks** grounding the selection;
- **Chunks tab** — all chunks with full text (tables as Markdown) and searchable;
- **Meta tab** — run summary, counts, `unresolved_targets` (the review queue), conflicts, violations.

Remote practice: the viewer binds `127.0.0.1` and is read-only. On a server, run it next to the output folder
and tunnel the port (`ssh -L 8081:localhost:8081 user@server`) instead of exposing it; `--host 0.0.0.0` only
inside a trusted network. It has no access to the service — it reads output folders, so it also works on a
machine that only holds copied results.

## Conventions

- **pip, not uv** — the enterprise environment installs through an Artifactory PyPI proxy.
- `.env` is machine-local and gitignored; [`docling-graph/.env.example`](docling-graph/.env.example) is the
  shared template with one commented block per machine — mirror changes there to keep setups parallel.
- All model access goes through OpenAI-compatible endpoints; swapping LiteLLM/gemini (dev) for
  vLLM/qwen + TEI (enterprise) is configuration only.
