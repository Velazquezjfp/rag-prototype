# Deploying opensearch-index on a remote server

Goal: the same OpenSearch node and `osi` tool on your server (CentOS/RHEL, Docker, internet only through a proxy,
Artifactory for PyPI and container images), then index the `out/` folders produced there. Verified locally on
2026-09-02 with `opensearchproject/opensearch:3.8.0`; the remote steps are the same commands with different values
in `.env`.

## 0. What it needs from the outside

| Need | Local | Remote |
|---|---|---|
| OpenSearch node image (~2 GB) | Docker Hub | internal registry mirror **or** daemon proxy **or** `docker load` (§1) |
| `osi` tool | `.venv` via PyPI | `.venv` via Artifactory PyPI, or the indexer image (`python:3.12-slim` from the registry) |
| Host kernel setting | already set | `vm.max_map_count >= 262144` |
| Memory | 2 GB heap + ~1 GB | same; `OPENSEARCH_HEAP` in `.env` |
| Network | 127.0.0.1:9200 | same (loopback); reach it through `ssh -L 9200:localhost:9200 user@server` |

Nothing else: no models, no GPU, no internet at run time.

## 1. Resolve the image question first

```bash
cd opensearch-index && bash scripts/preflight_image.sh        # honours OPENSEARCH_IMAGE from .env
```

It reports, in this order: image already present → registry reachable and tag exists (`docker manifest inspect`,
kilobytes, no download) → a look inside the image (uid 1000, curl present for the healthcheck) → the host's
`vm.max_map_count`. When the manifest is not reachable it prints the three fixes:

a) **Internal registry mirror** — the channel that already delivered `python:3.12` to the server. In `.env`:
   `OPENSEARCH_IMAGE=<artifactory-host>/<docker-remote-repo>/opensearchproject/opensearch:3.8.0`
   (and `DASHBOARDS_IMAGE`, `BASE_IMAGE` the same way).

b) **Daemon proxy** — `docker pull` and `docker compose pull` run inside dockerd, which does not read the shell's
   proxy variables (`docker manifest inspect` does, so it can succeed while the pull fails):
   ```bash
   sudo tee /etc/docker/daemon.json <<'JSON'
   {"proxies": {"http-proxy": "http://<proxy>:<port>", "https-proxy": "http://<proxy>:<port>",
                "no-proxy": "localhost,127.0.0.1,<artifactory-host>,<registry-host>,.<internal-domain>"}}
   JSON
   sudo systemctl daemon-reload && sudo systemctl restart docker
   ```
   (or the systemd drop-in `/etc/systemd/system/docker.service.d/http-proxy.conf` with `Environment="HTTPS_PROXY=…"`).

c) **Offline transfer** — the way the dgs image travelled:
   ```bash
   make image-save                               # here: opensearch-3.8.0.tar.gz (from the ~2 GB image)
   scp opensearch-3.8.0.tar.gz server:           # then on the server:
   gunzip -c opensearch-3.8.0.tar.gz | docker load
   ```

Which version: 3.8.0 is the current line (k-NN and neural-search bundled; RRF hybrid search needs ≥ 2.19). If only
a 2.19.x image is available, set `OPENSEARCH_IMAGE` accordingly — the mappings use nothing newer than 2.19 and the
tests pass unchanged (the lucene k-NN engine is set explicitly; the 3.x default engine would be faiss).

## 2. Files to put on the server

```
<base>/
├── opensearch-index/                 # this directory without .venv/ data/ .env
│   ├── compose.yaml  Dockerfile  Makefile  config.yaml  .env.example  pyproject.toml  requirements.txt  README.md
│   ├── src/opensearch_index/  scripts/  tests/
├── docling-graph/                    # already there
├── user-manual-books/handbuch_daten/Ontologie/ontology.yaml
└── out/<run>/response.json           # what process_via_api.py wrote on the server
```

`rsync -a --exclude .venv --exclude data --exclude .env opensearch-index/ server:<base>/opensearch-index/`

## 3. `.env` — the only file you edit

Copy `.env.example`, uncomment the REMOTE SERVER block:

