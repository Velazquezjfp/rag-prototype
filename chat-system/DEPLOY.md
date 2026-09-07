# Deploying chat-system on a remote server

Goal: the same chat UI on your server (CentOS/RHEL, rootless podman behind the `docker` alias, SELinux enforcing,
internet only through a proxy, Artifactory for PyPI and images) next to the OpenSearch node of `opensearch-index`,
with the model endpoints reached through SSH tunnels on the host loopback. Verified locally on 2026-09-04 (Docker,
`python:3.12-slim`, `postgres:16-alpine`); the remote steps are the same commands with other values in `.env`.

## 0. What it needs from the outside

| Need | Local | Remote |
|---|---|---|
| OpenSearch with the manuals indexed | `opensearch-index` node on 127.0.0.1:9200 | same host, same port (`make up` there first) |
| Embedding + chat endpoints | LiteLLM :4000 | vLLM / TEI through `ssh -L 11435:…` tunnels on the loopback (`RAG__*_BASE_URL`) |
| Ontology file | `../user-manual-books/…/ontology.yaml` | `/srv/rag/user-manual-books/handbuch_daten/Ontologie` (mounted read-only) |
| Database | SQLite in a volume | Postgres 16 in compose (profile `postgres`) — or SQLite for a single instance |
| Images | Docker Hub | `python:3.12-slim` + `postgres:16-alpine` from the registry mirror (`BASE_IMAGE`, `POSTGRES_IMAGE`) |
| Python packages (image build) | PyPI | Artifactory (`PIP_INDEX_URL`, `PIP_TRUSTED_HOST`) |

Nothing else: no GPU, no model files, no internet at run time. The UI binds to `127.0.0.1:8501` by default — reach it
through `ssh -L 8501:localhost:8501 user@server`; only set `CHAT_BIND=0.0.0.0` behind a real ingress.

## 1. Two ways to run

| | venv on the host | container (`make up` / `make up-enterprise`) |
|---|---|---|
| install | `python3 -m venv .venv && .venv/bin/pip install -i <artifactory> -r requirements.txt` (the four modules must be next to each other) | `docker compose --profile local build` with `BASE_IMAGE`/`PIP_INDEX_URL` from `.env` |
| run | `make run` (`CHAT_BIND`, `CHAT_PORT`) | host networking (`local`) or published port + compose Postgres (`enterprise`) |
| DB | `CHAT__DB__URL` in `.env`: SQLite file or `postgresql+psycopg://…@127.0.0.1:5432/chat` after `make db-up` | `local`: SQLite in the `chat-data` volume; `enterprise`: `postgres` service |
| checks | `make doctor`, `make ask Q=…` | `docker compose --profile local exec chat chat-doctor` / `… chat-ask "Frage"` |

The venv is the quickest on a server that already runs the `osi` venv; the container is the one that survives Python
upgrades on the host. Both read the same `.env`.

## 2. Files to put on the server

```
<base>/
├── opensearch-index/        # already there (the node); its src/ and pyproject.toml are needed for the build and the venv
├── users/                   # src/ pyproject.toml README.md
├── retrieval/               # src/ pyproject.toml config.yaml README.md
├── chat-system/             # this folder without .venv/ data/ .env
└── .dockerignore            # repository root: keeps venvs, data, .env, tests, the corpus out of the build context
```

`rsync -av --exclude .venv --exclude data --exclude .env --exclude out --exclude __pycache__ users retrieval chat-system .dockerignore user@server:<base>/`
(the ontology lives in `/srv/rag/user-manual-books/` as for the indexer).

## 3. `.env` — the only file you edit

`cp .env.example .env`, comment the DEV BOX block, uncomment the REMOTE SERVER block, fill in:

```
CHAT__DB__URL=postgresql+psycopg://chat:<password>@postgres:5432/chat    # enterprise profile (container) — host venv: @127.0.0.1:5432
CHAT__UI__ALLOW_USER_SWITCH=false
RAG__OPENSEARCH__URL=http://localhost:9200
RAG__EMBEDDING__BASE_URL=http://localhost:11435/v1          # tunnel; model intfloat/multilingual-e5-large, QUERY_PREFIX="query: "
RAG__LLM__BASE_URL=http://localhost:11435/v1  RAG__LLM__MODEL=Qwen/Qwen3-Coder-30B-A3B-Instruct  RAG__LLM__CONTEXT_LIMIT_TOKENS=32000
RAG__ONTOLOGY__PATH=/ontology/ontology.yaml                  # container; host venv: /srv/rag/user-manual-books/handbuch_daten/Ontologie/ontology.yaml
USERS__ADAPTER=env  USERS__DEV_USER=dev                       # header + USERS__HEADER_* once oauth2-proxy is in front
POSTGRES_PASSWORD=<password>  CHAT_BIND=127.0.0.1  CHAT_PORT=8501  SELINUX_LABEL=,Z
ONTOLOGY_DIR=/srv/rag/user-manual-books/handbuch_daten/Ontologie
BASE_IMAGE=<registry>/python:3.12-slim  POSTGRES_IMAGE=<registry>/postgres:16-alpine
PIP_INDEX_URL=https://<artifactory>/api/pypi/<repo>/simple  PIP_TRUSTED_HOST=
```

