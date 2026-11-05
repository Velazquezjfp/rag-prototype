# Next steps

**Hardware now known:** NVIDIA RTX 4080, **12 GB VRAM**; WSL2 with **23 GiB RAM**.
That closes the last blocking open item and changes the local topology. See §0 before anything else.

---

## 0. What the hardware forces

### The target model cannot run locally, at any quantization

Qwen3-Coder-30B-A3B needs roughly 17–20 GB at 4-bit before KV cache. On 12 GB it does not
fit, and the MoE architecture does not help: ~3B active parameters cuts *compute*, not the
memory floor, because all experts must be resident.

RAM offload is also out. A Q4 GGUF of that model is ~18 GB, and the 23 GiB has to hold WSL,
Docker with OpenSearch and Postgres, and the Python processes. Do not spend a day trying.

**So local dev runs a small stand-in, exactly as agreed. This is not a compromise, it is the
plan** — local exists to prove the plumbing, and quality is measured remotely.

### Good news: the vision side is far cheaper than assumed

`granite-docling-258M` is **530 MB** on disk (258M parameters, siglip2 vision backbone,
Granite-165M decoder, document images to 2048×2048 via dynamic patching). It runs comfortably
on a 4070. Diagram-era VRAM anxiety was misplaced.

### Correction to SPEC §5.3: "granite VLM" was two jobs, not one

| Job | Model | Size | Note |
|---|---|---|---|
| Document conversion — layout, tables, formulas | `granite-docling-258M` | 530 MB | This is docling's VLM pipeline. **Not** a describer. |
| Picture description — the German text per Abbildung | a general VLM, granite-vision-2b class | ~2–3 GB fp16 | Needed for ADR-0010's citeable figure chunks |

`granite-docling` parses document structure into DocTags. It does not write a German
description of a Kontextdiagramm. The description job in ADR-0010 needs a general
vision-language model, configured through docling's picture-description hook. Both fit in
12 GB; **neither may run while the LLM is loaded.**

### The sequencing rule

**Ingestion and serving never run at the same time on this GPU.** Ingestion is a separate
process anyway (ADR-0005), so make it a separate `make` target that expects the LLM stopped.

### Local budget

| Workload | Placement | Cost |
|---|---|---|
| Answering — local stand-in | GPU, `Qwen3-8B-AWQ` (or `Qwen3-4B-Instruct-2507`) | ~5–6 GB |
| Embeddings — `multilingual-e5-large` | **CPU** | ~1–2 GB RAM, keeps VRAM free |
| docling conversion | GPU, ingestion window only | ~1–2 GB |
| Picture description | GPU, ingestion window only | ~3 GB |
| OpenSearch + Postgres | Docker | ~4 GB RAM |

vLLM with tool calling: `vllm serve Qwen/Qwen3-8B-AWQ --enable-auto-tool-choice
--tool-call-parser hermes`. Tool calling matters even though the prototype has no agent loop,
because the contract must be identical to the remote endpoint (SPEC §10.1).

---

## 1. Step 0 — the ingestion spike. Do this first, before any infrastructure.

**Why this is first.** The ontology states ~70% of edges live in recurring tables, and the
corpus has 158 tables. **The entire architecture rests on docling extracting those tables
well from these specific PDFs.** If it does not, every other component is wasted work. This
is the cheapest possible test of the most load-bearing assumption, and it needs no OpenSearch,
no Postgres, no graph and no LLM.

**Target:** `Betriebshandbuch_ZSD.pdf` — 29 pages, the smallest, and it contains Tabelle 6,
the consumer matrix, which is one of the two tables that carry the cross-document edges.

**Do:** convert it with docling at `images_scale = 3.0`, dump the structured output, and look
at it by hand.

**Acceptance checklist — answer each yes or no in writing:**

1. Do tables come out as **structured objects** with rows and columns, or as flattened text?
2. Is each table's **caption attached** to it, so `Konsumentenmatrix` is findable?
3. Does Tabelle 6 survive with its columns intact — client, Vault path, certificate procedure,
   manual reference?
4. Are the `TESTDOKUMENT ·` page headers **cleanly strippable** as a line-prefix rule?
5. Do the 3 figures come out as picture elements at the **full ~4500 px**, and are the labels
   legible when you open them? Compare against `demo-corpus/diagramme-png/zsd*.png`.
6. Do identifiers survive as **single tokens** — `ZSDSUP-0247`, `BHB-PLT-0007`,
   `kv/dd/prod`, `SOP-ZSD-06` — or do they fragment across lines?