```bash
OPENSEARCH_IMAGE=<registry>/opensearchproject/opensearch:3.8.0   # or the Docker Hub name after docker load
OPENSEARCH_HEAP=2g
OPENSEARCH_BIND=127.0.0.1               # keep; SSH tunnel or same host
OPENSEARCH_DATA=./data/opensearch       # persisted inside the module folder
SELINUX_LABEL=,Z                        # SELinux enforcing
OSI__OPENSEARCH__URL=http://localhost:9200
OSI__EMBEDDING__MODEL=intfloat/multilingual-e5-large   # what DGS__EMBEDDING__MODEL was for those runs
OSI__EMBEDDING__DIM=1024
OSI__EMBEDDING__TEXT_PREFIX="passage: "
OSI__ONTOLOGY__PATH=/srv/rag/user-manual-books/handbuch_daten/Ontologie/ontology.yaml
OUT_DIR=/srv/rag/out                    # for the indexer container
ONTOLOGY_DIR=/srv/rag/user-manual-books/handbuch_daten/Ontologie
# build args for the indexer image: BASE_IMAGE, PIP_INDEX_URL, PIP_TRUSTED_HOST, proxies (both spellings)
```

**Security plugin.** The compose node runs with the plugin disabled (plain HTTP, no users) and is bound to the
loopback interface, which is the agreed setup for the dev box and the server. To run it enabled instead: remove
`DISABLE_SECURITY_PLUGIN` and `DISABLE_INSTALL_DEMO_CONFIG` from `compose.yaml`, set
`OPENSEARCH_INITIAL_ADMIN_PASSWORD` (8–100 chars with upper, lower, digit and special character, strong per
zxcvbn), and point the tool at `OSI__OPENSEARCH__URL=https://localhost:9200`, `OSI__OPENSEARCH__USERNAME=admin`,
`OSI__OPENSEARCH__PASSWORD=…`, `OSI__OPENSEARCH__VERIFY_CERTS=false` (demo certificates). The managed enterprise
cluster later is the same four settings plus `OSI__OPENSEARCH__CA_CERTS` and `OSI__INDEX__REPLICAS=1`.

## 4. Run

```bash
cd <base>/opensearch-index
make up                                  # data/opensearch (uid 1000 hints) + compose up -d + scripts/wait_healthy.sh
curl -s 'localhost:9200/_cluster/health?pretty'   # status yellow = ready (single node never turns green)

# tool via venv (Artifactory PyPI):
python3.12 -m venv .venv && .venv/bin/pip install -i https://<artifactory>/api/pypi/<repo>/simple -e .
.venv/bin/osi verify && .venv/bin/osi bootstrap
.venv/bin/osi ingest /srv/rag/out/remote-zsd
.venv/bin/osi status

# or the tool as a container (no Python on the host):
docker compose --profile tools build
docker compose --profile tools run --rm indexer verify
docker compose --profile tools run --rm indexer bootstrap
docker compose --profile tools run --rm indexer ingest /data/out/remote-zsd
```

`opensearch-py 3.2` pins `opensearch-protobufs==1.2.0`; if Artifactory does not mirror it, pin
`opensearch-py==3.1.0` in `pyproject.toml` (same API).

## 5. RHEL / CentOS notes

* **Data directory ownership.** The node runs as uid/gid 1000 and refuses to start on a root-owned directory:
  `sudo chown -R 1000:1000 data/opensearch` after `make init` if your user is not uid 1000.
* **SELinux** enforcing: `SELINUX_LABEL=,Z` relabels the bind mounts (data, `/data/out`, `/ontology`).
* **`vm.max_map_count`**: `echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-opensearch.conf && sudo sysctl --system`.
* **firewalld**: nothing to open — the port is bound to 127.0.0.1. Use an SSH tunnel for Dashboards/curl from a laptop.

### podman behind the `docker` alias (podman-docker + podman-compose)

Verified on the target server on 2026-09-03 (rootless podman with pasta networking, SELinux enforcing). The compose
file avoids everything podman-compose does not implement, so the same commands work:

* **No `--wait`.** `make up` runs `compose up -d opensearch` and then `scripts/wait_healthy.sh`, which polls
  `http://127.0.0.1:9200/_cluster/health?wait_for_status=yellow` from the host with `curl --noproxy '*'`
  (`WAIT_TIMEOUT`, default 300 s; progress every 30 s; on timeout it prints `compose ps`, the last 40 log lines and
  the known causes). `make wait` re-runs just the poll. If `docker compose` is not wired to podman on that host:
  `COMPOSE="podman-compose" make up`.
* **`depends_on` is ordering only** (no `condition: service_healthy`). Run `make up` before
  `docker compose --profile tools run --rm indexer …`; the `osi` client retries but does not wait for a booting node.
