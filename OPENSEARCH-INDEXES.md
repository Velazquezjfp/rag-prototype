# OpenSearch indexes and queries (current solution)

Status 2026-10-08. The four indexes of the **running** solution (OpenSearch 3.8.0, k-NN plugin, `lucene` engine):
which fields each one has, where every field comes from, which queries hit it and what Python does with the
result afterwards. Not covered: the SQLite alternative (`SUCHSPEICHER-VERGLEICH.md`).

Source of truth: `opensearch-index/src/opensearch_index/mappings.py` (schema), `transform.py` (field
provenance), `retrieval/src/rag_retrieval/search.py` + `retriever.py` (chat queries), `opensearch-index/src/opensearch_index/search.py` + `indexer.py` (`osi` queries).

Reading guide:

- **OpenSearch has no JOIN.** Records in different indexes are linked only by ids (`doc_id`, `chunk_id`, `node_id`).
  Every "join" below happens in Python, by fetching ids.
- **Alias → physical index.** Code only uses the alias (`bhb-chunks`); the physical index is `bhb-chunks-v1`
  (`MAPPING_VERSION = 1`). A mapping change creates `-v2` and swaps the alias.
- All mappings are `dynamic: strict`: a field that is not in the mapping is rejected at index time.
- `kw` = `keyword` (exact value, not analyzed). `text(de_text)` = analyzed with the German analyzer
  (standard tokenizer → lowercase → German stopwords → `german_normalization` → `light_german` stemmer).
  `+ .keyword` = the same field also stored as keyword sub-field. `(not indexed)` = stored in `_source`,
  not searchable. `(disabled)` = opaque JSON blob in `_source`, not parsed, not searchable.

## 0. Overview

| Index (alias) | One record = | `_id` | Written by | Read by chat (`rag_retrieval`) | Read by `osi` |
|---|---|---|---|---|---|
| `bhb-chunks` | one text chunk of one manual | `chunk_id` | `osi ingest` (bulk) | **yes**: 4 search channels + `mget` | smoke queries, counts, sweep |
| `bhb-nodes` | one graph entity *per document* (same entity in two manuals = two records) | `{sha12}:{node_id}` | `osi ingest` (bulk) | **no** | `node_lookup`, shared-node aggregation, sweep |
| `bhb-documents` | one manual, incl. the **whole graph as a JSON blob** | `doc_id` | `osi ingest` (bulk) | **yes**: `match_all` once at startup / reload | `get` by id |
| `bhb-manifest` | ingest bookkeeping per manual (status, run, counts) | `doc_id` | `osi ingest` (create/update) | **no** | `get`, `term`, `match_all` |

```text
response.json ──osi ingest──► bhb-chunks ◄── 4 channels + mget ── chat
(docling-graph)              bhb-nodes                               │
                             bhb-documents ◄── match_all (graph) ────┘
                             bhb-manifest  (osi only)
```

## 1. `bhb-chunks`

Settings: `index.knn: true`, 1 shard, 0 replicas, analyzer `de_text`, normalizer `lc` (lowercase + trim).

### 1.1 Fields

`c` = the chunk object `chunks[i]` in `response.json`. `G` = `graph` in `response.json`. `osi` = value set by the
indexer at ingest time (config `OSI__*` or computed).

