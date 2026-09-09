# Remote runbook: second book, retrieval, users, chat

Steps to run **on the server** (CentOS/RHEL, rootless podman behind the `docker` alias, SELinux enforcing,
Artifactory PyPI, model endpoints through SSH tunnels on the loopback). Nothing here runs on the dev box.

Starting point (verified 2026-09-03): the OpenSearch node of `opensearch-index/` is set up there and holds
**BHB-PLT-0007 (ZSD)**; docling-graph produced the CaaS run (`<out>/<caas-run>/response.json`) with the
server's models. Target: both books indexed, retrieval → users → chat verified in that order, and at the end only
**OpenSearch + tunnels + one Streamlit process** running.

`<base>` = the folder holding the module directories (e.g. `/srv/rag`). `<out>` = the docling-graph output folder
(e.g. `/srv/rag/out`). `$PIP_INDEX_URL` = the Artifactory simple index.

---

## 0. Memory plan: what runs when

| Component | RAM (order of magnitude) | Needed for | Phase |
|---|---|---|---|
| OpenSearch node (`OPENSEARCH_HEAP=2g`) | 2 GB heap + ~1 GB | everything | always |
| docling-graph container (`dgs`) | several GB (torch, docling models) | **only** processing new PDFs | stop before phase 1 |
| SSH tunnels (embedding + chat model) | negligible | phases 2–4 | phases 2–4 |
| `osi` / `rag-retrieve` CLI runs | < 300 MB each, short-lived | checks | phases 1–2 |
| Streamlit (`make run`, imports users + retrieval in-process) | ~300–600 MB | UI | phase 4 → end state |
| Postgres container | ~150 MB | not needed for the test | skip (SQLite) |
| OpenSearch Dashboards | ~1 GB | never needed | skip |

Before anything:

```bash
free -h
docker ps --format 'table {{.Names}}\t{{.Status}}'
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}'
```

The CaaS `response.json` already exists, so docling-graph is not needed for anything below:

```bash
cd <base>/docling-graph && docker compose --profile local down     # or: make compose-down   (enterprise: --profile enterprise down)
```

Bring it back only when you process another PDF (`docker compose --profile local up -d`).

---

## 1. Code on the server

Git tracks `retrieval/`, `users/`, `chat-system/`, `integration/`, `out/` and the root files; `opensearch-index/`,
`docling-graph/`, `user-manual-books/` are **not** tracked (synced by rsync earlier). Whatever route you use, the
four Python modules must be **siblings** (the requirements files install `-e ../opensearch-index` etc.):

```
<base>/
├── opensearch-index/   (already there)          ├── users/
├── retrieval/                                   ├── chat-system/
├── user-manual-books/handbuch_daten/Ontologie/ontology.yaml
└── .dockerignore       (only for the container build of chat-system)
```

```bash
rsync -av --exclude .venv --exclude data --exclude .env --exclude out --exclude __pycache__ \
  retrieval users chat-system .dockerignore user@server:<base>/
```

**Do not ingest the repository's `out/remote-caas` on the server.** Those vectors were produced on the dev box with
`bge-m3`. They are 1024-dim like e5, so the dimension check passes, but they are incompatible with the e5 vectors
of the ZSD chunks on the server and kNN for CaaS would return noise. Use the run docling-graph wrote **on the
server** (same `DGS__EMBEDDING__MODEL` as the ZSD run there).

---

## 2. Phase 1: node up, ingest the CaaS book, verify

```bash
cd <base>/opensearch-index
make up                  # = make init (podman unshare chown on rootless podman) + compose up -d + scripts/wait_healthy.sh
make health              # curl --noproxy '*' …/_cluster/health  -> "status": "yellow" is the final state of a single node
.venv/bin/osi verify     # version, knn plugin true, 1024-dim round trip
.venv/bin/osi status     # expect: bhb-documents 1, BHB-PLT-0007 active
```

If the node does not come up: `WAIT_TIMEOUT=600 make wait`; the script prints the log tail and the known causes
(`vm.max_map_count`, `AccessDeniedException` → ownership, `memory is not locked` → `OPENSEARCH_MEMORY_LOCK=false`).
Details in `opensearch-index/DEPLOY.md` §5–§6.

### 2.1 Sanity-check the run folder before writing anything

