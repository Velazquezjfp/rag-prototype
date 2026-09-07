# integration/ — Phase 2, step 1: process a manual with docling-graph and index it in OpenSearch, in one step

**Status:** plan + essential tests written 2026-09-04; the script itself is implemented in the next session
(test-first against the interface below). Both services are assumed running on the target machine.

## 1. Purpose and scope

One command turns a PDF into indexed OpenSearch records: call the docling-graph service (`POST /v1/process`), write
the run folder exactly as `docling-graph/scripts/process_via_api.py` does today, then run the `opensearch-index`
ingest protocol on it. A directory of PDFs is consumed as a queue. No change to the docling-graph service, no change
to the `osi` tool: this folder is the orchestration layer that SPEC §12 calls `ingestion/` (docling-graph = extraction
service, opensearch-index = indexing, integration = the separate ingestion *process* of SPEC §5).

First end-to-end test: `user-manual-books/handbuch_daten/handbuch/Betriebshandbuch_CaaS-Plattform.pdf`
(`BHB-PLT-0001`, hub system, 27 pages / 19 tables / 3 figures) on the server, next to the already indexed ZSD manual
(`BHB-PLT-0007`). Only this book for now.

## 2. Alignment with SPEC and docs

| Requirement | Where | How this step honours it |
|---|---|---|
| Ingestion runs as a separate process; no ingestion API in the prototype | SPEC §5, ADR-0005 | a client-side script; the services stay as they are |
| Re-ingesting one manual replaces its subgraph; a new manual joins through shared nodes | SPEC §4.4, ADR-0003 | `osi` replace protocol per `doc_id`; shared `node_id`s (identity hash) join books, see §3 |
| Merged graph = union of per-document graphs joined by identity keys, loaded into memory at query time | SPEC §6.1, ADR-0005, graph-retrieval-patterns §3.4 | per-book graph blobs in `bhb-documents`; the union is a load-time operation (retrieval module); `cross_book_report.py` performs it today for inspection |
| Extraction acceptance = `expected_graph_shape` | SPEC §3.3 / §11.3, NEXT-STEPS Step 3 gate | the report checks the parts two books can satisfy: the documented cycle `Vault → CaaS-Plattform → BAVD Issuing CA 3 → Vault` spans exactly ZSD and CaaS; partner tickets (`ZSDSUP-0247` ↔ `CAASUP-0351`); shared persons; negative edges |
| Never quote a metric produced with a stand-in model; never mix models in an evaluation | SPEC §10.1, ADR-0014 | the CaaS run uses gemma4 while ZSD used qwen3-coder: fine for plumbing and for "does it connect", **not** for quality numbers (§5) |
| pip + pyproject, Artifactory, no uv | memory | `requirements.txt` here installs `opensearch-index` editable plus `httpx` |

## 3. Will the new book be an isolated graph, or connected to ZSD?

**Connected where identities match exactly, isolated where they do not — and both are visible.**

- docling-graph's node id is `<Class>_<blake2b(identity fields + class)>`. A `Document` with `doc_id BHB-PLT-0001`,
  an `Incident` with `ticket_id CAASUP-0351`, a `Host` with `hostname iam-p01`, a `Person` "Kai Ostermann" produce
  the *same* `node_id` in every manual that mentions them. The ZSD graph already contains
  `Document_5196103c4e4f5529` = `BHB-PLT-0001` (as a related document) and `Incident CAASUP-0351` (partner ticket);
  when the CaaS book is ingested, its own `Document` node and its own `CAASUP-0351` node land under the same
  `node_id`. Nothing is rewritten: each book keeps its records (`_id = <sha12>:<node_id>`) and its graph blob; the
  connection is the shared key.
- Edges are stored per book with their own provenance. Two books asserting the same relation are two evidence
  records with the same `(source, target, type, polarity)`; the union graph has both. (`edge_id` includes the quote
  and chunk ids, so it is per book — the join key for edges is the tuple, not the id.)
- **Not connected automatically:** identity values that differ in surface form. ZSD alone already has `ZSD`,
  `ZSD - Zentrale Sicherheitsdienste` and `Zentrale Sicherheitsdienste`, `Keycloak`/`keycloak`, `Ebert`/`Marcel Ebert`.
  Folding those (alias reconciliation, casefold across classes, attribute conflict lists such as 38 vs 48 min) is the
  **merge module** of graph-retrieval-patterns §3.4 — later, additive, not part of this step. So expect the hub
  `Zentrale Sicherheitsdienste` from `expected_graph_shape` to match only by containment, not by identity.