7. Is the **heading hierarchy** present, so h3/h4 chunk boundaries are actually available?
   (The old anonymized corpus had every heading flattened to one level. Verify this one does not.)

**If checks 1–3 fail,** stop and reconsider the extraction approach before building anything.
That is the outcome worth discovering on day one rather than in week four.

**If check 5 fails,** the render factor or the export path is wrong, not the model. Fix it here.

**Deliverable:** `ingestion/spike/README.md` with the seven answers and the sample output
committed. This is also the first artifact a later session can read to know where things stand.

---

## 2. Then, in order

Each step has a gate. Do not start the next one until the gate passes.

### Step 1 — Environment
Docker compose with OpenSearch (k-NN enabled) and Postgres; `pydantic-settings`; the
`AuthContext` seam with the dev adapter; `local_deploy.sh` simulating the ingress.

**WSL specifics that will bite you:**
- `vm.max_map_count=262144` is **required** or OpenSearch will not start. Set it in
  `/etc/sysctl.conf` inside WSL, or `wsl.conf` so it survives a restart.
- Set the OpenSearch heap explicitly: `OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g`. The 1 GB default
  is too small once k-NN is in use, and k-NN also consumes off-heap native memory.
- Disable swap for the container and set `memlock` to unlimited.
- Confirm your 23 GiB is actually granted: check `.wslconfig` on the Windows side.

**Gate:** create a k-NN vector index with 1024 dimensions and round-trip one document.
This is the concrete proof the plugin is really there.

### Step 2 — Ontology build
Move `Ontologie/` to `betriebshandbuch/v1/`. Rename the generator to
`ontology_to_pydantic.py`. Add `ontology_to_owl.py` sharing the loader. Add the Makefile.
Delete the hand-maintained `ontology_model.py` and generate it.

**Gate:** `make` produces all three artifacts, and `--check` fails loudly on a deliberately
broken ontology edit.

### Step 3 — Full ingestion
All five PDFs. Chunking per SPEC §5.1 with the **tokenizer-count assertion** in place from the
first commit, not added later. Entity resolution from the identity keys. Merge, serialize,
index.

**Gate:** `expected_graph_shape` passes — 5 documents, 2 hubs, 7 partner tickets, the
documented cycle, an 11-step chain, ≥6 shared persons, ≥7 negative edges. This is also where
you regenerate `canon.md` from the PDFs, replacing the stale one (SPEC §3.3).

### Step 4 — Retrieval, fast mode only
The single hybrid query with all four clause types. Query rewriting. The score-threshold
guardrail.

**Gate:** ask "auf welchen Servern läuft ZSD" and get the right hosts with citations. Ask
"was war bei ZSDSUP-0247" and confirm the identifier clause finds it exactly.

### Step 5 — Graph traversal, slow mode
The intent router from `docs/retrieval-intents.md`, typed edge allowlists, RRF fusion with the
graph list as a fifth input, provenance and channel in the citation.

**Gate:** the two questions that only slow mode can answer — *"was passiert wenn Vault
versiegelt ist"* must surface VPP as **explicitly unaffected with its reason**, and *"wurde
das schon einmal gelöst"* on a partner ticket must return the counterpart from the other
document.

### Step 6 — UI
Streamlit chat, references, fast/slow toggle, coverage and diagnostics as openable metadata
rather than primary output. Graph viewer with **negative edges in a distinct style**.

**Gate:** the fast/slow toggle produces a visibly different, better slow answer on one of the
Step 5 questions. That is your demo.

### Step 7 — Evaluation
Its own session. Golden set instantiated from the competency questions with the three extra
categories, every answer hand-verified. Coverage reported across the degradation levels.

**Gate:** numbers you would defend in a room.

---

## 3. Risk ordering

Highest first, so effort goes where it pays:

1. **Table extraction quality on these PDFs.** Addressed by Step 0. Everything depends on it.
2. **Silent embedding truncation.** Addressed by the assertion in Step 3. It would otherwise
   present as an unexplained quality ceiling much later.
3. **Entity resolution merging wrongly.** Addressed by the Step 3 gate; a bad merge is the
   worst live failure available.
4. **OpenSearch k-NN not actually present.** Addressed by the Step 1 gate, which is why that
   gate is a real index and not a health check.
5. **Local/remote prompt drift.** Addressed by pinning the prompt, format, tool schema and
   parameters, and by never tuning against local output.

---

## 4. Deliberately not now

Cross-encoder reranker · agent framework · graph database · vault client · compaction ·
npm toolchain · ingestion API · real OIDC. Each has a recorded reason in `docs/adr/`.