```bash
ls -la <out>/<caas-run>/                       # response.json (canonical) — or meta.json + chunks.json (+ graph.json)
python3 - <<'EOF'
import json, sys
r = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "<out>/<caas-run>/response.json"))
print(r["document"]["name"], r["document"]["pages"], "pages")
print("chunks:", len(r["chunks"]), "dim:", len(r["chunks"][0]["embedding"]))
print("graph:", r["graph"]["meta"]["node_count"], "nodes", r["graph"]["meta"]["edge_count"], "edges")
print("degraded:", r["degraded"], "errors:", r["errors"])
EOF
```

Expected: `Betriebshandbuch_CaaS-Plattform.pdf`, 27 pages, ~120 chunks (count depends on the run), `dim: 1024`,
`degraded` all `false`, `errors: []`. If `degraded.graph` is true or the node count is tiny, the run is not worth
indexing: re-run docling-graph first.

Confirm the embedding model of that run is the one the node already holds. `osi status` prints the model recorded
for BHB-PLT-0007 (`OSI__EMBEDDING__MODEL` at ingest time, `intfloat/multilingual-e5-large` on the server); the
CaaS run must have been produced with the same `DGS__EMBEDDING__MODEL` in `docling-graph/.env`. The response file
records only the dimension, so this is a provenance check, not a computed one.

### 2.2 Ingest

```bash
.venv/bin/osi ingest <out>/<caas-run> --dry-run     # resolves doc_id, fingerprints the run, validates, prints the plan
.venv/bin/osi ingest <out>/<caas-run>               # writes chunks, nodes, document, manifest
.venv/bin/osi status
```

The document id is resolved from the file name through the ontology (`meta.documents[].file` →
`BHB-PLT-0001`). If the server's PDF has another file name, add `--doc-id BHB-PLT-0001`. Re-running the same
command is a no-op (same run fingerprint); a newer run of the same PDF replaces the CaaS records and sweeps stale
nodes. Other exit paths are listed in `opensearch-index/DEPLOY.md` §6 (`--replace`, `--force`, lock in progress).

Expected `osi status` afterwards:

| Field | Expect |
|---|---|
| `indices.bhb-documents` | 2 |
| `documents[BHB-PLT-0001].status` | `active`, `indexed.chunks` = chunk count of the run, `indexed.nodes` = node count |
| `cross_document_node_ids.count` | > 0 (60 on the dev box; the exact number depends on the LLM that extracted each book) |
| `attention` | `[]` |

### 2.3 Test queries (no model endpoint needed)

Identifiers, BM25, stored-vector kNN and node lookups run entirely inside OpenSearch:

```bash
# identifier channel: tickets, SOPs, firewall rules of the CaaS book (exact match on the `identifiers` field)
.venv/bin/osi search --identifier CAASUP-0338
.venv/bin/osi search --identifier SOP-CAAS-01
.venv/bin/osi search --identifier FW-CAAS-004

# BM25 with the German analyzer
.venv/bin/osi search --text "CaaS-Plattform Namespaces Mandanten" --k 5

# kNN with a stored CaaS vector: chunk ids are <sha256(pdf)[:12]>-NNNN; the same PDF gives the prefix fa9517fb84f3.
# If it is another file, take a chunk_id from a BM25 hit (--json) instead.
.venv/bin/osi search --knn-from-chunk fa9517fb84f3-0010 --k 3

# cross-book join: node ids are content-addressed (identity fields + class), so the same entity has the same id in
# both books. After the ingest these must list BOTH documents and their edges:
.venv/bin/osi search --node-id System_8c8c6e95949e6f73        # System "Vault"
.venv/bin/osi search --node-id Incident_9bee92d1caabf291      # Incident ZSDSUP-0247 (referenced in the CaaS book too)
.venv/bin/osi search --node-id Person_9fe33ad64c9f5686        # Marcel Ebert

# RRF fusion of several clauses through the bhb-rrf pipeline
.venv/bin/osi search --identifier ZSDSUP-0247 --identifier CAASUP-0351 --hybrid --k 5
```