How to see it after the CaaS ingest:

```bash
osi status                                        # cross_document_node_ids.count > 0, with a sample
osi search --node-id Document_5196103c4e4f5529    # BHB-PLT-0001: nodes from both books + edges of both
osi search --node-id Incident_<CAASUP-0351 hash>  # partner ticket seen from both sides
python cross_book_report.py                       # shared nodes by type, cross-book edges, cycle check, partner tickets
```

`cross_book_report.py` (this folder) loads every graph blob from `bhb-documents`, unions them by `node_id`, and
reports: books present; shared node ids by class with labels per book; cross-book edges (edges whose endpoint also
exists in another book); `Document` nodes and which books carry them; partner tickets; the `expected_graph_shape`
items that two books can answer (the documented cycle, shared persons, negative edges, hub systems by containment).
Run against the current single book it prints the baseline (0 shared) and proves the queries work.

**Scope statement:** exact-identity consolidation is in scope and already works (it is a property of the ids);
alias/variant consolidation and the merged graph document are the later merge module.

## 4. Environment facts to design against (consolidated from module 1 and 2 work)

- Server: CentOS/RHEL, **rootless podman** behind the `docker` alias (pasta), SELinux enforcing. Compose files must
  avoid docker-only flags (`--wait`, `depends_on` conditions); `make init` chowns `data/opensearch` via `podman unshare`.
- docling-graph runs with `--profile local` (host networking): `http://localhost:8080`; one job at a time —
  a second `POST /v1/process` gets **503 + `Retry-After: 30`**; a request is bounded by
  `DGS__SERVICE__REQUEST_DEADLINE_S` (default 1800 s) and the HTTP client's read timeout must be at least that.
  Results are cached by (sha, options, models, versions): the same PDF with the same settings returns in < 1 s.
- OpenSearch node: `http://localhost:9200`, security plugin off; `osi` venv in `opensearch-index/.venv`, `.env` with
  absolute `OSI__ONTOLOGY__PATH`, embedding `intfloat/multilingual-e5-large`, dim 1024, prefix `"passage: "`.
- Models reach the server through SSH tunnels from the user's PC (`localhost:11435` → Ollama 11434). Only
  docling-graph uses them; neither `osi` nor this script talks to a model endpoint.
- Proxy: HTTPS only, not in any `.env`. Clients use `trust_env=False` (httpx) / urllib3 without proxy env.
- Python via Artifactory PyPI; pip, not uv. Paths on the server are absolute (`<base>/…`), not `/srv/rag`.

## 5. Using gemma4:26b instead of qwen3-coder for the CaaS run — guidance and pushback

Accept it for the integration test, with these adjustments in `docling-graph/.env` on the server (then
`docker compose --profile local up -d` to recreate the container):

| Variable | Set to | Why |
|---|---|---|
| `DGS__LLM__MODEL` | `gemma4:26b` | the id `GET /v1/models` returns on the tunnel |
| `DGS__LLM__CONTEXT_LIMIT` | the context Ollama actually serves for that model | **the most important one.** Ollama's default context is small (4–8k) unless the model or `OLLAMA_CONTEXT_LENGTH` says otherwise; dgs plans prompts against `CONTEXT_LIMIT` (default 128000), and an oversized prompt is truncated silently by the server, which produced the "coverage-pass timeouts" seen earlier. Check with `ollama show gemma4:26b` on the PC and raise the served context to ≥ 32k if it is lower. |
| `DGS__LLM__MAX_OUTPUT_TOKENS` | leave the default 8192 | do **not** lower it: gemma4 spends part of the budget on thinking; a truncated answer is a JSON parse failure. Raise only if `finish_reason=length` errors appear. |
| `DGS__LLM__STRUCTURED_OUTPUT` | `true`; switch to `false` if the graph step logs HTTP 400 on `response_format` | dgs falls back to prompt-mode JSON; gemma is less schema-faithful than a coder model, so expect more `unresolved_targets` and enum violations in `graph.meta` |
| `DGS__SERVICE__REQUEST_DEADLINE_S` | `7200` | a 26B model on a 12 GB GPU through a tunnel is slow; the ZSD graph step took 337 s with qwen on the server, budget an hour or more here. The script's read timeout must match (default 3 h below). |
| `DGS__VLM__ENABLED` | `false` for this run (or `qwen3-vl:30b` if it is up) | gemma4 as VLM was "blind" on this diagram set; three picture chunks are not worth a slower, noisier run |

