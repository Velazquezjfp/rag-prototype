# Architecture & Data Flow — Ingest and Storage

How a PDF manual becomes searchable text, vectors and a knowledge graph in OpenSearch, and which
container does what. This follows the **target deployment in [`technical_request.md`](technical_request.md)**
(§1, §2, §5, §9). Where the code differs today, see [Plan vs. current](#plan-vs-current) at the end.
The question path is covered in [`RETRIEVAL-FLOW.md`](RETRIEVAL-FLOW.md).

All example records (the 💬 bubbles and the samples in §3) are **real data** from the ZSD run
(`BHB-PLT-0007`, `out/remote-zsd/response.json`), shortened with `…`.

---

## 1. The whole system

The platform provides OpenSearch and the model endpoints. We deliver three units: **chat**, **dgs** and
the **indexer**. The indexer is a one-shot container: it runs once per manual and then exits.

```mermaid
flowchart TB
  %% ============ inputs ============
  PDF[/"📄 PDF manual<br/>Betriebshandbuch_ZSD.pdf"/]
  ONTO[/"📐 ontology.yaml<br/>26 classes · 32 relations<br/>(ConfigMap, mounted read-only)"/]
  USER(["👤 User in browser"])
  ING["Ingress + IAM (PGA)<br/>injects X-Forwarded-User / -Email / -Groups"]

  %% ============ platform endpoints ============
  subgraph EXT["Platform model endpoints (OpenAI-compatible, not ours)"]
    direction LR
    LLM["🧠 LLM · gemma4<br/>/v1/chat/completions<br/>streaming + JSON schema"]
    EMB["🔢 Embedding · multilingual-e5-large<br/>/v1/embeddings · 1024 dim"]
    VLM["🖼 VLM (optional, off)"]
  end

  %% ============ dgs ============
  subgraph DGS["📦 Container dgs · docling_graph_service · POST /v1/process · :8080"]
    direction TB
    G1["① Convert<br/>docling: layout · TableFormer · OCR de/en"]
    G2["② Clean up DoclingDocument<br/>page furniture · headings · captions"]
    G3["③a Chunk for search<br/>HybridChunker · 512 tokens<br/>tables kept whole"]
    G4["④a Embed chunks<br/>prefix 'passage: ' · batches of 64"]
    G5["③b Extract graph<br/>slices → LLM, output forced into<br/>JSON schema compiled from ontology"]
    G6["④b Deduplicate<br/>ontology identity rules"]
    G7["⑤ materialize()<br/>join on item ids texts/40, tables/11 …<br/>node → chunk_ids · edge → chunk_ids"]
    G8["⑥ Write run directory"]
    G1 --> G2
    G2 --> G3 --> G4 --> G7
    G2 --> G5 --> G6 --> G7
    G7 --> G8
  end

  VOL[("🗂 Shared volume (RWX)<br/>run directory per manual<br/>response.json · markdown")]

  %% ============ indexer ============
  subgraph OSI["📦 Container indexer · osi ingest · one-shot, exits in seconds"]
    direction TB
    I1["① Load response.json<br/>check vector dim = 1024, no zero vectors"]
    I2["② Take the lease<br/>manifest status → indexing"]
    I3["③ Transform<br/>stamp reverse links chunk → nodes/edges<br/>extract identifiers by ontology regex"]
    I4["④ Bulk write · deterministic _id<br/>(re-run = upsert)"]
    I5["⑤ Verify counts · sweep the old run"]
    I6["⑥ Release<br/>manifest status → active"]
    I1 --> I2 --> I3 --> I4 --> I5 --> I6
  end

  %% ============ opensearch ============
  subgraph OS["🗄 OpenSearch ≥ 2.19 · k-NN plugin · the only data store"]
    direction LR
    XC[("bhb-chunks<br/>text + 1024-dim vector<br/>+ links to graph")]
    XN[("bhb-nodes<br/>one record per entity")]
    XD[("bhb-documents<br/>one per manual<br/>+ whole graph JSON blob")]
    XM[("bhb-manifest<br/>ingest state + lock")]
  end

  %% ============ chat ============
  subgraph CHAT["📦 Container chat · Streamlit :8501 · 1 replica"]
    direction TB
    CU["rag_users<br/>headers → user + groups → policy<br/>quota · allowed manuals"]
    CS["chat_system<br/>UI · conversations · daily quota"]
    CR["rag_retrieval<br/>4 search channels + 1-hop graph<br/>→ prompt with citations"]
    CG["in-memory union graph<br/>+ label index"]
    SQL[("SQLite on PVC<br/>conversations · messages · counters")]
    CU --> CS --> CR
    CS <--> SQL
    CR --- CG
  end

  %% ============ ingest wiring ============
  PDF -->|"multipart upload"| G1
  ONTO -->|"schema + identity rules"| G5
  G1 -.->|"figure images"| VLM
  G4 <-->|"chunk texts → vectors"| EMB
  G5 <-->|"slice + schema → typed JSON"| LLM
  G8 --> VOL
  VOL -->|"read"| I1
  ONTO -->|"identifier regexes, root systems"| I3
  I2 --> XM
  I4 --> XC
  I4 --> XN
  I4 --> XD
  I6 --> XM

  %% ============ ask wiring (details in RETRIEVAL-FLOW.md) ============
  USER --> ING -->|"HTTP + identity headers"| CU
  XD -->|"graph blobs at start-up"| CG
  XD -->|"document list · cached 5 min"| CS
  CR <-->|"msearch (4 channels) · mget"| XC
  CR <-->|"question → 1 vector, 'query: '"| EMB
  CR <-->|"prompt → streamed answer"| LLM
  CS -->|"answer + citations"| USER

  %% ============ data bubbles ============
  B0("💬 <b>ontology.yaml → schema</b><br/>RESPONSIBLE_FOR:<br/>  source: Person · target: NodeBase<br/>  label_de: 'verantwortlich für'<br/>  cues_de: ['zuständig', …]")
  B1("💬 <b>response.json</b> (dgs output)<br/>{ document: {name, sha256, pages: 29},<br/>  chunks: [112 × {chunk_id, text, embedding[1024]}],<br/>  graph: {nodes: [250], edges: [154]},<br/>  degraded: {vlm, embeddings, graph: false} }")
  B2("💬 <b>bhb-chunks</b> _id 2bb722f565a0-0055<br/>kind: table · page_numbers: [17]<br/>caption: 'Tabelle 7: Standard Operating Procedures'<br/>text: '| SOP-ZSD-06 | Kaltstart … | Kai Ostermann |'<br/>embedding: [0.0019, 0.0003, -0.0570, … ×1024]<br/>identifiers: ['SOP-ZSD-01' … 'SOP-CAAS-06']<br/>node_labels: ['kai ostermann', 'sop-zsd-06', …] (14)<br/>edge_ids: ['2aca7dfa9b3a135b', …] (7)")
  B3("💬 <b>bhb-nodes</b> _id 2bb722f565a0:Person_c148…<br/>type: Person · label: 'Kai Ostermann'<br/>attributes: {role_title: 'Verantwortlicher ZSD, IAM-Betrieb',<br/>  phone_ext: '1315', org_unit: 'Bereich IT-S 1'}<br/>chunk_ids: ['…-0001', '…-0002', '…-0003'] · pages: [1, 2]")
  B4("💬 <b>bhb-documents</b> _id BHB-PLT-0007<br/>title: 'Betriebshandbuch ZSD - …' · version: '2.3'<br/>root_system: 'Zentrale Sicherheitsdienste'<br/>counts: {chunks: 112, nodes: 250, edges: 154}<br/>graph.edges[i]: {id: '2aca7dfa9b3a135b',<br/>  source: Kai Ostermann, type: RESPONSIBLE_FOR,<br/>  target: SOP-ZSD-06, polarity: positive,<br/>  properties: {raci: 'verantwortlich'},<br/>  quote: 'SOP-ZSD-06 | Kaltstart … | Kai Ostermann',<br/>  provenance: {pages: [17], chunk_ids: ['…-0055']}}")
  B5("💬 <b>bhb-manifest</b> _id BHB-PLT-0007<br/>status: indexing → active<br/>run_id, doc_sha256, owner, started_at, finished_at<br/>counts · swept · embedding_model · history[]")

  ONTO -.- B0
  VOL -.- B1
  XC -.- B2
  XN -.- B3
  XD -.- B4
  XM -.- B5

  classDef container fill:#eef4ff,stroke:#3b6fd8,stroke-width:2px
  classDef store fill:#fff7e6,stroke:#d08a00
  classDef ext fill:#f3f3f3,stroke:#888,stroke-dasharray:4 3
  classDef bubble fill:#fffde7,stroke:#b9a100,stroke-dasharray:3 3,font-family:monospace,font-size:11px,text-align:left
  class DGS,OSI,CHAT container
  class OS,VOL store
  class EXT ext
  class B0,B1,B2,B3,B4,B5 bubble
```

### What each container takes in and gives out

| Container | Inputs | Steps (high level) | Outputs | Writes to |
|---|---|---|---|---|
| **dgs** | PDF · `ontology.yaml` · LLM, Embedding (and optional VLM) endpoints | convert → clean up → **fork**: (a) chunk + embed, (b) extract graph under the ontology schema → join the two on item ids | **two products in one `response.json`:** ① chunks with vectors, ② the graph JSON (nodes + edges, each with provenance) | shared volume only, **never OpenSearch** |
| **indexer** | the run directory · `ontology.yaml` | validate → lease → stamp reverse links → bulk upsert → verify → sweep old run → release | 4 kinds of records | OpenSearch (the **only** writer) |
| **OpenSearch** | bulk writes from the indexer | stores and searches (BM25 with German analyzer, k-NN HNSW, keyword term) | search hits, documents by id | — |
| **chat** | user question + identity headers · reads OpenSearch · Embedding + LLM | policy → rewrite → retrieve → prompt → stream (see [`RETRIEVAL-FLOW.md`](RETRIEVAL-FLOW.md)) | answer with citations `[BHB-PLT-0007 S. 17]` | SQLite (conversations only); read-only on OpenSearch |

**Why dgs does not write to OpenSearch:** it keeps the trust split clean. dgs talks to the model
endpoints and holds no database credentials, and only the indexer holds write rights (§8.2 of the
technical request). It also makes the expensive step (2–5 min, LLM) reusable: re-indexing a manual
from its run directory takes seconds and needs no model.

---

## 2. How the two dgs outputs are stored and linked in OpenSearch

dgs produces **chunks + vectors** and **the graph JSON**. The indexer splits that into four indices
and writes the links in **both directions**, so a search hit leads into the graph and a graph fact
leads back to the page that proves it.

```mermaid
flowchart LR
  subgraph RUN["response.json (from dgs)"]
    direction TB
    RC["chunks[]<br/>chunk_id · text · embedding · dom_paths"]
    RG["graph<br/>nodes[] · edges[]<br/>each with provenance.chunk_ids"]
  end

  subgraph OS["OpenSearch"]
    direction TB
    C[("<b>bhb-chunks</b><br/>1 doc per chunk<br/>_id = chunk_id")]
    N[("<b>bhb-nodes</b><br/>1 doc per entity per manual<br/>_id = sha12:node_id")]
    D[("<b>bhb-documents</b><br/>1 doc per manual · _id = doc_id<br/>metadata + markdown + <b>graph blob</b>")]
    M[("<b>bhb-manifest</b><br/>1 doc per manual · _id = doc_id")]
  end

  RC -->|"text, vector, pages, caption<br/>+ identifiers (regex)"| C
  RG -->|"reverse index:<br/>node_ids · node_labels ·<br/>node_types · edge_ids"| C
  RG -->|"each node: type, label, aliases,<br/>attributes, chunk_ids, degree"| N
  RG -->|"whole graph incl. edges<br/>(edges live only here)"| D

  C -. "chunk.node_ids → node" .-> N
  N -. "node.chunk_ids → chunk" .-> C
  D -. "edge.provenance.chunk_ids → chunk" .-> C
  M -. "status active = D and C are complete" .-> D

  classDef store fill:#fff7e6,stroke:#d08a00
  class C,N,D,M store
```

| Index | One record = | Key fields | Queried by the chat how |
|---|---|---|---|
| `bhb-chunks` | one searchable passage or whole table | `text`, `body_text`, `caption` (BM25, `de_text` analyzer) · `embedding` (knn_vector 1024, HNSW, lucene) · `identifiers`, `node_labels` (keyword, verbatim) · `node_ids`, `edge_ids` · `doc_id`, `page_numbers`, `heading_breadcrumb` | 4 channels in one `msearch`; `mget` by id for graph provenance |
| `bhb-nodes` | one entity in one manual | `type`, `label`, `aliases`, `attributes`, `identity_norm`, `chunk_ids`, `pages`, `degree` | inspection / `osi search`. The chat works from the graph blob in memory. |
| `bhb-documents` | one manual | `title`, `version`, `root_system`, `counts`, `embedding_model`, `markdown`, **`graph`** (nodes + edges with ids) | read once at start-up → in-memory union graph + label index; document list for the sidebar |
| `bhb-manifest` | the ingest state of one manual | `status` (`indexing` / `active` / `failed`), `run_id`, `doc_sha256`, `owner`, `counts`, `history` | the lock between indexer runs. It tells the chat that a manual is complete. |

**Edges have no index of their own.** They are stored in the graph blob of `bhb-documents` and
referenced by id from every chunk that proves them (`edge_ids`). The chat never searches edges. It
loads them into memory and walks them.

---

## 3. The records, in full

### 3.1 One chunk in `bhb-chunks`

```jsonc
{
  "chunk_id": "2bb722f565a0-0055",          // sha256(pdf)[:12] - running index → stable across runs
  "doc_id": "BHB-PLT-0007",  "run_id": "…",  "indexed_at": "2026-09-…",
  "kind": "table",
  "heading_breadcrumb": ["5 Betrieb", "5.5 Standard Operating Procedures"],
  "caption": "Tabelle 7: Standard Operating Procedures",
  "page_numbers": [17],
  "dom_paths": ["#/texts/339", "#/tables/11"],   // DoclingDocument item ids = the join key
  "token_count": 412,
  "text": "5 Betrieb\n5.5 Standard Operating Procedures\nTabelle 7: …\n| SOP | Titel | Auslöser | Verantwortlich | Dauer | Abstimmung |\n…\n| SOP-ZSD-06 | Kaltstart der Sicherheitsdienste | Notfall, Stromabschaltung, Wiederanlauf | Kai Ostermann | 90 min bis Schritt 7 | Reihenfolge nach SOP-CAAS-06 |",
  "embedding": [0.0019056769, 0.00029982728, -0.05702861, 0.026187675, "… 1024 floats"],
  "embedding_model": "intfloat/multilingual-e5-large",
  "identifiers": ["SOP-CAAS-06", "SOP-ZSD-01", "SOP-ZSD-02", "…", "SOP-ZSD-06"],
  "node_ids":    ["Person_c148c1f00683d662", "Procedure_05f570dc41890cfe", "… 14 nodes"],
  "node_labels": ["kai ostermann", "keycloak", "marcel ebert", "sop-zsd-06", "…"],
  "node_types":  ["ImpactStatement", "Person", "Procedure", "System"],
  "edge_ids":    ["2aca7dfa9b3a135b", "332792a2901cf812", "… 7 edges"]
}
```

`text`/`embedding` come from dgs output ①. `node_*`/`edge_ids` are the **reverse index** that the
indexer derives from output ②. `identifiers` are extracted by the indexer with the ontology's regexes.

### 3.2 One node in `bhb-nodes`

```jsonc
{
  "_id": "2bb722f565a0:Person_c148c1f00683d662",
  "doc_id": "BHB-PLT-0007",
  "node_id": "Person_c148c1f00683d662",  "type": "Person",  "label": "Kai Ostermann",  "aliases": [],
  "attributes": { "role_title": "Verantwortlicher ZSD, IAM-Betrieb", "phone_ext": "1315",
                  "email": "iam-betrieb@bavd.bund.de", "org_unit": "Bereich IT-S 1" },
  "quote": "Kai Ostermann (Bereich IT-S 1, Durchwahl 1315)",
  "chunk_ids": ["2bb722f565a0-0001", "2bb722f565a0-0002", "2bb722f565a0-0003"],
  "pages": [1, 2],  "match": "verbatim",  "degree": 4
}
```

### 3.3 One manual in `bhb-documents` (with one edge of its graph blob)

```jsonc
{
  "doc_id": "BHB-PLT-0007",  "name": "Betriebshandbuch_ZSD.pdf",  "pages": 29,  "tables": 22,
  "title": "Betriebshandbuch ZSD - Zentrale Sicherheitsdienste",  "version": "2.3",
  "root_system": "Zentrale Sicherheitsdienste",
  "counts": { "chunks": 112, "nodes": 250, "edges": 154, "documents": 1 },
  "embedding_model": "intfloat/multilingual-e5-large",  "embedding_dim": 1024,
  "markdown": "BETRIEBSHANDBUCH\n\n## ZSD - Zentrale Sicherheits­ dienste …",
  "graph": {
    "nodes": [ "… 250 × {id, type, label, attributes, aliases, quote, provenance}" ],
    "edges": [
      { "id": "2aca7dfa9b3a135b",
        "source": "Person_c148c1f00683d662",      // Kai Ostermann
        "type": "RESPONSIBLE_FOR",
        "target": "Procedure_05f570dc41890cfe",   // SOP-ZSD-06 Kaltstart der Sicherheitsdienste
        "polarity": "positive",  "qualifier": null,
        "properties": { "raci": "verantwortlich", "is_deputy": false },
        "quote": "SOP-ZSD-06 | Kaltstart der Sicherheitsdienste | Notfall, Stromabschaltung, Wiederanlauf | Kai Ostermann",
        "provenance": { "pages": [17], "chunk_ids": ["2bb722f565a0-0055"] } }
    ],
    "meta": { "ontology": {"name": "bavd-ops-manual-ontology", "version": "1.0.0"}, "…": "…" }
  },
  "degraded": { "vlm": false, "embeddings": false, "graph": false }
}
```

### 3.4 The ingest record in `bhb-manifest`

```jsonc
{
  "doc_id": "BHB-PLT-0007",
  "status": "active",                       // indexing → active   (or → failed, with "error")
  "run_id": "…", "previous_run_id": "…",    // same run_id again = no-op
  "doc_sha256": "2bb722f565a0ff49…", "doc_name": "Betriebshandbuch_ZSD.pdf",
  "owner": "<hostname>:<pid>", "started_at": "…", "finished_at": "…",
  "counts": { "chunks": 112, "nodes": 250, "edges": 154, "documents": 1 },
  "swept": { "chunks": 0, "nodes": 0 },     // records of the previous run removed
  "embedding_model": "intfloat/multilingual-e5-large",
  "history": [ { "run_id": "…", "replaced_at": "…" } ]
}
```

---

## Plan vs. current

| Plan (`technical_request.md`) | Code today (2026-09-30) |
|---|---|
| Chat notices a new manual within ~5 min, **document list and in-memory graph** refresh without restart (§1, §9) | Document list: yes, `Catalog` caches `bhb-documents` for 300 s. Graph: `Retriever.reload_graph()` exists, but nothing in the chat calls it on a timer or on the manifest yet, so the graph is loaded at start-up only. |
| Chat polls the **manifest** for `active` | The chat reads `bhb-documents` directly; the manifest is used by the indexer only. |
| dgs → indexer as two operator steps (§9) | As planned (`osi ingest <run-dir>`). Self-service upload from the chat (flow 7) is an open scope decision (§10 #6). |
| Embedding `multilingual-e5-large` everywhere | The three prototype manuals are still `bge-m3` and are re-indexed before go-live (§3.1). |
