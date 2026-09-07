# Integration report — process → index pipeline (Phase 2, step 1)

Date: 2026-09-04 · Scope: `integration/process_and_index.py` and `cross_book_report.py` against the running
docling-graph service (dgs) and the opensearch-index node (osi). Server run of the CaaS manual: **not yet executed**
(section 6). Numbers below describe the *mechanism*; they are not quality measures and must not be compared across
LLMs or runs (see section 4).

## 1. Result in one paragraph

The orchestrator is implemented to the interface in `PLAN.md` §6, its four tests are green, and it ran the complete
loop on the dev box: PDF → `POST /v1/process` → run directory → `osi` plan/ingest. A repeated run hit the service's
result cache and the indexer answered `noop`; a run started while the service was busy backed off on the 503 exactly
as the service asked and failed cleanly when its budget ran out. Nothing in `docling-graph/` or `opensearch-index/`
was changed. The folder can be synced to the server as is.

## 2. Deliverables in `integration/`

| File | Purpose | State |
|---|---|---|
| `process_and_index.py` | asyncio orchestrator: `--pdf`/`--dir`, semaphore `--concurrency` (default 1), 503 back-off within `--timeout`, run dir `<out>/<stem>[-<suffix>]` in the `process_via_api` layout + `index_report.json`, indexer in a worker thread, `--skip-existing`, per-book failure isolation, exit 1 on any failure, prints the service's models on start | done, smoked live |
| `cross_book_report.py` | read-only union of the `bhb-documents` graph blobs by `node_id`: shared nodes, cross-book edges, Document carriers, partner tickets, documented cycle, hubs, shared persons, negative edges | done, run on 1 book |
| `tests/test_process_and_index.py` | 4 tests without services (httpx `MockTransport`, stubbed indexer): 503 retry, non-200 → `ProcessError`, run-dir layout + summary, pipelining with one call in flight | 4 passed, ruff clean |
| `PLAN.md` | alignment with SPEC/ADRs, isolated-vs-connected answer, environment facts, gemma4 guidance, interface, server steps | updated (§7, §8) |
| `requirements.txt` | `-e ../opensearch-index`, `httpx`, `pytest`; installs into `opensearch-index/.venv` | installed on the dev box |

## 3. Verification on the dev box (local dgs `gemini-dev` via LiteLLM, local OpenSearch 3.8.0)

### 3.1 Unit level

`../opensearch-index/.venv/bin/python -m pytest tests -q` → `4 passed`; `ruff check --line-length 140 .` → clean.
One test contained a typo from the previous session (`b"%PDF fake %d"` is invalid bytes formatting) and was fixed.

### 3.2 Live smokes

| Case | Command shape | Observed |
|---|---|---|
| index-only path | `--skip-existing --dry-run` on a dir holding the ZSD `response.json` | no service call; doc_id `BHB-PLT-0007` via `ontology_file`; plan `noop` against the active manifest; `index_report.json` written; `.env` and the relative ontology path resolved from `integration/` |
| service busy | second process with `--timeout 40` while a job ran | 503 → waited the 30 s `Retry-After` → 503 → budget exhausted → `failed`, exit 1, **no run directory created** |
| preflight | any run needing the service | first log line names the models: `llm=gemini-dev(on) vlm=gemini-dev(on) embedding=bge-m3(on) deadline=1800s jobs=1` and warns when `--timeout` is below the service deadline |

### 3.3 End-to-end run and repeat (ZSD manual, `--no-vlm`, run suffix `local`)

| Step | Run 1 | Run 2 (same command) |
|---|---|---|
| service time | 408 s, `cached=False` | 0.5 s, `cached=True` |
| output | 108 chunks (82 text, 26 table), 108 embedded, 235 nodes, 114 edges, 24 unresolved targets, degraded none, errors none | identical |
| indexer | `active` in 4.9 s, run `8b058be25f9d`, reason `new extraction: 80638e76f8a1 -> 8b058be25f9d`, swept 4 chunks + 48 nodes | `noop` in 0.6 s |
| manifest | `BHB-PLT-0007` active, history 3 | unchanged |
| exit code | 0 | 0 |

Files written: `response.json`, `chunks.json`, `graph.json`, `markdown.md`, `summary.json`, `index_report.json`.
After the replacement, `osi search --identifier ZSDSUP-0247` still returns pages 4, 12, 22, 23, and
`cross_book_report.py` runs on the new state (1 book, 0 shared node ids, 16 `PARTNER_TICKET` edges,
7 negative edges, 7 referenced Document nodes: `BHB-PLT-0001`, `BHB-PLT-0042`, `BHB-VRF-0118`, `BHB-VRF-0207`,
`NET-ZK-004`, `NFH-ITS-1.4`, `SBF-ITS-2025`).