| Field | Type | Provenance |
|---|---|---|
| `chunk_id` | kw (= `_id`) | `c.chunk_id` (`{sha12}-{nnnn}`) |
| `doc_id` | kw | **osi**: resolved per manual, in this order: `--doc-id` override → ontology `meta.documents` by file name → single document-id regex hit on page 1 → `DOCUMENTS` edge in `G`. Shared by all four indexes. |
| `doc_sha256` | kw | `document.sha256` |
| `run_id` | kw | **osi**: fingerprint of (response content, edge ids, ontology, embedding model/dim, mapping version). Same input → same `run_id` → re-ingest is a no-op. |
| `indexed_at` | date | **osi**: UTC timestamp of the ingest |
| `text` | text(de_text) | `c.text` (cleaned whitespace). Full chunk text incl. heading prefix. |
| `body_text` | text(de_text) | `c.body_text` (chunk text without the heading prefix) |
| `heading_breadcrumb` | text(de_text) + .keyword | `c.heading_breadcrumb` (array of headings) |
| `heading_level` | integer | `c.heading_level` |
| `kind` | kw | `c.kind` (`text`, `table`, `picture`) |
| `caption` | text(de_text) + .keyword | `c.caption` (tables/figures only) |
| `page_numbers` | integer (array) | `c.page_numbers` |
| `dom_paths` | kw (not indexed) | `c.dom_paths` |
| `bboxes` | object (disabled) | `c.bboxes` (page coordinates for highlighting) |
| `token_count` | integer | `c.token_count` |
| `identifiers` | kw (array) | **derived**: ontology regexes (`ontology.yaml`, e.g. `SOP-\d+`, host names) run over `c.text + c.caption`. Case-sensitive. |
| `node_ids` | kw (array) | **derived from `G`** (reverse index): every `G.nodes[j]` whose `provenance.chunk_ids` contains this chunk, plus both endpoints of every `G.edges[j]` whose `provenance.chunk_ids` contains it |
| `node_labels` | kw, normalizer `lc` (array) | **derived from `G`**: `label` **and** `aliases` of the nodes above, lowercased by the normalizer |
| `node_types` | kw (array) | **derived from `G`**: `type` of the nodes above |
| `edge_ids` | kw (array) | **derived from `G`**: hash id of every edge whose `provenance.chunk_ids` contains this chunk |
| `embedding` | `knn_vector`, dim 1024, `cosinesimil`, HNSW (`lucene`, m=16, ef_construction=128) | `c.embedding` (array of 1024 floats, computed by docling-graph with bge-m3). Rejected if dim ≠ `OSI__EMBEDDING__DIM` or all zeros. Also kept in `_source`, so every query excludes it. |
| `embedding_model` | kw | **osi**: `OSI__EMBEDDING__MODEL` (`bge-m3`); `response.json` does not name its model |

### 1.2 Queries

All chat channels: `size = 20` (`k_per_channel`), `_source.excludes = ["embedding","bboxes"]`. When the user
restricted the manuals, `doc_ids` adds a filter: inside the `knn` clause for kNN, as `bool.filter` for the others.
Without restriction the three text channels are sent unwrapped (no `bool`).

