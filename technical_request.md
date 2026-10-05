# Technical Request — Deployment

What has to be provisioned to run the Betriebshandbuch assistant (RAG over IT operations manuals).
Written for the deployment team. Hardware figures marked *measured* come from runs on the development
machine (12 vCPU / 23 GB); see `PRESENTATION.md` for the measurement method.

**Deployment model:** every component is a **long-running container talking HTTP**. No container starts
another container, no scheduler is required, no access to a container/orchestrator API is needed.
The handover artefact is a compose file per environment; the translation to Kubernetes Deployments,
Services and PVCs is 1:1 and is left to the platform team.

Status 2026-09-16: prototype complete and verified on three manuals. Target corpus 30–40 manuals of
5–10 pages each.

---

## 1. Lifecycle

```
  ┌── ASK (every question, ~13 s) ────────────────────────────────────────────┐
  │                                                                           │
  │  user ─► Ingress + IAM ─► chat  ─► OpenSearch   (search: 4 channels)      │
  │          (adds identity     │    ─► Embedding    (1 vector per question)   │
  │           headers)          │    ─► LLM          (writes the answer)       │
  │                             └─► answer with citations, streamed            │
  └───────────────────────────────────────────────────────────────────────────┘

  ┌── INGEST (once per manual, 2–5 min for 5–10 pages) ───────────────────────┐
  │                                                                           │
  │  PDF ─► docling-graph  ─► VLM / Embedding / LLM   (parse, chunk, extract) │
  │            │                                                              │
  │            └─► run directory on shared volume                             │
  │                      │                                                    │
  │                      └─► osi indexer ─► OpenSearch                        │
  │                                          manifest: indexing → active      │
  │                                                     │                     │
  │  chat polls the manifest ◄───────────────────────────┘                    │
  │  on "active": document list refreshed, in-memory graph reloaded (no restart)│
  └───────────────────────────────────────────────────────────────────────────┘
```

Ask and Ingest share only OpenSearch. Ingest is **not** on the interactive path: if docling-graph is
down, the chat keeps answering from what is already indexed.

---

## 2. Runtime units we deliver

| Unit | Image | Module(s) | Mode | Hardware (request / limit / measured) | Storage | Access |
|---|---|---|---|---|---|---|
| **chat** | `chat-system:<ver>` · 952 MB | `chat_system` + `rag_retrieval` + `rag_users` (in-process libraries) | always on, **1 replica** | 250m / 1 CPU · 512Mi / 1Gi · *measured 92 MB* | **PVC 10 GB** (SQLite) | **end user**, through Ingress + IAM headers |
| **dgs** (ingest service) | `dgs:<ver>` · 6.35 GB | `docling_graph_service` | always on, 1 replica, idle most of the time | 1 / 8 CPU · 2Gi / 12Gi · *measured 1.5 GB idle, 5.0 GB peak, 4.5–7 cores* | shared volume for outputs | application only, cluster-internal |
| **indexer** | `osi:<ver>` · 283 MB | `opensearch_index` | **runs once per manual**, then exits | 250m / 1 CPU · 512Mi / 1Gi · *measured < 300 MB, seconds* | reads the shared volume | application only, cluster-internal |

Notes for the platform team:

- **chat runs as a single instance**, because the conversation database is **SQLite** on its own volume
  (§6). Three consequences: the volume is **RWO**; the deployment strategy must be **`Recreate`, not
  `RollingUpdate`** (two pods must never hold the file, and with RWO a rolling update deadlocks anyway);
  and there is **no HA** — a rollout or a node failure means a short outage. Acceptable for an internal
  tool at this size; switching to Postgres later is one environment variable (§7) plus more replicas.
- **chat** serves a WebSocket per session (Streamlit). With one replica session affinity is moot, but
  configure it anyway so scaling out later does not break running sessions. The limit of 10 concurrent
  answers is per process and is therefore the system limit; the daily message quota lives in the database.
- Database schema migrations run **automatically at start-up** (`alembic upgrade head`). With a single
  instance this is safe by construction.
- **dgs** is deliberately *burstable*: it idles at ~1.5 GB and needs 8 CPU / 12 Gi only while processing a
  manual. Requests are set to the idle footprint, limits to the peak.
- **indexer** is the only unit that is not long-running. It is started by an operator (§9) and exits in
  seconds. It never runs concurrently with itself for the same manual — the manifest document in
  OpenSearch is the lock.