Pushback to keep in mind: the CaaS graph will be **denser or sparser than the ZSD one for reasons of the model, not
of the manual**. Do not read node/edge counts of the two books as a comparison, and re-run CaaS with the qwen model
before any coverage number is quoted (SPEC §11.4). Tag the run folder so the origin stays visible:
`--run-suffix gemma4` → `out/Betriebshandbuch_CaaS-Plattform-gemma4/`. Follow-up for docling-graph (Phase 2 step 2):
report `llm_model`, `embedding_model`, `embedding_dim`, `text_prefix` in `versions`, so the manifest records them.

Quick endpoint check before the long run (same as docling-graph/DEPLOY.md §3):

```bash
curl -s http://localhost:11435/v1/models | head -c 300
curl -s http://localhost:8080/v1/capabilities | python3 -m json.tool | grep -A3 endpoint_status   # llm: ok
```

## 6. The script: `integration/process_and_index.py`

```
python process_and_index.py --pdf <file> [--pdf <file2> …] | --dir <folder> [--glob '*.pdf']
        [--dgs-url http://localhost:8080] [--out ../out] [--run-suffix gemma4]
        [--no-vlm] [--no-graph] [--no-embed] [--contract dense|direct] [--ontology <yaml>]
        [--concurrency 1] [--timeout 10800] [--skip-existing]
        [--doc-id X] [--force] [--replace] [--dry-run]           # passed to the indexer
```

Interface (what the tests in `tests/` expect):

```python
@dataclass
class RunConfig: dgs_url, out_root, run_suffix, options: dict, ontology: dict | None, concurrency: int,
                 timeout_s: float, skip_existing: bool, index: IndexFlags(doc_id, force, replace, dry_run)

async def process_one(client: httpx.AsyncClient, pdf: Path, options: dict, ontology: dict | None,
                      *, deadline_s: float) -> dict
    # POST /v1/process with base64 content; on 503 sleep Retry-After (default 30 s) and retry until deadline;
    # any other non-200 -> ProcessError(status, text[:2000])

def write_run_dir(resp: dict, out_dir: Path) -> Path
    # response.json, markdown.md, chunks.json, graph.json (if present), summary.json — the process_via_api layout,
    # so osi ingest, the viewer and DEPLOY docs keep working unchanged

def index_run(out_dir: Path, flags: IndexFlags) -> IngestReport
    # opensearch_index: get_settings() -> make_client -> load_ontology -> Indexer.plan/ingest on load_run(out_dir)
    # synchronous (opensearch-py is sync); the orchestrator calls it via asyncio.to_thread

async def run(pdfs: list[Path], cfg: RunConfig) -> list[BookResult]
    # asyncio: a semaphore of size cfg.concurrency around process_one (dgs takes one job per instance, so the
    # default is 1 and the win is pipelining: book N indexes while book N+1 converts); each book = process ->
    # write -> index, independent of the others; results collected, one summary line per book, exit 1 if any failed

def main() -> int   # argparse; httpx.AsyncClient(base_url, timeout=Timeout(cfg.timeout_s, connect=10), trust_env=False)
```

Behaviour that matters:

- `--skip-existing`: if `<out>/<run>/response.json` exists, skip the service call and only index — cheap re-index
  after an `osi`-side change, and safe because the indexer is idempotent anyway.
- Idempotency end to end: the same PDF with the same dgs settings hits the dgs result cache and then `osi` reports
  `noop`. A changed LLM produces a new response → a new `run_id` → the book's records are replaced (ZSD stays).
- Failures are per book: a dgs 500 or a `PlanError` marks that book failed and the queue continues; the summary
  names the failed ones. Nothing is written to OpenSearch for a book whose processing failed.
- Logging: one line per phase per book with elapsed seconds (`convert+graph`, `write`, `index`), the dgs
  `degraded` flags and `errors[]` echoed, because a degraded graph must be visible before it is indexed.