| Channel | Who | OpenSearch request (index `bhb-chunks`) | Search type / algorithm / limits | Post-processing |
|---|---|---|---|---|
| **kNN** (dense) | chat | `{"size": 20, "_source": {"excludes": ["embedding","bboxes"]}, "query": {"knn": {"embedding": {"vector": [0.012, -0.044, …1024 floats], "k": 20, "filter": {"terms": {"doc_id": ["BHB-PLT-0042"]}}}}}}` | **Vector search** on `embedding`. Question → same embedding model (bge-m3, HTTP call `RAG__EMBEDDING__*`) → 1024 floats. HNSW graph walk, cosine distance, **approximate**. The filter sits *inside* the `knn` clause → filter-during-search (always returns k valid hits). Score: higher = closer; only comparable inside this list. Skipped (with a warning) if the embedding service fails. | Rank 1…20 → RRF. The score itself is not used for fusion. |
| **BM25** (lexical) | chat | `{"size": 20, "_source": {…}, "query": {"bool": {"must": [{"multi_match": {"query": "Wer ist verantwortlich für SOP-6?", "fields": ["text^2", "body_text", "caption"]}}], "filter": [{"terms": {"doc_id": […]}}]}}}` | **Full-text**, Lucene **BM25** (defaults k1=1.2, b=0.75), `best_fields`: chunk score = max over the three fields, `text` weighted ×2. Question and index both go through `de_text`: `"SOP-6"` becomes the tokens `sop`, `6`; umlauts folded; stemmed. Finds same words, not same meaning. | Rank → RRF. The BM25 hit count feeds the guardrail. |
| **Identifier** (exact) | chat | `{"size": 20, "_source": {…}, "query": {"bool": {"should": [{"term": {"identifiers": "SOP-6"}}, {"term": {"identifiers": "vault-p01"}}], "minimum_should_match": 1, "filter": […]}}}` | **Exact keyword match**, **case-sensitive**, no analysis. Terms = ontology regexes run over the *question* (same regexes as at index time). Only channel that finds `SOP-6` as a whole. Sent only when the question contains at least one identifier. | Rank → RRF. Hit's `via` = which identifiers matched (shown in UI). Any identifier hit = strong evidence for the guardrail. |
| **Label** (exact) | chat | `{"size": 20, "_source": {…}, "query": {"bool": {"should": [{"term": {"node_labels": "sop-6"}}, {"term": {"node_labels": "vault"}}], "minimum_should_match": 1, "filter": […]}}}` | **Exact keyword match**, lowercased by normalizer `lc` on both sides. Terms = graph node labels/aliases found as n-grams (≤ 4 words) in the question, resolved against the **in-memory graph** (not OpenSearch), plus "partial" labels (≥ 2 question words). Sent only when at least one label was found. | Rank → RRF. `via` = matched labels. The matched nodes become start nodes of the graph expansion. |
| **Graph chunks** (fetch by id) | chat, slow mode | `POST bhb-chunks/_mget?_source_excludes=embedding,bboxes` body `{"ids": ["b6d7d486423e-0010", "b6d7d486423e-0093", …]}` | **Lookup by `_id`**, no search, no score. Up to 15 ids (`graph_max_chunks`) = the `provenance.chunk_ids` of the best graph facts. This is the "join" graph → chunks, done in Python. | Becomes the 5th list (`graph`) in a second RRF; the first 2 graph chunks are forced into the final list (`_guarantee_graph_sources`). |
| smoke: kNN with stored vector | `osi search --knn-from-chunk` | `GET bhb-chunks/_doc/{chunk_id}?_source_includes=embedding` → then the kNN query above without filter | same as kNN; vector read from an indexed chunk instead of embedding a question | none (printed) |
| smoke: hybrid RRF | `osi search --hybrid` | `{"query": {"hybrid": {"queries": [{knn…}, {multi_match…}, {"terms": {"identifiers": […]}}, {"terms": {"node_labels": […]}}]}}}` with `?search_pipeline=bhb-rrf` | **server-side** fusion by the `bhb-rrf` search pipeline (`score-ranker-processor`, `rrf`, rank_constant 60). Needs OpenSearch ≥ 2.19. **Not used by the chat** (it returns one score, cannot take the graph list). | none |
| maintenance | `osi ingest` / `delete` / `status` | count: `{"query": {"bool": {"filter": [{"term": {"doc_id": "BHB-PLT-0042"}}, {"term": {"run_id": "…"}}]}}}` · sweep (old runs of a manual): `delete_by_query {"query": {"bool": {"filter": [{"term": {"doc_id": "…"}}], "must_not": [{"term": {"run_id": "<new run>"}}]}}}` · delete manual: `delete_by_query {"query": {"term": {"doc_id": "…"}}}` · per-manual counts: `{"size": 0, "aggs": {"by_doc": {"terms": {"field": "doc_id", "size": 1000}}}}` | exact keyword filters / aggregation, no scoring | none |

## 2. `bhb-nodes`

### 2.1 Fields

`n` = `graph.nodes[j]` in `response.json`.