* **Rootless podman: data directory ownership — the one that bit us.** Inside a rootless container uid 1000 maps to
  one of your subordinate uids, so a directory you own on the host is *root-owned* as seen by the OpenSearch
  process, and the node exits with `failed to bind service … AccessDeniedException: /usr/share/opensearch/data/nodes`.
  `make init` (part of `make up`) now detects rootless podman (`docker info --format '{{.Host.Security.Rootless}}'`)
  and runs `podman unshare chown -R 1000:1000 data/opensearch` itself. Afterwards the host shows the directory owned by
  a high uid such as 100999 — correct, not damage — and `make reset` removes it with `podman unshare rm -rf`.
  How we confirmed it:
  ```bash
  docker info 2>/dev/null | grep -i rootless      # rootless: true
  ls -ld data/opensearch                          # host view: your user
  podman unshare ls -ld data/opensearch           # container view: root root  -> the problem
  getenforce                                      # Enforcing -> SELINUX_LABEL=,Z stays required
  ```
* **SELinux** enforcing: keep `SELINUX_LABEL=,Z` in `.env`; podman relabels the mount at every start, nothing to
  repeat. A denial with the label in place shows up in `sudo ausearch -m avc -ts recent` (e.g. a data directory on a
  filesystem that cannot carry labels).
* **Rootless podman: memlock.** The user's hard `memlock` limit cannot be raised from inside a rootless container.
  If the node exits with `memory locking requested for opensearch process but memory is not locked`, set
  `OPENSEARCH_MEMORY_LOCK=false` in `.env` (the JVM heap is then swappable; irrelevant for this data size).
* **Healthcheck.** The compose healthcheck is informational (rootless podman runs it through transient systemd
  units, which some hosts lack); readiness comes from the host-side poll.
* **`restart: unless-stopped`** survives reboots only with a systemd unit under podman
  (`podman generate systemd --new --name opensearch-index-opensearch-1` or a quadlet).
* **Proxies.** Only `docker manifest inspect` / `docker pull` need the corporate proxy (§1). The host-side checks use
  `--noproxy '*'` and the wait script never sources `.env`, so build-time proxy variables cannot redirect a loopback
  request. `osi` itself ignores proxy variables.

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `unknown flag: --wait` / `unrecognized arguments: --wait` | an old `make up`; the current one polls readiness with `scripts/wait_healthy.sh` (podman-compose has no `--wait`) |
| `make up`: node never gets ready, container restarts | the wait script prints the log tail: `max virtual memory areas vm.max_map_count [65530] is too low` → §5; `AccessDeniedException … /usr/share/opensearch/data/nodes` → ownership (rootless podman: `make init` chowns via `podman unshare`, or do it by hand) or SELinux (§5); `memory locking requested … but memory is not locked` → `OPENSEARCH_MEMORY_LOCK=false` |
| `osi verify` → `knn_plugin: false` | not the official image or a managed cluster without k-NN → request k-NN by name (docs/infrastructure-dependencies.md) |
| `MappingMismatch: knn dimension 1024 != OSI__EMBEDDING__DIM 768` | the indices were created for another embedding model; keep one model per prefix or use another `OSI__INDEX__PREFIX` |
| `invalid embeddings … dim 768 != 1024` | the run was embedded with another model than `.env` says; fix `OSI__EMBEDDING__*` (they are recorded on the chunks) |
| `cannot determine the document id … pass --doc-id` | file name not in the ontology's `meta.documents`, no id on the title page, no `DOCUMENTS` edge → `osi ingest … --doc-id BHB-XXX-0000` |
| `content sha256 … is already indexed as doc_id …` | the same PDF under a second id: almost always a wrong `--doc-id`; `--force` if intended |
| `doc_id X currently holds 'A.pdf'; the new file is 'B.pdf' — pass --replace` | new PDF version with another file name; `--replace` replaces the old records |
| `an ingest of X is in progress since …` | another `osi ingest` is running (or crashed < `lock_ttl_s` ago); wait or `--force` |
| manifest `status: failed` in `osi status` | the error is in the manifest; fix the cause and re-run — the previous run's records were not swept |
| `strict_dynamic_mapping_exception` | a field the mapping does not know: the tool and the indices are from different versions → bump `MAPPING_VERSION`, migrate |
| ingest through a corporate proxy fails | the client uses urllib3 without proxy environment; make sure `OSI__OPENSEARCH__URL` is reachable directly (tunnel/loopback) |