**If the units are run under Kubernetes**, two properties of the images matter:

- All three images run **non-root as uid 10001**, but declare the user **by name** (`USER chat` / `osi` /
  `dgs`). Under a `restricted` Pod Security policy, set **`runAsUser: 10001` explicitly** next to
  `runAsNonRoot: true` — otherwise the kubelet cannot verify the named user and the container does not
  start. Everything else `restricted` requires (`seccompProfile: RuntimeDefault`,
  `allowPrivilegeEscalation: false`, drop `ALL` capabilities) is a pod-spec field with no obstacle on the
  image side.
- The **ingest unit needs 8 CPU / 12 Gi at its limit**, which is above a typical namespace default. If a
  ResourceQuota or LimitRange caps it lower, processing a manual will be throttled or killed — please
  confirm the namespace allows it.

---

## 3. Platform services required (provided by the enterprise, not by us)

| Service | Required version / feature | Why we need it | Sizing | Access |
|---|---|---|---|---|
| **OpenSearch** | **≥ 2.19**, verified on **3.8.0** · **k-NN plugin mandatory** | the only data store: text chunks, 1024-dim vectors, graph nodes, the graph blob, the ingest manifest | data < 100 MB at 40 manuals; 2 CPU / 4 Gi, JVM heap 2–4 GB, 20 GB disk | one technical account for the app (read), one for the indexer (write) |
| **LLM endpoint** | **OpenAI-compatible** `/v1/chat/completions` **with streaming** · **gemma4** — see §3.1 | writes the answer; extracts the graph during ingest | ≥ 32k context (128k recommended), ≥ 24B dense / ≥ 30B MoE class, German; 3–5 parallel streams, ≥ 20–30 tok/s per stream; GPU (48 GB class) | API key or mTLS, application identity |
| **Embedding endpoint** | **OpenAI-compatible** `/v1/embeddings` · **`intfloat/multilingual-e5-large`** (1024 dim, fixed) — see §3.1 | one vector per chunk at ingest, one per question | 2 CPU / 4 GB is sufficient for query load; GPU only for bulk ingest | API key, application identity |
| **Ingress + IAM** | authenticating reverse proxy (oauth2-proxy pattern, here: PGA) injecting `X-Forwarded-User`, `-Email`, `-Groups` | the application reads only headers — no OIDC client, no token handling | — | **end user** |
| ~~Postgres~~ | — | **not used.** The conversation history is SQLite on the chat unit's volume. Postgres 16 remains supported as a later option (§7) if HA or several replicas are required | — | — |
| **Shared volume** | RWX (ReadWriteMany) if dgs and indexer run on different nodes | PDF in, run directory out | 5 GB | — |

**OpenSearch details the DBA will ask for:**

```
indices (4, each behind an alias)   bhb-chunks · bhb-nodes · bhb-documents · bhb-manifest
mappings                           dynamic: strict, 1 shard, 1 replica
vector field                       knn_vector, 1024 dim, HNSW, engine lucene, m=16, ef_construction=128
text analysis                      built-in only: german stopwords, german_normalization, light_german stemmer
indexer account rights             create index + alias, write, refresh, delete_by_query, read
app account rights                 search, msearch, mget on bhb-*
NOT required                       Dashboards · ML plugin · server-side RRF pipeline (fusion is client-side)
```

### 3.1 Models — decided

**Two models operate the whole system.** One LLM serves both the chat and the graph extraction; one
embedding model serves both the questions and the chunks. This is a deliberate decision: fewer endpoints to
secure, one model to benchmark, no compatibility matrix.

| Role | Model — **fixed** | Used by | Load |
|---|---|---|---|
| **LLM** — answer + extraction | **gemma4** (test server: tag `gemma4:26b` via Ollama, served context 262 144) | chat: 1 call per question + a short rewrite call · dgs: many schema-bound calls per manual | interactive 3–5 parallel streams · batch 4–6 min per manual |
| **Embedding** | **`intfloat/multilingual-e5-large`** — 1024 dim, prefixes `passage: ` (chunks) / `query: ` (questions) | chat: 1 call per question · dgs: batches of 64 per manual | 200–270 ms per question (measured) · 1.5–2.5 min per manual |
| **Vision (VLM)** *(optional)* | any chat model with image input — **off on the test server** | dgs: 1 call per figure | ~15 s per manual |

#### The LLM — what must hold