| Field | Type | Provenance |
|---|---|---|
| `node_id` | kw | `n.id` (`Person_fd3e064a23582274`); same id can appear in several manuals → `_id` = `{sha12}:{node_id}` |
| `doc_id`, `doc_sha256`, `run_id`, `indexed_at` | kw / date | as in `bhb-chunks` |
| `scope` | kw | constant `"document"` (`"corpus"` reserved for a future merge step) |
| `type` | kw | `n.type` (`Person`, `Procedure`, `System`, …) |
| `label` | text(standard) + .keyword(`lc`) | `n.label` (standard analyzer: names are not stemmed) |
| `aliases` | text(standard) + .keyword(`lc`) | `n.aliases` |
| `identity`, `identity_norm` | kw | **derived**: identity key from the ontology's identity rules per type + `root_system` (for merging the same entity across manuals) |
| `attributes` | `flat_object` | `n.attributes` (free key/values; only when non-empty) |
| `attributes_text` | text(de_text) | **derived**: all attribute values joined with spaces |
| `quote` | text(de_text) | `n.quote` (evidence sentence) |
| `identifiers` | kw (array) | **derived**: ontology regexes over `label + aliases + attributes` |
| `chunk_ids` | kw (array) | `n.provenance.chunk_ids` |
| `pages` | integer (array) | `n.provenance.pages` |
| `match` | kw | `n.provenance.match` (how the extractor anchored it, e.g. `verbatim`) |
| `degree` | integer | **derived**: number of edges in `G` touching this node |
| `provenance` | object (disabled) | `n.provenance` as a whole |

### 2.2 Queries

| Channel | Who | OpenSearch request (index `bhb-nodes`) | Search type / limits | Post-processing |
|---|---|---|---|---|
| — | chat | **none.** The chat never queries `bhb-nodes`; it gets the graph from `bhb-documents.graph`. | | |
| node lookup | `osi search --node-id` | `{"size": 50, "_source": {"excludes": ["provenance"]}, "query": {"term": {"node_id": "Procedure_53d37ee243c4f7f3"}}}` | exact keyword; all manuals that mention the node | Python "join": for every `doc_id` in the hits → `GET bhb-documents/_doc/{doc_id}?_source_includes=graph` → edges of that node collected from the JSON blob |
| shared nodes | `osi status` | `{"size": 0, "aggs": {"shared": {"terms": {"field": "node_id", "min_doc_count": 2, "size": 10000}}}}` | aggregation: node ids present in ≥ 2 manuals | reported |
| maintenance | `osi ingest` / `delete` | same count / sweep / delete_by_query / `by_doc` aggregation as for chunks | exact keyword filters | none |

The fields `label`, `aliases`, `attributes_text`, `quote` are searchable (text) but **no query uses them today**.
They exist for a later cross-manual entity search.

## 3. `bhb-documents`

### 3.1 Fields

`d` = `document` in `response.json`; `own` = the `Document`-type node in `graph.nodes` whose `attributes.doc_id`
equals this manual's `doc_id`.

