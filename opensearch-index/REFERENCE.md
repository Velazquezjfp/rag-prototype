# opensearch-index — module 2: the OpenSearch store for docling-graph output

Takes what `docling-graph/` produces for one manual (`response.json`: Markdown, embedded chunks, ontology-typed
graph, metadata) and puts **all of it** into OpenSearch, idempotently: re-running the same output is a no-op,
a new extraction or a new PDF version replaces exactly that document's records, nothing is ever duplicated.
It also runs the OpenSearch node itself (docker compose, k-NN enabled, data persisted in this folder) and ships the
checks that decide whether a server can get the image at all.

Verified 2026-09-02 on the ZSD manual (`out/remote-zsd`, OpenSearch 3.8.0): 112 chunks / 250 nodes / 154 edges
indexed in 1.1 s; second run `noop`; the other extraction of the same PDF (255 nodes) replaced the graph and swept
11 stale nodes; k-NN self-hit 1.0; identifier, node, BM25 and hybrid-RRF smoke queries answer from the right pages;
66 unit + 12 integration tests green; data survives `docker compose down`/`up`.

## What is stored

Four indices (aliases over `bhb-<name>-v1`), shared by all manuals; every record carries `doc_id`, `doc_sha256`,
`run_id`, `indexed_at`.

| Index | `_id` | Content |
|---|---|---|
| `bhb-chunks` | `chunk_id` | the retrieval unit: `text`/`body_text`/`caption` (German analyzer), breadcrumb, kind, pages, bboxes, `embedding` (`knn_vector`, lucene HNSW, cosine), **`identifiers`** (ontology regexes: tickets, SOPs, hosts, zones, firewall rules, document ids), reverse index **`node_ids` / `node_labels` / `node_types` / `edge_ids`** — a kNN hit yields its graph neighbourhood in the same lookup |
| `bhb-nodes` | `<sha12>:<node_id>` | one record per node per document: type, label + aliases, `identity` / `identity_norm` (the ontology identity key, normalized), `attributes` (`flat_object`), `attributes_text`, quote, chunk ids, pages, degree. `node_id` is docling-graph's content-addressed id, **the same in every manual that mentions the entity** |
| `bhb-documents` | `doc_id` | the manual: document info, title/version/valid_from/ci_id from its `Document` node, `related_doc_ids`, the full **graph as node-link JSON** (edges carry their `id`) for NetworkX (ADR-0005), Markdown, degraded flags, errors, warnings, timings, versions, counts |
| `bhb-manifest` | `doc_id` | ingest state and lock: `status` (`indexing` / `active` / `failed`), `run_id`, `previous_run_id`, sha, counts, swept, history |

Plus the search pipeline `bhb-rrf` (reciprocal rank fusion) for the four-clause hybrid query of SPEC §7.2.

## Quick start

```bash
cd opensearch-index
cp .env.example .env                       # pick the machine block
make up                                    # ./data/opensearch + compose up -d + wait for yellow  (http://127.0.0.1:9200; docker or podman)
make dev                                   # .venv with the osi CLI
make verify                                # version, plugins (opensearch-knn!), 1024-dim k-NN round trip
make bootstrap                             # indices + aliases + RRF pipeline (idempotent)
.venv/bin/osi ingest ../out/remote-zsd     # -> active  doc_id=BHB-PLT-0007 ... counts={'chunks': 112, 'nodes': 250, ...}
.venv/bin/osi ingest ../out/remote-zsd     # -> noop    already indexed
.venv/bin/osi status
.venv/bin/osi search --identifier ZSDSUP-0247
.venv/bin/osi search --knn-from-chunk 2bb722f565a0-0060 --k 3
.venv/bin/osi search --node-id Host_ca04c4f4e5846870
.venv/bin/osi search --text "Vault versiegelt" --knn-from-chunk 2bb722f565a0-0060 --hybrid
```