| # | Requirement | Why | Consequence if missing |
|---|---|---|---|
| 1 | **OpenAI-compatible** `/v1/chat/completions` | the only interface the system speaks | does not work at all |
| 2 | **Token streaming** | the answer appears while it is written; a 4 000-token answer otherwise takes ~60 s of blank screen | unusable interactively |
| 3 | **Structured output / JSON schema** (`structured_output: true`) | the ontology is enforced *as a schema*, not requested in prose — this is what keeps extraction inside the 26 classes and 32 relations | no knowledge graph; only text search remains |
| 4 | **≥ 32k context**, 128k recommended | system prompt ~0.8k + ecosystem 0.4k + retrieved context 6k + pasted material ≤ 3k + history ~4k + answer 4k | prompts are refused; long conversations break |
| 5 | **~8 192 output tokens per call** for extraction | one schema-filled object per document slice | truncated extraction, degraded graph |
| 6 | **Solid German** — technical prose, negations, verbatim identifiers, tables | the corpus, the prompts and every answer are German | wrong or invented answers |
| 7 | **≥ 24B dense / ≥ 30B MoE class**, instruction-tuned | reference point verified in the prototype | quality below what was demonstrated |
| 8 | Thinking mode **switchable off** | reasoning tokens are taken from the answer budget; the 200-token rewrite call truncates otherwise | truncated answers, broken follow-up questions |

Requirements 1–6 are **hard**. Requirement 7 names a reference point, not a fixed product: **gemma4 is the
verified reference; a larger model (120B-class open weights) is acceptable and preferable if GPU capacity
allows.** Requirement 3 is the one to test first on any offered endpoint — it is the least commonly supported.

Sizing (estimate): a 26–30B model at 4-bit ≈ 16–20 GB weights plus KV cache → **one GPU of the 48 GB class**
for 32k context and 4 parallel streams. CPU inference is not viable interactively.

**One endpoint for both roles** is the decision, with one operational consequence: a batch ingest competes
with interactive users. Mitigations in increasing order of cost — run ingests outside office hours, keep
`DGS__LLM__PARALLEL_WORKERS` at 2, or split the endpoints later (`RAG__LLM__*` and `DGS__LLM__*` are already
separate settings, so this is configuration, not rework).

#### The embedding model — one decision, for good

Chunks and questions must be embedded by **the same model with the same prefix**, otherwise questions and
documents live in different vector spaces and the k-NN channel returns near-noise.

> ⚠ **The index records the embedding model from an indexer setting (`OSI__EMBEDDING__MODEL`), not from the
> data** — a processing run does not name the model that produced its vectors. A wrong setting therefore
> yields a silently mislabelled index: the query-side check compares two configuration strings and stays
> quiet. `bge-m3` and `multilingual-e5-large` are **both 1024-dimensional**, so no dimension check catches it
> either. Set `OSI__EMBEDDING__MODEL` and `DGS__EMBEDDING__TEXT_PREFIX` correctly at ingest, and verify once
> empirically with `opensearch-index/scripts/which_embedding.py` (re-embeds an indexed chunk and compares by
> cosine; 1.0 identifies the model).

The three manuals indexed during the prototype were embedded with `bge-m3` and **are re-indexed** with
`multilingual-e5-large` before go-live, so the corpus is homogeneous. Re-processing the PDFs is required
because the vectors themselves change.

**Deployment knobs for the models:**

```
RAG__LLM__MODEL / BASE_URL / API_KEY              chat        ┐ same endpoint,
DGS__LLM__MODEL / BASE_URL / API_KEY              extraction  ┘ separate settings

RAG__EMBEDDING__MODEL=intfloat/multilingual-e5-large   RAG__EMBEDDING__QUERY_PREFIX="query: "
DGS__EMBEDDING__MODEL=intfloat/multilingual-e5-large   DGS__EMBEDDING__TEXT_PREFIX="passage: "
OSI__EMBEDDING__MODEL=intfloat/multilingual-e5-large   OSI__EMBEDDING__TEXT_PREFIX="passage: "
DGS__VLM__ENABLED=false                                switch figure description off

RAG__LLM__MAX_TOKENS=4000                         answer budget
RAG__LLM__CONTEXT_LIMIT_TOKENS=32000              prompt guard (refuses oversized prompts)
DGS__LLM__CONTEXT_LIMIT=128000  DGS__LLM__MAX_OUTPUT_TOKENS=8192

# thinking models spend part of the output budget on reasoning — switch it off:
RAG__LLM__EXTRA_BODY={"think": false}                                     # Ollama / gemma4
RAG__LLM__EXTRA_BODY={"chat_template_kwargs": {"enable_thinking": false}} # vLLM
```