| Field | Type | Provenance |
|---|---|---|
| `doc_id` | kw (= `_id`) | **osi**: see `bhb-chunks` |
| `doc_id_source` | kw | **osi**: which rule resolved `doc_id` (`override`, `ontology_file`, `page1_regex`, `documents_edge`) |
| `doc_sha256`, `run_id`, `indexed_at` | kw / date | as above |
| `scope` | kw | constant `"document"` |
| `name` | kw | `d.name` (file name) |
| `format` | kw | `d.format` (`pdf`) |
| `pages`, `tables`, `pictures` | integer | `d.pages`, `d.tables`, `d.pictures` |
| `title` | text(de_text) + .keyword | `own.attributes.title`, else `own.label` |
| `version`, `valid_from`, `classification`, `ci_id` | kw | `own.attributes.*` (`valid_from` stays an unparsed string: "22. Juli 2026") |
| `root_system` | kw | **osi**: `ontology.root_system(doc_id)` |
| `related_doc_ids` | kw (array) | `attributes.doc_id` of the *other* `Document` nodes in `G` (manuals this one cites) |
| `markdown` | text (not indexed) | `markdown` (the whole manual as Markdown, ~67 k chars) |
| `graph` | object (**disabled**) | **the complete `graph` of `response.json`** (`nodes`, `edges`, `meta`), plus an `id` on every edge. Stored as an opaque blob: OpenSearch cannot search inside it. |
| `degraded.vlm`, `.embeddings`, `.graph` | boolean | `degraded.*` (which pipeline stage ran in fallback mode) |
| `errors`, `warnings` | kw (not indexed) | `errors`, `warnings` |
| `timings_s`, `versions` | object (disabled) | `timings_s`, `versions` |
| `counts.chunks`, `.nodes`, `.edges`, `.documents` | integer | **osi**: computed at ingest |
| `embedding_model` | kw | **osi**: `OSI__EMBEDDING__MODEL` |
| `embedding_dim` | integer | **osi**: `OSI__EMBEDDING__DIM` (1024) |
| `embedding_text_prefix` | kw (not indexed) | **osi**: `OSI__EMBEDDING__TEXT_PREFIX` (`""` for bge-m3, `"passage: "` for e5) |

### 3.2 Queries

| Channel | Who | OpenSearch request (index `bhb-documents`) | Search type / limits | Post-processing |
|---|---|---|---|---|
| graph load | chat, **once at startup** and on `reload_graph()` after a new ingest | `{"size": 200, "_source": {"includes": ["doc_id", "title", "version", "root_system", "embedding_model", "embedding_dim", "embedding_text_prefix", "counts", "name", "indexed_at", "graph"]}, "query": {"match_all": {}}}` | **no search**: returns every manual (max 200) with its graph blob. The `graph` field is a JSON blob, so this is a bulk read, not a query. | Python builds the in-memory `GraphStore`: nodes, edges, adjacency, a label/alias index (`norm_key`), titles per `doc_id`. Everything graph-related in a chat request (label matching, 1-hop expansion, facts, entity cards) runs on this RAM copy, **not** on OpenSearch. Also used to warn when the query embedding model ≠ indexed one. |
| document record | `osi search --node-id` | `GET bhb-documents/_doc/{doc_id}?_source_includes=graph` | lookup by `_id` | edges filtered in Python (see `bhb-nodes`) |
| maintenance | `osi delete` | `DELETE bhb-documents/_doc/{doc_id}` | by `_id` | none |

## 4. `bhb-manifest`

### 4.1 Fields

Pure `osi` bookkeeping; nothing here comes from `response.json` except `doc_sha256` and `doc_name`.

| Field | Type | Provenance |
|---|---|---|
| `doc_id` | kw (= `_id`) | resolved `doc_id` |
| `status` | kw | `indexing` → `active` or `failed` (set by `osi ingest`) |
| `run_id`, `previous_run_id` | kw | current / previous run fingerprint |
| `doc_sha256`, `doc_name` | kw | `document.sha256`, `document.name` |
| `doc_id_source` | kw | see `bhb-documents` |
| `owner` | kw | `hostname:pid` of the indexer process (lock holder) |
| `started_at`, `finished_at` | date | ingest timestamps |
| `counts.*`, `swept.*` | integer | rows written / old rows removed per index |
| `embedding_model`, `mapping_version`, `indexer_version` | kw / integer / kw | what produced this run |
| `error` | kw (not indexed) | failure message (max 2000 chars) |
| `history` | object (disabled) | previous manifest states |

### 4.2 Queries