The sweep of 4 chunks is explained by the options, not by the indexer: the previous run had the VLM on and produced
3 `picture` chunks and one more `text` chunk; with `--no-vlm` those chunk ids no longer exist and were removed.
The 48 swept nodes are node ids the new extraction did not produce (see 4.1).

## 4. Observations worth carrying forward

1. **Extraction variance is real and the replace protocol is what makes it harmless.** Same PDF, same model, two
   runs: 250 vs 235 nodes, 154 vs 114 edges, 14 vs 24 unresolved targets. The earlier local extraction had 2 of the
   3 documented cycle hops (`Vault → CaaS-Plattform → BAVD Issuing CA 3 → Vault`); the new one has 0 of 3. This is
   why the indexer replaces a book's records as a unit instead of upserting, and why counts are never quality
   evidence. Anything downstream that caches graph facts must key on `run_id`.
2. **"Vault" is not one node.** The current extraction has no `System Vault`; the concept appears as
   `Host Vault` (`vault.caas.bavd.intern`, aliases `vault-0/1/2`), `Component Vault` (scoped
   `zentrale sicherheitsdienste::vault`), two `Namespace` nodes, a `StartupStep`, a `FailureMode` and four
   `ImpactStatement` nodes. Label-level lookups must therefore search across types, and the later merge module
   (`osi merge`) needs type-aware folding, not only spelling variants.
3. **Cross-book joins exist only for exact identities today.** `node_id` is content-addressed, so a node with the
   same identity in two books is the same record key. The ZSD graph already references `Document BHB-PLT-0001` and
   `Incident CAASUP-0351`; both become shared the moment the CaaS manual is ingested. Spelling variants stay separate
   until the merge module exists.
4. **The service caches results by content + options + models.** A repeat with identical flags is free; changing
   `--no-vlm` or the LLM produces a new result and therefore a new `run_id`. Tag such runs with `--run-suffix` so
   the run directories do not overwrite each other.
5. **Runtime profile of one book on the dev box:** convert 1 s (cached by the service), embed ~103 s, graph ~302 s,
   indexing ~5 s. Indexing is noise; keeping the service busy is what matters, which is what the semaphore plus
   pipelining does.

## 5. State of the two environments