On Ollama the served context is set when the model is loaded (262 144 for `gemma4:26b` on the test server);
**never send `num_ctx` per request** — it overrides the served value downwards.

---

## 4. Stack per unit

All Python images are built from the same Artifactory index; Python **3.12** throughout (verified 3.12.3).
The pinned dependency sets are in the repository; the direct dependencies are listed here because they
determine the licences and the mirror content.

### chat — `chat-system:<ver>`

```
base image     python:3.12-slim
entrypoint     streamlit run app.py          port 8501       health GET /_stcore/health
pinned set     chat-system/requirements.txt  (installs the sibling modules editable)
```

| Direct dependency | Constraint | Verified |
|---|---|---|
| streamlit | >=1.50,<2 | 1.63.0 |
| sqlalchemy | >=2.0.30,<3 | 2.0.52 |
| alembic | >=1.13,<2 | 1.19.1 |
| psycopg[binary] | >=3.2,<4 | 3.3.5 |
| opensearch-py | >=3.2,<4 | 3.2.0 |
| httpx | >=0.27 | 0.28.1 |
| pydantic / pydantic-settings | >=2.7 / >=2.4 | 2.13.5 / 2.15.0 |
| typer | >=0.12 | 0.27.2 |
| pyyaml | >=6 | 6.0.3 |

The image contains four packages: `chat_system`, `rag_retrieval`, `rag_users`, `opensearch_index`.
`rag_retrieval` and `rag_users` are **libraries inside this process**, not separate services.

### dgs — `dgs:<ver>`

```
base image     python:3.12                   (the full image ships libGL/glib — no apt step needed)
entrypoint     uvicorn docling_graph_service.api:app     port 8080     health GET /healthz
pinned set     docling-graph/requirements.txt
models         docling layout + TableFormer + EasyOCR (de, en) are BAKED INTO THE IMAGE
               (offline operation, HF_HUB_OFFLINE=1 — no model download at runtime)
```

| Direct dependency | Constraint | Verified |
|---|---|---|
| docling[easyocr] | >=2.123,<3 | 2.123.0 (runs produced with 2.124.0) |
| docling-graph | >=1.9.1,<2 | 1.9.1 |
| docling-core / docling-parse / docling-ibm-models | transitive | 2.92.0 / 7.16.0 / 3.14.0 |
| torch | transitive | **2.13.0+cpu** (CPU wheel — see build args) |
| transformers | >=4.44 | 5.16.1 |
| easyocr | transitive | 1.7.2 |
| tokenizers / tiktoken / numpy | transitive | 0.23.1 / 0.12.0 / 2.5.2 |
| fastapi / uvicorn[standard] | >=0.115 / >=0.30 | 0.141.1 / 0.52.4 |
| httpx · pydantic · pydantic-settings · pyyaml · typer · anyio | as above | — |

**This unit is the reason the image is 6.35 GB** (torch + docling models + EasyOCR). It performs no GPU
work — everything is CPU.

### indexer — `osi:<ver>`

```
base image     python:3.12-slim
entrypoint     osi                           (CLI: bootstrap | ingest | status | verify | search | delete)
pinned set     opensearch-index/requirements.txt
```

| Direct dependency | Constraint | Verified |
|---|---|---|
| opensearch-py | >=3.2,<4 | 3.2.0 |
| pydantic / pydantic-settings | >=2.7 / >=2.4 | 2.13.5 / 2.15.0 |
| pyyaml | >=6 | 6.0.3 |
| typer | >=0.12 | 0.27.2 |

### Image build inputs (if the images are built on site)

```
BASE_IMAGE          registry mirror path for python:3.12-slim / python:3.12
PIP_INDEX_URL       Artifactory PyPI index            PIP_TRUSTED_HOST   its host
PIP_EXTRA_INDEX_URL PyTorch CPU index (dgs only) — if unavailable, torch comes from the main index as a
                    CUDA wheel that still runs on CPU, and the image grows to ~7–8 GB
HTTP_PROXY / HTTPS_PROXY / NO_PROXY   in both upper and lower case (apt honours only lower case)
```

Proxy variables are **build arguments only** — they must never be set in the runtime environment.

---

## 5. Communication matrix