| Channel | Who | OpenSearch request (index `bhb-manifest`) | Search type / limits | Post-processing |
|---|---|---|---|---|
| — | chat | **none** | | |
| plan | `osi ingest` | `GET bhb-manifest/_doc/{doc_id}` (with `seq_no`/`primary_term` for optimistic locking) · `{"size": 5, "query": {"term": {"doc_sha256": "<sha>"}}}` (same PDF already indexed under another `doc_id`?) | lookup / exact keyword | decides **noop** (same `run_id`, status `active`), **refuse** (status `indexing` by another owner, unless `--force`) or **ingest** |
| lock + state | `osi ingest` | `PUT bhb-manifest/_doc/{doc_id}?op_type=create` (fails if it exists → lock) · update to `active`/`failed` with `if_seq_no`/`if_primary_term` | write with concurrency control | after `active`: sweep of older runs in chunks/nodes |
| listing | `osi status` | `{"size": 500, "sort": [{"doc_id": "asc"}], "query": {"match_all": {}}}` | all manifests | combined with the `by_doc` counts of chunks/nodes; `failed`/`indexing` reported under *attention* |

## 5. Independent searches vs. joins

**Independent (parallel) searches.** The four chat channels are sent as **one `_msearch` request**, all against
`bhb-chunks`; none depends on another's result:

```json
{"index": "bhb-chunks"}
{"size": 20, "_source": {"excludes": ["embedding","bboxes"]}, "query": {"knn": {"embedding": {"vector": [...], "k": 20}}}}
{"index": "bhb-chunks"}
{"size": 20, "_source": {"excludes": ["embedding","bboxes"]}, "query": {"multi_match": {"query": "Wer ist verantwortlich für SOP-6?", "fields": ["text^2","body_text","caption"]}}}
{"index": "bhb-chunks"}
{"size": 20, "_source": {"excludes": ["embedding","bboxes"]}, "query": {"bool": {"should": [{"term": {"identifiers": "SOP-6"}}], "minimum_should_match": 1}}}
{"index": "bhb-chunks"}
{"size": 20, "_source": {"excludes": ["embedding","bboxes"]}, "query": {"bool": {"should": [{"term": {"node_labels": "sop-6"}}], "minimum_should_match": 1}}}
```

A failing clause (e.g. k-NN plugin missing) becomes an empty channel with a warning; the others still answer.

**Joins (all in Python, by id).** OpenSearch never joins; there is no `join` field, no `nested`, no parent/child.

| Join | Key | From → to | Where |
|---|---|---|---|
| graph facts → evidence chunks | `edge.provenance.chunk_ids`, `node.provenance.chunk_ids` | RAM graph (from `bhb-documents.graph`) → `bhb-chunks` via `_mget` | `retriever.py` step 5 |
| chunk → graph nodes | `chunk.node_ids` | `bhb-chunks` hit → RAM graph (start nodes of the expansion) | `facts.select_start_nodes` |
| question → graph nodes | label n-grams / `norm_key` | question → RAM graph label index → `node_labels` terms query | `query.analyze_question` |
| chunk → manual title | `doc_id` | `bhb-chunks` hit → RAM `titles` (from `bhb-documents`) | `fusion.to_chunk_hits` |
| node → its edges | `doc_id` | `bhb-nodes` hit → `GET bhb-documents` → edges in blob | `osi search --node-id` only |

## 6. Post-processing after OpenSearch (chat, per question)

Defaults from `retrieval/src/rag_retrieval/settings.py`.

1. **Dedup + RRF** (`fusion.rrf`): `score(chunk) = Σ 1 / (60 + rank)` over the lists it appears in. Ties: more
   channels first, then better best rank, then `chunk_id`. The OpenSearch `_score` is kept only for display.
2. **Guardrail** (`guardrail.decide`): evidence is *strong* if the identifier channel hit or a graph label was in the
   question; otherwise BM25 must have returned something and one of the top 3 must come from ≥ 2 channels.
   Weak evidence → no graph expansion; with the guardrail enabled the chat answers without calling the LLM.
3. **Graph expansion** (slow mode only, RAM): start nodes = labels in the question + nodes of the top 5 fused hits
   + top 2 per channel (max 30). 1 hop in both directions → up to 40 facts
   (`Jonas Brinkmann —RESPONSIBLE_FOR→ SOP-6 [BHB-PLT-0042 S. 4–5]`) and up to 15 entity cards.