Why asyncio here and not just a loop: the dgs call is one long HTTP wait per book (tens of minutes) and the index
step is seconds; with a directory of manuals the orchestrator should keep the service busy while indexing the
previous result, back off on 503 without blocking, and later address more than one dgs instance
(`--dgs-url` repeated → semaphore per URL). Nothing more: no queues persisted, no daemon.

## 7. Tests (essential only)

`tests/test_process_and_index.py` — runs without services (httpx `MockTransport`, stubbed `index_run`); written
before the script, green since 2026-09-04 (`../opensearch-index/.venv/bin/python -m pytest tests -q`):

1. `process_one` retries on 503 with `Retry-After` and returns the JSON of the eventual 200.
2. `process_one` raises `ProcessError` on any other non-200.
3. `write_run_dir` produces the five files of the `process_via_api` layout and a summary with counts.
4. `run` over two PDFs with `concurrency=1` never has two dgs calls in flight and indexes each written folder.

Live smokes done on the dev box (local dgs + local node, ZSD): `--skip-existing --dry-run` on an existing run dir →
`noop` against the active manifest, `index_report.json` written, settings and the relative ontology path resolved from
`integration/`; a second invocation while the service was busy → 503, waited the 30 s `Retry-After`, retried, gave up
at its `--timeout`, exit 1, no run directory created; full run through the service → see §8 step 2.

`cross_book_report.py` — the live check for §3, run after the CaaS ingest (and once before, for the baseline).

Manual smokes on the server after the run (from `opensearch-index/`, venv active):
`osi status` · `osi search --identifier CAASUP-0351` · `osi search --node-id Document_5196103c4e4f5529` ·
`osi search --text "Kaltstartreihenfolge" --k 5` (CaaS Tabelle 13, SPEC §5.1) · `osi ingest <run> ` again → `noop`.

## 8. Implementation order and the end-to-end run

1. DONE — `pip install -r integration/requirements.txt` into `opensearch-index/.venv` (adds httpx).
2. DONE — `process_and_index.py` implemented to §6, four tests green, ruff clean, live smokes (§7) on the dev box; results in `REPORT.md`.
3. Server: sync the `integration/` folder; `../opensearch-index/.venv/bin/pip install -r requirements.txt` (Artifactory
   index as for osi); optional `../opensearch-index/.venv/bin/python -m pytest tests -q` (no services needed).
4. Server: adjust `docling-graph/.env` per §5, recreate the dgs container, run the endpoint checks. The script prints
   the service's models on start (`llm=gemma4:26b(on) vlm=...(off) ...`), so a stale container is visible at once.
5. Server, from `integration/`:
   ```bash
   ../opensearch-index/.venv/bin/python cross_book_report.py            # baseline: 1 book, 0 shared
   ../opensearch-index/.venv/bin/python process_and_index.py \
       --pdf <base>/user-manual-books/handbuch_daten/handbuch/Betriebshandbuch_CaaS-Plattform.pdf \
       --out <base>/out --run-suffix gemma4 --no-vlm --timeout 10800
   ../opensearch-index/.venv/bin/python cross_book_report.py            # after: shared nodes, cycle check
   ```
   Output: `<base>/out/Betriebshandbuch_CaaS-Plattform-gemma4/{response,chunks,graph,summary,index_report}.json`.
   If the extraction was already produced with `process_via_api.py`, add `--skip-existing` (the run dir must be named
   `<pdf stem>-<suffix>`), which indexes without a second service call.
6. Acceptance for this step: CaaS manifest `active` with `doc_id BHB-PLT-0001` resolved via `ontology_file`;
   `osi status` shows two documents and `cross_document_node_ids.count > 0`; the report lists the two `Document`
   nodes as shared and names the partner ticket pair; the cycle check reports which of the three hops exist (any
   missing hop is a graph-quality finding, not an integration failure); a second run of the script is `noop`.

## 9. Out of scope here, planned next

`POST /v1/index` in opensearch-index + `DGS__SINK__URL` (Phase 2 step 2) · merge module (`bhb-entities`, alias
folding, conflict lists, merged graph document) · retrieval module (`retrieve(question, use_graph)`: question
embedding with `query:` prefix, identifier regexes, node-label terms, RRF, typed traversal per
`docs/retrieval-intents.md`) · re-running CaaS with the qwen model before any quality number is reported.