All connections are outbound from the unit named in *Source*; the only inbound connection from outside
the platform is the Ingress.

| # | Source | Target | Protocol / Port | Purpose | Auth | Frequency |
|---|---|---|---|---|---|---|
| 1 | Browser | Ingress | HTTPS 443 | the chat UI, WebSocket upgrade | end user (IAM) | per session |
| 2 | Ingress | chat | HTTP 8501 | request forwarding incl. identity headers | header injection, session affinity | per request |
| 3 | chat | OpenSearch | HTTPS 9200 | `msearch`, `mget`, graph blob at start-up | technical account (read) | per question |
| 4 | chat | Embedding endpoint | HTTPS | 1 vector per question | API key | per question |
| 5 | chat | LLM endpoint | HTTPS, **streaming** | writes the answer | API key | per question |
| 7 | chat | dgs *(only with self-service upload, §10)* | HTTP 8080 | `POST /v1/process` | none (cluster-internal) | per upload |
| 8 | dgs | LLM endpoint | HTTPS | graph extraction | API key | per manual |
| 9 | dgs | VLM endpoint *(same host as 8 by default)* | HTTPS | figure descriptions | API key | per manual |
| 10 | dgs | Embedding endpoint | HTTPS | chunk vectors, batches of 64 | API key | per manual |
| 11 | indexer | OpenSearch | HTTPS 9200 | bulk write, refresh, delete_by_query, manifest | technical account (write) | per manual |

Long-running connections: **5** (answer streaming, up to ~120 s) and **8** (extraction, up to ~300 s per
call). Idle timeouts on proxies between these hops must accommodate that.

### 5.1 What content leaves the platform

Relevant if the model endpoints are not operated in-house — the manuals describe the agency's central
security services, so the classification of this traffic is a decision for the security officer, not a
technical detail.

| Flow | What is transmitted | When |
|---|---|---|
| **8** dgs → LLM | **the full text of a manual**, slice by slice, as extraction input | once per manual, at ingest |
| **9** dgs → VLM | the page images containing figures | once per manual (omitted entirely if the VLM is off) |
| **10** dgs → Embedding | the full text of a manual, in batches | once per manual |
| **5** chat → LLM | the user's question, the retrieved passages and graph facts (≤ ~6 000 tokens), plus the last turns of the conversation | per question |
| **4** chat → Embedding | the user's question only | per question |

No user identity, e-mail address or group membership is ever sent to a model endpoint. Conversation
history stays in the chat unit's database and is transmitted only back to the model as prompt context for
the same user's own conversation.

**Consequence:** if the LLM endpoint is a shared or external service, the manual content and the users'
questions leave the application's trust zone. An in-house endpoint removes the question entirely, which is
how the prototype was operated (models reachable only on the internal network).

---

## 6. Storage and data protection

| Data | Location | Size (40 manuals) | Backup |
|---|---|---|---|
| Index (chunks, vectors, nodes, graph, manifest) | OpenSearch | < 100 MB | **not required** — reproducible from the PDFs |
| Run directories (`response.json`, markdown) | shared volume | 2–3 MB per manual, ~5 GB with margin | optional — saves re-processing (2–5 min per manual) |
| Conversations, messages, daily counters | **SQLite** on the chat unit's PVC (WAL mode) | **~24 KB per message** measured → ~12 MB/day at full quota (50 users × 10 messages), ~2.6 GB/year → **PVC 10 GB** | per the customer's retention policy — snapshot the PVC; do **not** copy the `.db` file while the pod runs (WAL) |
| Source PDFs | shared volume or a document store | ~250 MB | **the actual source of truth** |
| Ontology (`ontology.yaml`) | ConfigMap or read-only volume, mounted into dgs and indexer | 40 KB | in version control |

**No backup concept is needed for the index.** Source of truth are the PDFs and the ontology; if the
index is lost, the manuals are re-processed and re-indexed. Ingest is idempotent: identical output is a
no-op, a new extraction replaces that manual as a whole, and an aborted run leaves a superset, never a
gap.

---

## 7. Configuration and secrets

Configuration is environment variables. **Every value has a default in the image**; the lists below are what
must be set for a real deployment. The authoritative, maintained templates are the three `.env.example`
files in the repository (`chat-system/`, `docling-graph/`, `opensearch-index/`) — they carry a commented
block per environment and are kept in sync with the code.