Never put `HTTP_PROXY`/`http_proxy` into `.env` for run time: every endpoint is loopback and the HTTP clients ignore
the proxy environment; proxies are build args only (compose passes them into the image build when set in the shell).
The e5 model on the server needs the `"query: "` prefix (the chunks were embedded with `"passage: "`); `chat-doctor`
and `rag-retrieve check` both flag a model mismatch against `bhb-documents.embedding_model`.

## 4. Run

```bash
cd <base>/chat-system

# A) venv (Artifactory PyPI)
python3 -m venv .venv && .venv/bin/pip install -i $PIP_INDEX_URL -r requirements.txt
make db-up                         # Postgres in compose (skip for SQLite: CHAT__DB__URL=sqlite:///./data/chat.db)
make doctor && make db-init
make ask Q="Was war bei ZSDSUP-0247?" ARGS="--no-graph"
make run                           # then ssh -L 8501:localhost:8501 user@server and open http://127.0.0.1:8501

# B) container, host networking (tunnels on the loopback), SQLite in the chat-data volume
make up                            # = compose --profile local up -d --build
make health                        # curl --noproxy '*' http://127.0.0.1:8501/_stcore/health
docker compose --profile local exec chat chat-doctor
docker compose --profile local logs -f chat

# C) container, published port + compose Postgres
make up-enterprise                 # profiles postgres + enterprise; waits for Postgres from the host (scripts/wait_db.sh)
```

The schema is created/upgraded at startup (`CHAT__DB__AUTO_UPGRADE=true`); for a controlled rollout set it to
`false` and run `chat-db upgrade` yourself (`chat-db current` exits 1 when an upgrade is pending).

## 5. RHEL / CentOS notes (rootless podman behind the `docker` alias, SELinux)

- No `--wait`, `depends_on` in list form only: the Makefile polls readiness from the host (`scripts/wait_db.sh`
  uses `compose exec postgres pg_isready`; `COMPOSE="podman-compose" make db-up` if `docker compose` is not wired).
- **Volumes are named volumes** (`chat-data`, `chat-pgdata`): no `podman unshare chown`, no relabel needed. The only
  bind mount is the ontology directory, read-only, with `SELINUX_LABEL=,Z`.
- `network_mode: host` (profile `local`) with rootless podman uses pasta/slirp: `localhost:9200` and the tunnel
  ports on the host are reachable; the UI listens on the host's loopback directly (`CHAT_BIND`/`CHAT_PORT`).
- The image runs as uid 10001; Postgres runs as its image's uid inside the named volume. Nothing on the host needs
  a specific owner.
- Build behind the proxy: export the proxy variables in the shell before `docker compose … build` (compose forwards
  them as build args; apt-get honours the lowercase spelling) and set `PIP_INDEX_URL`/`BASE_IMAGE` in `.env`.

## 6. Troubleshooting

| Symptom | Cause → fix |
|---|---|
| `chat-doctor`: `db … has no schema yet` | first start not done yet → `make db-init` (or let `auto_upgrade` do it) |
| `chat-doctor`: `opensearch … no documents` / connection refused | node down or wrong `RAG__OPENSEARCH__URL` → `cd ../opensearch-index && make up && make status` |
| `chat-doctor`: `llm … unreachable` | tunnel not up / wrong `RAG__LLM__BASE_URL` / key → `ssh -L …`, `curl --noproxy '*' <base_url>/models` |
| warning `embedding model mismatch` in Diagnostik | `RAG__EMBEDDING__MODEL`/`QUERY_PREFIX` differ from what indexed the chunks → use the server block (e5 + `"query: "`) |
| answers cut mid-sentence, `finish_reason=length` | raise `RAG__LLM__MAX_TOKENS` (reasoning models spend ~1300 tokens thinking) |
| `ValueError: prompt estimate … exceeds the model context limit` | small model → `RAG__LLM__CONTEXT_LIMIT_TOKENS`, `RAG__RETRIEVAL__CONTEXT_TOKEN_BUDGET=2500`, `CHAT__RETRIEVAL__K=4` (`chat-doctor` `budget` warns) |
| "Gerade sind zu viele Anfragen gleichzeitig in Arbeit" | `CHAT__LIMITS__MAX_CONCURRENT_ANSWERS` reached (per process) — wait, or raise it |
| `Nicht angemeldet: missing header X-Forwarded-User` | `USERS__ADAPTER=header` without the ingress in front → `env` for tests, or fix oauth2-proxy |
| Postgres: `password authentication failed` | `POSTGRES_PASSWORD` changed after the volume was created → `docker volume rm chat-system_chat-pgdata` (destroys the data) or `ALTER USER` |
| container starts, UI blank | `make health`; `docker compose logs chat`; the first page load builds the graph (~1 s per manual) |