Without a Python environment (server): `docker compose --profile tools build` once, then
`docker compose --profile tools run --rm indexer ingest /data/out/remote-zsd` (`OUT_DIR` in `.env` is mounted as
`/data/out`). Optional UI: `docker compose --profile dashboards up -d` → http://127.0.0.1:5601.

## Input

`osi ingest <path>...` accepts a `response.json` file, a directory containing one (what `scripts/process_via_api.py`
writes), or a `dgs process` directory (`meta.json` + `chunks.json` [+ `graph.json`, `markdown.md`]). `document.json`
is never read. `graph: null` (`--no-graph`) and `embedding: null` are accepted; a vector whose length differs from
`OSI__EMBEDDING__DIM`, or a zero vector, refuses the whole run.

## Identity and idempotency

**Document id** (`BHB-PLT-0007`) — never guessed, recorded as `doc_id_source`: `--doc-id` › ontology
`meta.documents[].file` matching the file name › exactly one document-id regex hit on the **title page** (page-1
chunks; later pages cite the *other* manuals) › `attributes.doc_id` of the source node of the single `DOCUMENTS` edge
› error asking for `--doc-id`. Disagreements between the methods are printed as warnings.

**Run id** — sha256 over everything that lands in the indices: document sha256, chunks (text and metadata; vectors
rounded to 1e-4 so float noise does not count), nodes and edges (sorted, so order does not count), the ontology
template hash, dgs versions, the configured embedding model/dimension and the mapping version. Identical output ⇒
identical `run_id`. A fresh docling-graph run of the same PDF gives a new `run_id` because the LLM extraction is not
reproducible (250 / 255 / 279 nodes in three runs) — and that is what the protocol handles.

**Protocol** (`osi ingest`):

1. `plan`: resolve `doc_id`, compute `run_id`, read the manifest. `noop` if that run is already active. Guards:
   the same content sha256 under a different `doc_id` is refused (`--force` overrides); a new sha256 under a known
   `doc_id` is a *replace* — allowed when the file name matches, otherwise `--replace` is required.
2. `lease`: write the manifest as `indexing` with optimistic concurrency (`op_type=create` or `if_seq_no`); a
   concurrent ingest gets a clear error, a stale lease (older than `ingest.lock_ttl_s`) or `--force` takes over.
3. `bulk` upsert with deterministic ids (chunks, nodes, document) → refresh → **verify counts** (`doc_id` + `run_id`).
4. `sweep`: delete every record of this `doc_id` whose `run_id` differs (stale nodes of the old extraction, old
   chunk ids of a replaced PDF version). Only after the counts checked out.
5. `finalize`: manifest `active`, `previous_run_id`, `history`. Any error before that → manifest `failed` with the
   message, **no sweep**, exit 1; the index then holds a superset (never a hole) and the next run heals it.

Chunk and node ids are logical, so records are overwritten in place. Consequence for the retrieval module: **never
filter by `run_id`** — read the manifest for status, query the data as it is.

`osi ingest --dry-run` prints the plan (doc id and how it was resolved, sha, run id, counts, the sweep query) and
writes nothing. `osi status` lists manifests, per-document counts, failed or in-progress ingests and chunks without a
manifest.

## Several manuals, one corpus

The indices hold all books together. docling-graph's `node_id` is a hash of the ontology identity value plus class,
so `Host iam-p01` or `Document BHB-PLT-0007` gets the same id in every manual: `terms node_id` on `bhb-nodes` gives
the entity across books, `osi search --node-id` shows it with its edges from every document, `osi status` counts the
`node_id`s that appear in more than one document. The `RELATED_DOCUMENT` edges of the ZSD graph already point at the
`Document_…` ids the other manuals will produce. The cross-document merge with attribute-conflict lists (SPEC §5.4)
is a later module; it groups by `node_id` and writes new indices — nothing here changes.

## Configuration

`config.yaml` holds working defaults; override per key with `OSI__<SECTION>__<KEY>` in `.env` or the environment
(`OSI_CONFIG=/path/config.yaml` selects another file). Switching machines or clusters is `.env` only.