```bash
# ---- chat -------------------------------------------------------------------
RAG__OPENSEARCH__URL=https://opensearch.intern:9200
RAG__OPENSEARCH__USERNAME=…                RAG__OPENSEARCH__PASSWORD=…
RAG__EMBEDDING__BASE_URL=…/v1              RAG__EMBEDDING__API_KEY=…
RAG__EMBEDDING__MODEL=intfloat/multilingual-e5-large   RAG__EMBEDDING__QUERY_PREFIX="query: "
RAG__LLM__BASE_URL=…/v1                    RAG__LLM__API_KEY=…
RAG__LLM__MODEL=gemma4:26b
RAG__ONTOLOGY__PATH=/ontology/ontology.yaml
CHAT__DB__URL=sqlite:////app/chat-system/data/chat.db   # the mounted PVC (4 slashes = absolute path)
USERS__ADAPTER=header                      # production: identity from the ingress headers

# ---- dgs (ingest service) ---------------------------------------------------
DGS__LLM__BASE_URL=…/v1                    DGS__LLM__API_KEY=…
DGS__LLM__MODEL=gemma4:26b
DGS__EMBEDDING__MODEL=intfloat/multilingual-e5-large   DGS__EMBEDDING__TEXT_PREFIX="passage: "
DGS__VLM__ENABLED=false
DGS__GRAPH__DEFAULT_ONTOLOGY_PATH=/ontology/ontology.yaml

# ---- indexer ----------------------------------------------------------------
OSI__OPENSEARCH__URL=https://opensearch.intern:9200
OSI__OPENSEARCH__USERNAME=…                OSI__OPENSEARCH__PASSWORD=…
OSI__EMBEDDING__MODEL=intfloat/multilingual-e5-large    OSI__EMBEDDING__TEXT_PREFIX="passage: "
OSI__ONTOLOGY__PATH=/ontology/ontology.yaml
```

**Secrets** — these belong in a Secret or vault, never in an image or a ConfigMap:

```
RAG__LLM__API_KEY          RAG__EMBEDDING__API_KEY          DGS__LLM__API_KEY   DGS__VLM__API_KEY
RAG__OPENSEARCH__PASSWORD  OSI__OPENSEARCH__PASSWORD
```

Two properties worth knowing:

- Settings are read **once at process start**. There is no hot reload — a configuration change requires a
  restart (rollout) of the unit.
- **Proxy variables must never be set at runtime.** `HTTP_PROXY` / `HTTPS_PROXY` are build arguments only;
  every endpoint is reached directly, and the HTTP clients deliberately ignore the proxy environment. A
  proxy in the runtime environment breaks the long-running extraction and streaming calls.

---

## 8. Identity and access

| Layer | State | What is needed |
|---|---|---|
| Authentication | **provided by the platform.** The application reads `X-Forwarded-User`, `-Email`, `-Groups` and holds no OIDC client, no tokens, no session store. Header names are configurable. | the PGA contract: routing, which claim carries the groups, the group naming convention |
| Authorisation (policy) | **mock, structurally complete.** Groups map to: messages per day, turns per conversation, and **which manuals a group may read**. The manual filter is pushed *into* the search (including the k-NN clause), not applied to the display — it is a real tenancy boundary. | the group → limit mapping. **Undefined, and a decision rather than a task.** |
| User directory | **mock** (4 hard-coded users). The header adapter never consults it; with a real IdP it simply becomes unused. | nothing — it disappears on its own |
| Quota enforcement | real: counters live in the database, so a second browser tab or a new session cannot reset them | the numeric limits depend on the LLM contract |
| Technical accounts | OpenSearch read (chat) and write (indexer); API keys for LLM and embedding | issue accounts and keys |

The mock policy shipped today (`admin` 100/20/all · `bavd-ops` 10/10/all · `bavd-readonly` 5/5/ZSD only)
is placeholder data and is expected to be replaced by real group names.

### 8.1 The trust boundary — two hard requirements

The application **trusts the identity headers unconditionally**: there is no signature and no shared secret.
This is the intended design behind an authenticating proxy, and it makes two things mandatory.

> **R1 — the chat unit must be reachable only through the authenticating ingress.**
> Anyone who can open its port directly can set `X-Forwarded-User` themselves and act as any user,
> including a group that may read every manual. Enforce by network placement, NetworkPolicy or service
> mesh — whichever is standard on the platform.
>
> **R2 — the ingress must strip inbound `X-Forwarded-*` headers before injecting its own.**
> An ingress that *appends* instead of *replacing* lets a client smuggle its own identity through it. This
> is the classic misconfiguration of this pattern and it is silent when wrong.