4. **Graph chunks**: `_mget` of up to 15 provenance chunks → 5th list → **second RRF**; the first 2 graph chunks are
   forced into the final list.
5. **Cut** to `final_k = 10`, **group** table parts sharing (`doc_id`, `caption`) under one caption, build
   **citations** `"{doc_id} S. {pages}"` from groups and facts.
6. To the LLM: the 10 chunks (text), the facts and the entity cards, plus the citations for the answer.

## 7. Fusion (RRF): formula and example

```text
score(chunk) = Σ over every channel list that contains the chunk of   1 / (60 + rank_in_that_list)
```

Only the **rank** counts. The OpenSearch `_score` (kNN 0.87, BM25 12.4, …) is never added: the four channels score on
different scales, ranks are comparable. A chunk found by several channels adds up; a chunk found once can only
reach `1/61 ≈ 0.0164`.

Example, question *"Wer ist verantwortlich für SOP-ZSD-06?"*, top 3 of each channel (`k=20` in reality):

| Rank | kNN | BM25 | Identifier | Label |
|---|---|---|---|---|
| 1 | **A** `…-0055` (SOP table) | D `…-0090` | **A** `…-0055` | **A** `…-0055` |
| 2 | B `…-0012` | **A** `…-0055` | E `…-0003` | E `…-0003` |
| 3 | C `…-0031` | B `…-0012` | — | — |

| Chunk | Terms | Score | Final rank |
|---|---|---|---|
| A | 1/61 + 1/62 + 1/61 + 1/61 | **0.0653** | 1 |
| E | 1/62 + 1/62 | 0.0323 | 2 |
| B | 1/62 + 1/63 | 0.0320 | 3 |
| D | 1/61 | 0.0164 | 4 |
| C | 1/63 | 0.0159 | 5 |

What this does: A, confirmed by all four channels, wins clearly. E (rank 2 in two *exact* channels) beats D, which
was BM25's number one but which no other channel confirmed. Ties are broken by number of channels, then best rank,
then `chunk_id`. In slow mode the graph chunks (§8) are added as a fifth list and the same formula runs again; the
final list is cut to 10.

## 8. How facts are fetched (edges + nodes)

The facts do **not** come from an OpenSearch query. They come from the graph that was loaded once into RAM from
`bhb-documents.graph` (§3.2): a list of **nodes** (`id`, `type`, `label`, `aliases`, `attributes`, `provenance`)
and a list of **edges** (`source`, `target`, `type`, `polarity`, `qualifier`, `properties`, `quote`, `provenance`).

1. **Start nodes** (max 30): the node ids behind the labels found in the question (`Kai Ostermann`,
   `SOP-ZSD-06`) + the `node_ids` of the top 5 fused chunks and the top 2 chunks of each channel.
2. **One hop** (`GraphStore.expand`): every edge whose `source` **or** `target` is a start node, over all relation
   types. The same edge id in two manuals = one fact with two citations.
3. **Edge → fact**: the edge gives relation, polarity, properties, quote and pages; the **nodes** give the labels
   and types of both ends. Max 40, ordered: edges touching a question label first, then relations the question
   asks about, negative statements before positive.

   ```json
   {"id": "2aca7dfa9b3a135b", "source": "Person_6cbefc94f3651b59", "target": "Procedure_53d37ee243c4f7f3",
    "type": "RESPONSIBLE_FOR", "polarity": "positive", "properties": {"raci": "verantwortlich", "is_deputy": false},
    "quote": "SOP-ZSD-06 | Kaltstart der Sicherheitsdienste | Notfall, Stromabschaltung, Wiederanlauf | Kai Ostermann",
    "provenance": {"pages": [17], "chunk_ids": ["2bb722f565a0-0055"]}}
   ```
   becomes
   ```text
   Kai Ostermann —RESPONSIBLE_FOR (verantwortlich für)→ SOP-ZSD-06 (raci=verantwortlich, is_deputy=False) — „SOP-ZSD-06 | Kaltstart …“ [BHB-PLT-0007 S. 17; Kante 2aca7dfa9b3a135b]
   ```
