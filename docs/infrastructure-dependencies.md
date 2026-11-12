# Infrastructure dependencies

**Purpose.** Living inventory of what must be provisioned by another team versus what ships in
the repo. This file is expected to change; keep the Status column current.

**Split rule.** "Enterprise" means someone outside the project must act. "Ours" means a
container or a library we control.

---

## 1. Needs enterprise provisioning

| Component | Dev form | Enterprise form | Owner | Status | Blocking |
|---|---|---|---|---|---|
| **GPU nodes + k8s GPU operator** | RTX 4080, 12 GB VRAM | existing demo/pilot environment | platform | **available** — company environments already set up for demos and pilots | no |
| **LLM endpoint (Qwen3-Coder-30B-A3B-Instruct)** | smaller Qwen on local GPU | vLLM in the pilot environment | platform | **fixed constraint** — the only model available until production | no |
| **OpenSearch with k-NN plugin** | docker container | managed cluster, **k-NN enabled** | platform | to request; treated as agreed | no |
| **PostgreSQL** | docker-compose | internal Postgres offering | platform | to request | no |
| **Container registry** | Docker Hub | internal registry | platform | **working** — python 3.12 and npm images already pulled | no |
| **PyPI proxy** | public PyPI | Artifactory | platform | **working** — docling, docling-graph, EasyOCR installed via Artifactory | no |
| **Model weight distribution** | Hugging Face | Artifactory | platform | **working** — EasyOCR models already pulled | no |
| **OIDC / SSO** | dev adapter + simulated ingress | oauth2-proxy at ingress against internal IDM/AD | platform + security | needed for v2, not the demo | no (demo) |
| **Ingress + TLS (internal CA)** | localhost | cluster ingress, internal CA cert | platform | standard | no |
| **PVC / StorageClass** | local volumes | cluster StorageClass | platform | standard | no |
| **Secrets management** | `.env` | Kubernetes Secret | platform | env vars only for the demo; no vault client implemented | no |

### Notes on the ones with traps

- **OpenSearch k-NN must be requested by name.** Enterprise OpenSearch is frequently
  provisioned as a logging cluster with k-NN disabled, and you will not discover it until you
  try to create a vector index.
- **Model weights are the commonly forgotten item.** Hugging Face is unreachable from the
  target environment; Qwen3-Coder plus granite plus `multilingual-e5-large` is tens of
  gigabytes. Already solved here via Artifactory, but re-check when adding a model.
- **`replicas: 1`** wherever a single-writer component exists, with a comment explaining why.

---

## 2. Ours, no request needed

| Component | Notes |
|---|---|
| Streamlit UI + graph viewer | `streamlit-agraph` or `pyvis` — pure Python |
| Docling / docling-graph | pip via Artifactory, already installed |
| granite VLM invocation | ingestion-time only, batch |
| `multilingual-e5-large` | CPU-capable at 205 pages; does not compete with granite for VRAM |
| Python middleware, ingestion, retrieval | this repo |
| NetworkX graph | in-process; **no graph database** |

---

## 3. Explicitly NOT needed

Recording these so nobody adds them later without a reason:

| Not needed | Why |
|---|---|
| **npm mirror / Node toolchain** | Streamlit is pure Python and the graph viewer uses Python libraries. Do not negotiate this dependency channel unless something specifically requires it. |
| **Neo4j or any graph database** | ~1,500 nodes. In-memory NetworkX, persisted in OpenSearch. See `adr/0005`. |
| **Vault client** | `pydantic-settings` over env vars for the demo; the seam makes a later swap a one-loader change. |
| **LangGraph / Google ADK** | Retrieval is a fixed two-step pipeline. See `adr/0004`. |
| **Cross-encoder reranker** | Deferred until a golden set exists to tune against. See `adr/0006`. |
| **Server-side conversation compaction** | 10 messages/day against a 262K context cannot overflow. See `adr/0011`. |

---

## 4. Resource sizing

### Target environment

| Workload | When | Requirement |
|---|---|---|
| Qwen3-Coder-30B-A3B | query time | ~31 GB at FP8, ~17-20 GB at 4-bit, before KV cache. MoE cuts compute (~3B active), not the memory floor |
| `granite-docling-258M` | ingestion, batch | 530 MB. Document conversion only |
| Picture-description VLM (granite-vision-2b class) | ingestion, batch | ~2-3 GB fp16. Writes the German figure descriptions |
| `multilingual-e5-large` | ingestion + query | CPU acceptable; 1024-dim output |
| OpenSearch | always | small; 205 pages of chunks |
| Postgres | always | trivial; 10 users |

### Local development — RTX 4080, 12 GB VRAM, 23 GiB WSL RAM

**The target model does not fit locally at any quantization**, and RAM offload is not viable
alongside the Docker stack. Local runs a small stand-in; quality is measured remotely.

| Workload | Placement | Cost |
|---|---|---|
| `Qwen3-8B-AWQ` or `Qwen3-4B-Instruct-2507` | GPU | ~5-6 GB |
| `multilingual-e5-large` | **CPU** | ~1-2 GB RAM, keeps VRAM free |
| docling conversion | GPU, ingestion window only | ~1-2 GB |
| Picture description | GPU, ingestion window only | ~3 GB |
| OpenSearch + Postgres | Docker | ~4 GB RAM |

**Ingestion and serving never run simultaneously on this GPU.**

**WSL gotchas that will block you:**

- `vm.max_map_count=262144` is **required** or OpenSearch will not start. Set it in
  `/etc/sysctl.conf` inside WSL or in `wsl.conf` so it survives a restart.
- Set the heap explicitly: `OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g`. The 1 GB default is too small
  once k-NN is in use, and k-NN also consumes off-heap native memory.
- Disable container swap; set `memlock` to unlimited.
- Confirm the 23 GiB is actually granted — check `.wslconfig` on the Windows side.