**Two settings must be correct in production**, and they are verifiable in the running UI:

```
USERS__ADAPTER=header                 # identity from the ingress, not from the mock directory
CHAT__UI__ALLOW_USER_SWITCH=false     # the dev user selector
```

The selector appears only when `allow_user_switch` **and** `adapter == "env"` are both set, so either value
alone closes it — but set both. **Acceptance check: the sidebar must show no user selector, and the
displayed user must be the logged-in person.**

### 8.2 What the application deliberately does not have

Useful for the security review, because it bounds the attack surface:

- **no administrative interface** — limits, groups and the manual filter cannot be changed from the UI by
  anyone, at any privilege level; they come from configuration and the ingress headers
- **no local accounts, no passwords, no password reset, no session store** — the identity lives entirely in
  the request headers, so there is no credential to steal from the application
- **no outbound user data beyond the model calls** documented in §5 — see the data-flow note there
- **no write path to OpenSearch from the chat unit** — its account needs read rights only; only the
  indexer writes

---

## 9. Getting manuals into the system

Ingest is a **two-step operator action**, not a scheduled service:

```
PDF ──► dgs (process)  ──►  run directory on the work volume  ──►  indexer (ingest)  ──►  OpenSearch
        minutes                 2–3 MB per manual                     seconds
```

What this means for the deployment:

- **`osi bootstrap` must run once before the first ingest.** It creates the four indices and their aliases.
  Without it everything deploys correctly and nothing works.
- **The indexer must be startable on demand** — a one-shot container with its environment (§7) and the work
  volume mounted. Whether that is a `compose run`, a `kubectl run` or a Job template is the platform team's
  choice; the application does not start it itself.
- **dgs and the indexer share the work volume** — dgs writes the run directory, the indexer reads it. If the
  two can land on different nodes, the volume must be **RWX**.
- **No restart is needed after an ingest.** The chat notices a newly indexed manual by itself within about
  five minutes (document list and in-memory graph refresh on their own).

The operating procedure itself — the commands, the document-id rule, the checks with `osi status` and
`osi verify` — belongs to whoever ingests manuals and is documented in the repository
([`REMOTE-RUNBOOK.md`](REMOTE-RUNBOOK.md)), not here.

---

## 10. Open points — decisions required

| # | Topic | Decision needed |
|---|---|---|
| 1 | **PGA contract** | routing, group claim, group naming convention |
| 2 | **Group → policy mapping** | messages per day, turns per conversation, manuals per group |
| 3 | **LLM provision** | model, context window, quota, GPU capacity — the limits in 2 depend on this. In use: `gemma4:26b`; must support streaming **and** structured output (§3.1) |
| 3a | ~~Embedding model~~ **decided** | `intfloat/multilingual-e5-large`. The three prototype manuals are re-processed and re-indexed before go-live (§3.1) |
| 3b | **Vision model** | figure descriptions on or off — off on the test server, text and tables are unaffected |
| 4 | **OpenSearch tenancy** | own cluster or index prefix on an existing one; technical accounts |
| 5 | ~~Conversation storage~~ **decided** | **SQLite** on the chat unit's PVC → one replica, `Recreate` strategy, no HA (§2). Postgres stays available as a later switch if HA becomes a requirement |
| 6 | **Self-service upload** | if users are to upload manuals from the chat, the chat needs either a background worker or an operator-triggered process. Today ingest is an operator action (§9). **Scope decision, not a technical obstacle.** |

---

## Appendix — summary for capacity planning

```
Continuous operation          ~1.25 CPU / 2.5 GB       chat (1×) + dgs idle
Ingest peak                   +8 CPU / 12 GB           per manual, 2–5 min, plannable
OpenSearch                     2 CPU / 4 GB, 20 GB disk
LLM  answer + extraction       GPU, 48 GB class (external, shared)   gemma4, ≥32k context, streaming + JSON schema
Embedding                      2 CPU / 4 GB (external, shared)        multilingual-e5-large, 1024 dim, passage:/query:
VLM (optional)                 same endpoint as the LLM               off on the test server

Storage total                 ~40 GB   (index < 100 MB · runs 5 GB · PDFs 250 MB · SQLite PVC 10 GB · margin)
Initial load of 40 manuals    2–3 hours, parallelisable, one-time
```