| Key | Default | Meaning |
|---|---|---|
| `opensearch.url` | `http://localhost:9200` | `https://` enables TLS |
| `opensearch.username` / `password` | – | basic auth (security-enabled node or managed cluster) |
| `opensearch.verify_certs` / `ca_certs` | `true` / – | TLS verification; PEM bundle of the internal CA |
| `opensearch.timeout_s` / `max_retries` | 60 / 3 | |
| `index.prefix` | `bhb` | `bhb-chunks`, … ; tests use `bhbtest` |
| `index.shards` / `replicas` | 1 / 0 | replicas 1 on a multi-node cluster |
| `index.knn_m` / `knn_ef_construction` | 16 / 128 | lucene HNSW parameters |
| `index.rrf_pipeline` / `rrf_rank_constant` | true / 60 | create `bhb-rrf` at bootstrap (server ≥ 2.19) |
| `embedding.model` / `dim` / `text_prefix` | `bge-m3` / 1024 / `""` | **must match the dgs run** (`DGS__EMBEDDING__*`); recorded on every chunk |
| `ontology.path` | `../user-manual-books/…/ontology.yaml` | identifier regexes, identity keys, `meta.documents` |
| `ingest.bulk_size` | 200 | documents per bulk request |
| `ingest.lock_ttl_s` | 3600 | an `indexing` manifest older than this may be taken over |
| `ingest.history_keep` | 20 | previous runs kept in the manifest |

Mapping changes: bump `MAPPING_VERSION` in `mappings.py`, create `-v2`, reindex, swap the alias; `osi` refuses to
write into indices of another mapping version or vector dimension (`_meta`).

## CLI

| Command | Does |
|---|---|
| `osi verify` | reachable, version, plugins (fails without `opensearch-knn`), temporary k-NN index with a `dim`-vector round trip |
| `osi bootstrap [--dry-run]` | create missing indices/aliases and the RRF pipeline; check existing ones |
| `osi ingest <path>... [--doc-id X] [--force] [--replace] [--dry-run] [--json]` | the protocol above |
| `osi status [--json]` | manifests, counts, attention list, cross-document node ids |
| `osi search --text T \| --knn-from-chunk ID \| --identifier X... \| --node-id N [--hybrid] [--k]` | smoke queries with stored vectors (no embedding endpoint needed) |
| `osi delete --doc-id X [--yes]` | remove every record of one document |

Global options `--url`, `--prefix`, `--ontology`, `--log-level` override the settings for one call.

## Development

```bash
make dev && make test          # 66 unit tests, no cluster needed (in-memory fake client for the protocol)
make up && make bootstrap
make test-integration          # 12 tests against the node, prefix bhbtest-, cleaned up afterwards
make lint
```

Layout: `src/opensearch_index/{settings,schemas,ontology,loader,identity,transform,mappings,client,indexer,search,cli}.py`,
`tests/unit` (+ `fake_client.py`), `tests/integration/test_roundtrip.py`, `tests/data/response_small.json`
(12 chunks with 8-dim vectors, built by `scripts/make_fixture.py`), `scripts/preflight_image.sh`, `compose.yaml`,
`Dockerfile` (indexer image), `DEPLOY.md` (remote server).

## Limitations / next

- Processing and indexing in one step is the `ingest/` service now: it uses this package as a library and takes the
  embedding model from what dgs reports in `/v1/capabilities`.
- The retrieval module (`retrieve(question, use_graph)`) builds on `bhb-chunks` (four-clause hybrid query through
  `bhb-rrf`) and the graph blobs in `bhb-documents`; `search.py` shows the queries.
- No `edges` index: edges live in the graph blob and in `edge_ids` on chunks (they are traversed, not searched).
  Adding one later is a new index, no migration.
- Readers see a superset for the second between bulk and sweep; ingestion is a manual, separate process, so no
  blue/green switch was built.