| | Dev box (WSL2) | Server (RHEL, rootless podman) |
|---|---|---|
| dgs | `dgs:local`, LiteLLM `gemini-dev`, embedding `bge-m3` (no prefix) | container `--profile local`, host network, `localhost:8080`; LLM to be switched to `gemma4:26b`; embedding `intfloat/multilingual-e5-large` with `"passage: "`; models via SSH tunnel `localhost:11435` |
| OpenSearch | 3.8.0, `localhost:9200`, security off | 3.8.0, `localhost:9200`, security off, `SELINUX_LABEL=,Z`, ownership via `make init` |
| `BHB-PLT-0007` (ZSD) | run `8b058be25f9d`, 108 chunks / 235 nodes / 114 edges (this report's run) | run `6bf7a8811289`, 116 chunks / 339 nodes / 276 edges (qwen3-coder, 2026-09-03), all osi smokes passed |
| `integration/` | present, tests green | to be synced; `pip install -r requirements.txt` into `opensearch-index/.venv` |

## 6. Pending: the CaaS run on the server

Steps and acceptance are in `PLAN.md` §8 (steps 3–6). In short, from `integration/` on the server after the
`docling-graph/.env` change to gemma4 (context limit above all) and a recreated dgs container:

```bash
../opensearch-index/.venv/bin/python cross_book_report.py            # baseline: 1 book, 0 shared
../opensearch-index/.venv/bin/python process_and_index.py \
    --pdf <base>/user-manual-books/handbuch_daten/handbuch/Betriebshandbuch_CaaS-Plattform.pdf \
    --out <base>/out --run-suffix gemma4 --no-vlm --timeout 10800
../opensearch-index/.venv/bin/python cross_book_report.py            # after: shared nodes, cycle check
```

Expected: manifest `BHB-PLT-0001` active via `ontology_file`; `osi status` shows 2 documents and
`cross_document_node_ids.count > 0`; the report lists the two Document nodes as shared and the partner-ticket pair;
a second invocation is `cached=True` + `noop`. The first log line must read `llm=gemma4:26b(on) vlm=...(off)`.

## 7. Handover for the next step: retrieval, dedup and the chat interface

Facts established in this and the previous sessions that the retrieval module will depend on. Design belongs to
SPEC §7 and `docs/retrieval-intents.md`; this list only records what is verified.

**Where the data is (aliases over `-v1`, `dynamic: strict`, never filter by `run_id`)**

- `bhb-chunks`: `text`, `caption`, `heading_breadcrumb`, `kind` (text|table|picture), `page_numbers`, `token_count`,
  `identifiers` (ontology regex hits, e.g. `ZSDSUP-0247`), reverse index `node_ids` / `node_labels` (lowercased,
  labels **and aliases** of anchored nodes and of the endpoints of anchored edges) / `node_types` / `edge_ids`,
  `embedding` (1024, lucene hnsw, cosine), `embedding_model`, `doc_id`. Exclude `embedding` from `_source` when
  reading; it is large.
- `bhb-nodes`: `_id = <sha12>:<node_id>`, `node_id` (cross-book key), `type`, `label`, `aliases`, `identity`,
  `identity_norm`, `attributes` (flat_object), `attributes_text`, `quote`, `chunk_ids`, `pages`, `doc_id`.
- `bhb-documents`: one per `doc_id` with the whole graph blob (`graph.nodes`, `graph.edges` with injected `id`),
  `markdown`, document meta, `root_system`, `related_doc_ids`. Load into NetworkX at query time (ADR-0005).
- `bhb-manifest`: which run is active per `doc_id`; `cross_document_node_ids` via `osi status`.
- Search pipeline `bhb-rrf` exists (`score-ranker-processor`, rank constant 60) for hybrid queries.

**Embedding the question**

- The stored vectors are produced by the dgs embedding endpoint with the configured prefix (`"passage: "` on the
  server, none locally). A question must go through the *same* model with the e5 query prefix `"query: "`, and the
  active model must match `embedding_model` on the chunks. `osi` has no embedding client; the retrieval module needs
  one, pointed at the same endpoint as `DGS__EMBEDDING__*` (tunnel `localhost:11435` on the server), with
  `trust_env=False` so a proxy never sits in the path.
- e5 cosine scores are compressed (weak neighbours around 0.96; tables cluster by shape). Do not use absolute
  similarity thresholds; rank by fusion (RRF over knn + BM25 `de_text` + `identifiers` + `node_labels`), as in
  SPEC §7.2. BM25 alone was right on the identifier and table smokes; a knn query with a meaningless vector ranked
  an unrelated table first, which is expected RRF behaviour and not a defect.

**Dedup before the LLM sees anything**

- Chunks are unique per `chunk_id`, but a table split into parts repeats caption and header on every part
  (`caption_and_header_on_every_table_part`), and the vector path and the graph path (`node_ids` → `chunk_ids`)
  return overlapping chunk sets. Merge by `chunk_id`, then group by `heading_breadcrumb`/`caption` so table parts are
  presented as one table with page ranges.
- Nodes: the same entity is one `node_id` across books but a separate record per book. Group by `node_id`, present
  once, and keep per-book attributes as a list with `doc_id`; conflicting attribute values are a signal, not noise.
  Edges asserted by two books carry the same `edge_id` when identical.
- Types: the same real-world thing can be extracted under several classes (observation 4.2). A label lookup that
  only hits one type will miss context; group presented facts by normalized label as a second key.
- Polarity: negative edges (7 in the current ZSD graph) must be rendered as negations
  (`X does NOT depend on Y`), never collapsed with positive ones.
- Provenance for every fact handed to the LLM: `doc_id`, `page_numbers`, `chunk_id` (and `edge_id` for graph
  facts). `run_id` is internal and not user-facing.
- Until the merge module exists, do not attempt alias folding at query time beyond casefold matching on
  `node_labels`; the report script's exact-first matching is a usable pattern.

**Environment rules that also apply to the chat service**

- Server: HTTPS-only proxy, no proxy variables in `.env`, loopback services only, pip via Artifactory, rootless podman
  behind the `docker` alias, `depends_on` list form, `SELINUX_LABEL=,Z` on bind mounts.
- Never compare retrieval quality numbers across different extraction LLMs or runs.

## 8. Not done, by decision

`POST /v1/index` + `DGS__SINK__URL` (Phase 2 step 2); `osi merge`; retrieval module; any change to dgs; any run on
the server in this session.