4. **Nodes → entity cards** (max 15): every node touched by a fact (start nodes + reached neighbours) is rendered
   with its type, aliases and attributes: `Kai Ostermann (Person) — role_title: Verantwortlicher ZSD; phone_ext: 1315 [BHB-PLT-0007 S. 1, 2]`.
5. **Facts → chunks**: the `provenance.chunk_ids` of the facts (max 15) are fetched from `bhb-chunks` with `_mget`
   and become the fifth RRF list, so the table row the fact was extracted from is also in the sources.

## 9. What the LLM receives

`prompt.build_messages` produces the `messages` array of one chat-completion call (OpenAI-compatible endpoint).
The context is **one Markdown string** inside the user message, in the order Entitäten → Fakten → Quellen. Entities
and facts always fit; sources are added by fused rank until the budget (6000 tokens) is spent. The last 3
user/assistant pairs of the conversation go in between.

```json
[
  {"role": "system",
   "content": "Du bist der Assistent für die IT-Betriebshandbücher (BHB) des BAVD. Du beantwortest Fragen … ausschließlich aus dem bereitgestellten Kontext … 1. Verwende nur Informationen aus dem Kontext … 2. Belege jede Aussage mit der Quelle in eckigen Klammern, z. B. [BHB-PLT-0007 S. 19] …"},

  {"role": "user", "content": "Welche SOPs gibt es im ZSD?"},
  {"role": "assistant", "content": "Im ZSD-Handbuch sind sechs SOPs beschrieben … [BHB-PLT-0007 S. 17]"},

  {"role": "user",
   "content": "Kontext:\n## Entitäten\n- SOP-ZSD-06 (Procedure) — sop_id: SOP-ZSD-06; title: Kaltstart der Sicherheitsdienste; trigger: notfall [BHB-PLT-0007 S. 17, 19]\n- Kai Ostermann (Person) — role_title: Verantwortlicher ZSD, IAM-Betrieb; phone_ext: 1315; email: iam-betrieb@bavd.bund.de [BHB-PLT-0007 S. 1, 2]\n\n## Fakten\n- Kai Ostermann —RESPONSIBLE_FOR (verantwortlich für)→ SOP-ZSD-06 (raci=verantwortlich, is_deputy=False) — „SOP-ZSD-06 | Kaltstart der Sicherheitsdienste | …“ [BHB-PLT-0007 S. 17; Kante 2aca7dfa9b3a135b]\n- Kai Ostermann —ESCALATES_TO (eskaliert an)→ Dr. Annika Reuß (level=2) [BHB-PLT-0007 S. 26; Kante …]\n\n## Quellen\n### Quelle 1 · BHB-PLT-0007 „Betriebshandbuch ZSD - Zentrale Sicherheitsdienste“ · S. 17 · 5 Betrieb › 5.5 Standard Operating Procedures · Tabelle 7: Standard Operating Procedures · [2bb722f565a0-0055]\n| SOP | Titel | Auslöser | Verantwortlich | Dauer |\n| - | - | - | - | - |\n| SOP-ZSD-06 | Kaltstart der Sicherheitsdienste | Notfall, Stromabschaltung | Kai Ostermann | 2-4 h |\n\n### Quelle 2 · BHB-PLT-0007 · S. 19 · … · [2bb722f565a0-0062]\n…\n\nFrage: Wer ist verantwortlich für SOP-ZSD-06?"}
]
```

Every entity, fact and source carries `[doc_id S. page]`; the system prompt obliges the model to cite exactly
these, which is what the UI turns back into clickable citations.