What "loaded correctly" looks like: the identifier hits carry `doc_id: BHB-PLT-0001`; the kNN self-hit scores 1.0;
the node lookups show `documents: [BHB-PLT-0001, BHB-PLT-0007]`. If a node id is not found, the extraction on the
server normalised that identity differently: look the id up from a chunk (`osi search --identifier ZSDSUP-0247
--json` prints the chunk's `node_ids`) and query that one.

Optional, if the integration venv exists: `cd <base>/integration && ../opensearch-index/.venv/bin/python
cross_book_report.py` prints shared nodes, cross-book edges and the documented cycle Vault → CaaS-Plattform →
BAVD Issuing CA 3 → Vault, which needs both books.

---

## 3. Phase 2: retrieval module

```bash
cd <base>/retrieval
python3 -m venv .venv && .venv/bin/pip install -i "$PIP_INDEX_URL" -r requirements.txt     # -e ../opensearch-index + -e .[dev]
cp .env.example .env
```

In `.env`: comment the DEV BOX block, uncomment the REMOTE SERVER block, and set the real values:

| Key | Value |
|---|---|
| `RAG__OPENSEARCH__URL` | `http://localhost:9200` |
| `RAG__EMBEDDING__BASE_URL` / `MODEL` / `QUERY_PREFIX` | the tunnel, `intfloat/multilingual-e5-large`, `"query: "` (chunks were indexed with `"passage: "`) |
| `RAG__LLM__BASE_URL` / `MODEL` / `CONTEXT_LIMIT_TOKENS` | the tunnel, the served chat model, its context window |
| `RAG__ONTOLOGY__PATH` | absolute: `<base>/user-manual-books/handbuch_daten/Ontologie/ontology.yaml` |
| `RAG__LLM__MAX_TOKENS` | 4000 default; raise if answers end with `finish_reason=length` |

Never put `HTTP(S)_PROXY` in `.env`: every endpoint is loopback and the clients ignore the proxy environment.

```bash
# tunnels up, then:
curl -s --noproxy '*' http://localhost:11435/v1/models       # whatever port your tunnel uses

make test               # 104 unit tests, offline
make check              # aliases, indexed documents + their embedding model vs configured, embedding probe, LLM probe
make graph-stats        # in-memory union graph: 2 documents, shared node ids, edges (negative count), labels indexed
```

`make check` must show both documents with the configured embedding model and two green probes. Then the
retrieval itself (no model call unless `--answer`):

```bash
make ask Q="Was war bei CAASUP-0338?" ARGS="--no-graph"                   # identifier channel -> BHB-PLT-0001 chunks
make ask Q="Wer betreibt die CaaS-Plattform und wie eskaliere ich?"       # slow mode: facts + entity cards from CaaS
make ask Q="Was passiert, wenn Vault versiegelt ist?" ARGS="--show-context"   # cross-book: facts from both books
make ask Q="Was war bei ZSDSUP-0247?"                                     # incident referenced in both books
make ask Q="Wie backe ich einen Apfelkuchen?"                             # guardrail: weak evidence, no model call
make answer Q="Was passiert, wenn Vault versiegelt ist?"                  # with the chat model, streamed
make questions          # all 9 ground-truth questions, fast + slow -> out/questions/*.txt
```

Read the `Modus | Kanäle | Guardrail` lines and the `Quellen`: CaaS questions must cite `BHB-PLT-0001` pages, the
Vault question both books. Optional live suite: `RAG_INTEGRATION=1 make test-integration` (13 tests). One assertion
(`shared_node_ids >= 60`) was calibrated on the dev-box extractions; with another LLM on the server a lower count
is not a defect, counts are never comparable across LLMs.

---

## 4. Phase 3: users module

Pure Python, no services. Either a tiny venv of its own:

```bash
cd <base>/users
python3 -m venv .venv && .venv/bin/pip install -i "$PIP_INDEX_URL" -e ".[dev]"
make check              # ruff + 39 tests + `python -m rag_users`: directory, group rules, who USERS__* resolves to
```

or, leaner, from the chat-system venv once it exists (phase 4): `cd <base>/chat-system && .venv/bin/python -m
pytest ../users/tests -q && .venv/bin/python -m rag_users`.

Mock directory used by the tests below: `dev`, `otto.ops` (bavd-ops: 10 messages/day, 10 turns), `rita.read`
(bavd-readonly: 5/day, 5 turns, **only BHB-PLT-0007**), `anna.admin` (admin + bavd-ops: 100/day).

---

## 5. Phase 4: chat-system (venv, SQLite, then the UI)

```bash
cd <base>/chat-system
python3 -m venv .venv && .venv/bin/pip install -i "$PIP_INDEX_URL" -r requirements.txt   # -e ../opensearch-index ../users ../retrieval .[dev]
cp .env.example .env
```

`.env`: comment the DEV BOX block, uncomment the REMOTE SERVER block. For this test round:

| Key | Value for the test | Later |
|---|---|---|
| `CHAT__DB__URL` | `sqlite:///./data/chat.db` (no Postgres container) | Postgres via `make db-up` / `make up-enterprise` |
| `CHAT__UI__ALLOW_USER_SWITCH` | `true` (sidebar selectbox to test rita.read etc.) | `false` |
| `RAG__*` | identical to `retrieval/.env` (copy the block) | |
| `RAG__ONTOLOGY__PATH` | absolute host path (the `/ontology/...` value is for the container) | |
| `USERS__ADAPTER` / `USERS__DEV_USER` | `env` / `dev` | `header` behind oauth2-proxy |

```bash
make test && make test-ui                 # 49 unit + 4 AppTest, offline
make doctor                               # db, opensearch (2 manuals + embedding model), llm probe, resolved user, prompt budget
make db-init                              # alembic upgrade head -> data/chat.db
make ask Q="Was war bei CAASUP-0338?" ARGS="--no-graph --user otto.ops"
make ask Q="Was passiert, wenn Vault versiegelt ist?" ARGS="--user otto.ops"
make ask Q="Was war bei CAASUP-0338?" ARGS="--user rita.read"     # ZSD-only user: CaaS never reaches retrieval -> exit 2, no CaaS citation
make smoke                                # 6 questions of scripts/smoke_questions.txt -> out/smoke/<n>.txt
```

Optional live suite: `CHAT_INTEGRATION=1 make test-integration` (8 tests, temporary SQLite; needs the tunnels).

### 5.1 The UI

```bash
make run                                  # streamlit on 127.0.0.1:8501
# laptop:
ssh -N -L 8501:localhost:8501 user@server   # then open http://127.0.0.1:8501
```

Checklist in the browser:

1. Sidebar: user selectbox (dev, otto.ops, rita.read, anna.admin); the book multiselect shows two books, for
   `rita.read` only `BHB-PLT-0007`.
2. Ask `Was war bei CAASUP-0338?` as `otto.ops` → answer with `[BHB-PLT-0001 S. x]` citations and a Quellen list.
3. Toggle `Graph-Modus (langsam)` off/on, open Diagnostik: channels, guardrail verdict, `doc_ids`, latencies.
4. Ask `Wie backe ich einen Apfelkuchen?` → "Dazu steht nichts in den Handbüchern." with no sources.
5. As `rita.read` send 5 messages → the 6th is refused with the daily-cap message (bavd-readonly = 5/day);
   a 6th turn in one conversation is refused with the turn-cap message.
6. Reload the page: conversations persist (SQLite `data/chat.db`).

Container instead of venv (`make up`, host networking, SQLite volume) is the same `.env`; see `chat-system/DEPLOY.md`
§4 B/C. Not needed for this round and costs a build behind the proxy.

---

## 6. End state

Running: the OpenSearch container, the SSH tunnels, one `make run` process. Everything else down:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}'      # only opensearch-index-opensearch-1
cd <base>/docling-graph && docker compose --profile local down     # if still up
cd <base>/chat-system && make db-down                              # only if Postgres was started
free -h
```

Restart after a reboot: `cd <base>/opensearch-index && make up`, tunnels, `cd <base>/chat-system && make run`
(`restart: unless-stopped` survives reboots under rootless podman only with a generated systemd unit, see
`opensearch-index/DEPLOY.md` §5). Data survives `make down`; only `make reset` destroys the data directory.

---

## 7. Quick fault table

| Symptom | Where | Fix |
|---|---|---|
| `invalid embeddings … dim 768 != 1024` on ingest | osi | the run was embedded with another model; fix `docling-graph/.env` and re-run docling-graph |
| `cannot determine the document id` | osi | `--doc-id BHB-PLT-0001` |
| `an ingest of X is in progress since …` | osi | previous run crashed < lock TTL ago → wait or `--force` |
| `make check`: embedding model mismatch | retrieval | `RAG__EMBEDDING__MODEL` / `QUERY_PREFIX` differ from `bhb-documents.embedding_model` |
| every CaaS question hits the guardrail although BM25 finds it | retrieval | kNN vectors of the CaaS run incompatible (other embedding model) → re-ingest a run made with the node's model |
| `prompt estimate … exceeds the model context limit` | retrieval / chat | `RAG__LLM__CONTEXT_LIMIT_TOKENS`, `RAG__RETRIEVAL__CONTEXT_TOKEN_BUDGET=2500`, `CHAT__RETRIEVAL__K=4` |
| answers cut mid-sentence | chat | `RAG__LLM__MAX_TOKENS` up (reasoning models spend ~1300 tokens thinking) |
| `chat-doctor`: `db … has no schema yet` | chat | `make db-init` |
| UI blank / slow first load | chat | first page load builds the in-memory graph (~1 s per manual); `make health` |

Full tables: `opensearch-index/DEPLOY.md` §6, `chat-system/DEPLOY.md` §6.
