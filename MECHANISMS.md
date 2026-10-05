# The two mechanisms

How the knowledge graph is bound to the text at indexing time, and how a question walks from text
into the graph and back at query time. Everything here is behaviour of the running system; the
numbers and traces are taken from the indexed corpus (ZSD `BHB-PLT-0007`, CaaS `BHB-PLT-0001`,
Event-System `BHB-PLT-0042`) on 2026-09-14.

| | Mechanism | One sentence |
|---|---|---|
| **A** | **Binding** (indexing) | One PDF is parsed once, then cut twice — once into searchable chunks, once into slices for the extraction model — and the two halves are joined afterwards through the document's own item ids. |
| **B** | **Walking** (retrieval) | A search hit is not just a passage: it names the entities it proves, so retrieval steps from chunk into the graph, expands one hop, and comes back out into the passages that prove the facts it found. |

Terms printed `like this` are defined in the [glossary](#glossary) at the end.

---

## Mechanism A — Binding the graph to the text

### The problem

An extracted fact is only useful in this system if it can be **cited down to the page**. So every
node and every edge has to point back at the exact passage it came from. The difficulty: the
component that extracts the graph and the component that produces the searchable chunks are two
different libraries with two different notions of "a piece of text". They never see each other's
output.

### The shared artefact

Both halves read the **same object**: the `DoclingDocument` that docling produces from the PDF. It
is a tree of numbered items — `#/texts/40`, `#/tables/17`, `#/pictures/3` — each carrying its text,
page number, bounding box and heading level. Those numbers are the join key of the whole mechanism.

Before the fork, the document is repaired once so that both halves see the same clean text:

| Clean-up | What it does |
|---|---|
| `strip_page_furniture` | drops the `TESTDOKUMENT ·` banner line |
| `strip_repeated_furniture` | drops text repeated in the page margins on ≥ 3 pages (running headers/footers) |
| `normalize_heading_levels` | rebuilds the heading hierarchy from the section numbering |
| `dehyphenate_table_cells` | rejoins `bavd- issuing-ca-3` split by a PDF line wrap |
| `infer_captions` | gives a caption-less table the caption of the table it continues across a page break |
| picture descriptions | a vision model's description is written into the picture item |

### The fork

```
                              PDF
                               │  docling convert  (layout, TableFormer, OCR de/en)
                               ▼
                      DoclingDocument
                      items: #/texts/40, #/texts/41, #/tables/17, …
                               │  clean-up (furniture · headings · captions · figure text)
                               ▼
        ┌──────────────────────┴───────────────────────────┐
        │ our chunker                                      │ save_as_json → docling-graph
        ▼                                                  ▼
  HybridChunker                                     its own internal chunker
  512 tokens, e5 tokenizer                          512 tokens, MiniLM tokenizer
  tables/pictures kept whole                        slices are EPHEMERAL
  text peers under one heading merged                      │
        │                                                  │  each slice → LLM
        │                                                  │  forced into the JSON schema
        │                                                  │  compiled from ontology.yaml
        ▼                                                  ▼  processing_mode: many-to-one
  chunks[]  ──► embeddings (1024-dim)              nodes + edges, deduplicated by
  each keeps  dom_paths: ["#/texts/40", …]         identity rule, each keeping
  each keeps  chunk_id:  "2bb722f565a0-0007"       provenance.refs: ["#/texts/40", …]
        │                                                  │
        └────────────────────► materialize() ◄─────────────┘
                          join on the item ids
                                    ▼
                    node.provenance.chunk_ids = ["2bb722f565a0-0007"]
                    node.provenance.pages     = [4]        (derived from the chunk)
```

**The extraction slices are thrown away.** They are never embedded, never stored, never indexed.
They exist only for the duration of the LLM calls. There is exactly **one** surviving set of chunks —
the ones that get vector-searched — and node provenance points into that set.

Verified on the ZSD run:

```
response.json keys : document · markdown · chunks · graph · degraded · errors · timings · versions
chunks 112 · graph nodes 250 · edges 154
distinct chunk_ids referenced by nodes :  92
of those, NOT present in chunks[]      :   0     ← no dangling reference
chunks that no node references         :  20     ← prose without an extracted entity
```

### Why two chunkers instead of one

They are bounded by different things and cannot be merged without damaging one of them:

| | retrieval chunks | extraction slices |
|---|---|---|
| Hard limit | the **embedding model's** 512-token input — a longer chunk would be silently truncated by the encoder | what usefully fits into one schema-constrained LLM call |
| Tokenizer | `intfloat/multilingual-e5-large` (the model that will embed it) | `all-MiniLM-L6-v2` (docling-graph's default) |
| Must keep whole | tables and pictures, so a citation can name "Tabelle 12, S. 19" | nothing — a slice is scaffolding |
| Lifetime | stored and searched forever | discarded after the call |

Keeping them separate also keeps `docling-graph` a black box: it gets a document, a schema and a
policy, and returns typed objects with item references. If it changes its internal chunking, nothing
on our side breaks.

### The join, in two flavours

**Nodes — structural, exact.** docling-graph reports `provenance.refs` = the document items the
entity was extracted from. Our chunker built a `self_ref_index` while chunking: `item → [chunk_id]`.
`materialize()` walks the refs through that map. No text comparison, no similarity, no guessing.

**Edges — by quote, with a fallback.** An edge's evidence is reported as the model's verbatim
`quote`, not as an item. So the quote is normalised and matched against the chunk texts:

```python
def find(self, quote):
    q = norm_key(quote)                       # casefold, ß→ss, whitespace collapsed
    if len(q) < 12:  return []                # too short to be evidence
    hits = [cid for cid, text in self._texts if q in text]        # exact substring
    if hits: return hits
    window = q[:60]                                                # tolerate small model edits
    return [cid for cid, text in self._texts if window in text]
```

If even that fails, the edge inherits the chunks of its **source node** — so an edge is never left
without provenance.

### The reverse direction, written at ingest

`materialize()` gives the forward link (node → chunks). The **backward** link (chunk → nodes) is
written later by the indexer, `osi`, which walks every node's and every edge's `chunk_ids` and
stamps the graph neighbourhood onto the chunk document. For an edge it stamps **both endpoints**,
because the sentence proving an edge is not always in either node's own chunk list.

A real chunk record from the running index:

```
chunk_id     2bb722f565a0-0007        doc_id BHB-PLT-0007      pages [4]
node_ids     ["CertificateAuthority_6ed3c838…", "Component_9ac69fd3…", "Document_ddfceb8b…", "Namespace_2a98e99b…"]
node_labels  ["BAVD Test CA 1", "BHB-PLT-0007", "Bereich IT-S 1", "Bereich IT-S 1 - Informationssicherheit und Basisdienste"]
edge_ids     ["93bb302e9b3952a8", "9548226fa4fbd941"]
identifiers  []
```

This is what makes Mechanism B cheap: a search hit already knows which entities and facts it proves;
no lookup is needed to step into the graph.

### The relation is many-to-many

It is not "this chunk belongs to that entity". Measured over the ZSD run:

```
nodes per chunk  : min 1 · median 5 · max 33      ← one large table proves 33 entities
chunks per node  : min 1 · median 2 · max  9      ← one entity is documented in several places
nodes with no chunk reference : 0
```

### Worked example A

```
① docling parses page 4 of the ZSD manual into items #/texts/40 and #/texts/41

② our chunker emits
     chunk_id   2bb722f565a0-0007        kind text       page_numbers [4]
     dom_paths  ["#/texts/40", "#/texts/41"]
     text       "1 Dokumentinformation / 1.1 Zweck, Zielgruppe, Geltungsbereich /
                 Dieses Handbuch beschreibt den Betrieb der Zentralen Sicherheitsdienste …"
     embedding  1024 floats

③ docling-graph, from its own slice covering the same items, returns
     node   System "ZSD - Zentrale Sicherheitsdienste"
     provenance.refs = ["#/texts/40", "#/texts/41"]

④ materialize() looks both refs up in self_ref_index → chunk 2bb722f565a0-0007
     node.provenance.chunk_ids = ["2bb722f565a0-0007"]
     node.provenance.pages     = [4]                      ← derived from the chunk

⑤ osi writes the reverse link onto the chunk
     chunk.node_ids += ["System_…"]        chunk.node_labels += ["ZSD - Zentrale Sicherheitsdienste"]

⑥ result: the statement "ZSD is described in BHB-PLT-0007" is citable as [BHB-PLT-0007 S. 4],
   and the passage on page 4 knows it proves that entity.
```

### When it fails

Nothing in this mechanism half-writes:

| Failure | Behaviour |
|---|---|
| LLM call fails or the output does not validate | retried (max 2), then the **whole graph step** is marked `degraded.graph`; markdown, chunks and vectors are kept and the manual is **still indexed and searchable** |
| an edge points at an entity that was never extracted | reported as `unresolved_target` — **never** materialised as a stub node |
| a positive and a negative edge of the same type between the same nodes | reported as a **conflict**; neither overwrites the other |
| the quote of an edge matches no chunk | falls back to the source node's chunks |
| conversion fails | the only hard error — nothing is produced |

A result is written to the content-addressed cache **only when nothing degraded**.

---

## Mechanism B — Walking from text into the graph and back

### The problem

The most valuable statements in an operations manual are not inside the passage that mentions your
keyword. "What happens when Vault is sealed" is answered by an impact matrix in one manual and a
dependency chain in another; the most valuable negative finding — *VPP is not affected* — sits in a
table cell that no edge leads to. A ranked list of similar passages cannot produce that.

### The full path

```
question
   │
   ▼ ① ANALYZE                                             no I/O, no model
   │   identifiers  ← 6 ontology regexes over the question
   │   labels       ← word n-grams (4→1) against the in-memory label index
   │   partial      ← nodes whose label contains ≥ 2 question words (anchored)
   │
   ▼ ② EMBED  (encoder, not a generator)
   │
   ▼ ③ FOUR CHANNELS, one msearch, k = 20 each          ALL of them return CHUNKS
   │   knn · bm25 · identifier · label
   │
   ▼ ④ RRF               score = Σ 1/(60 + rank in that list)
   │
   ▼ ⑤ GUARDRAIL         weak? → answer without calling the model, stop here
   │
   ▼ ⑥ GRAPH CHANNEL  (slow mode only)
   │      seeds        = top 5 fused + top 2 of every channel
   │      start nodes  = resolved labels → partial labels → node_ids of the seeds   (cap 30)
   │      expand       = 1 hop, ALL 32 relations, BOTH directions
   │      ├─ facts         ≤ 40   the edges, rendered with polarity, qualifier, quote, page
   │      ├─ entity cards  ≤ 15   node attributes (this is how a degree-0 node reaches the prompt)
   │      └─ chunks        ≤ 15   fetched by mget, added as a FIFTH ranked list → RRF again
   │                              the chunks of the 2 best facts are pinned into the result
   ▼ ⑦ GROUP + CITE      table parts with the same caption become ONE source with a page range
   ▼ ⑧ PROMPT            entities → facts → sources, 6 000-token budget
```

Two modes: **fast** stops after ④, **slow** runs the graph channel. Nothing between the question and
the finished prompt is a language model — identifiers by regex, entities by string match, similarity
by an encoder, order by arithmetic.

### Step ① — what the question is turned into

The label index is built at start-up from the `norm_key` of every node label **and every alias** in
the union graph of all indexed manuals. The question is tokenised and every n-gram of length 4 down
to 1 is looked up; the longest match wins and consumes its tokens. Unigrams need ≥ 3 characters and
must not be German stop words — the stop list contains not only articles and question words but
function words that happen to occur inside labels (`passiert`, `läuft`, `hängt`, `dazu`).

`partial label matches` exist for one reason: the reified `ImpactStatement` nodes are labelled
"Vault versiegelt | VPP". No exact match and no edge reaches them, so a node whose label contains at
least **two** question content words is also collected — provided one of them is an **anchor** (a
word from an exactly resolved label or an identifier). Without the anchor rule, "Dispatcher neu
starten" pulled in every "… neu starten" statement in the corpus.

### Step ③ — why exact channels exist at all

| Channel | Query | Why it is not redundant |
|---|---|---|
| **knn** | HNSW/cosine over 1024-dim vectors, `doc_id` filter **inside** the k-NN clause | meaning, paraphrase, synonyms |
| **bm25** | `multi_match` on `text^2, body_text, caption`, `de_text` analyzer | wording, rare technical terms |
| **identifier** | `term` on the `identifiers` keyword field | a German analyzer splits `CAASUP-0342` into `caasup` + `0342`, which matches every CaaS ticket; the keyword field stores it **verbatim** |
| **label** | `term` on the `node_labels` keyword field (lowercased) | an exact entity or alias mention, including multi-word labels |

Stop words and stemming apply **only** to BM25. The identifier and label fields are keyword fields
and are not analysed at all — that is the entire point of them.

### Step ④ — fusion by rank, not by score

BM25 scores, cosine similarities and boolean matches are not comparable, so only ranks are used:

```
score(chunk) = Σ over every list that found it   1 / (60 + rank in that list)
```

A chunk at rank 1 in one list scores `1/61 = 0.0164`. A chunk at rank 10 in **two** lists scores
`2/70 = 0.0286`. **Agreement beats a single strong hit** — which is the whole point, and also the
reason the graph list needs the pinning rule below.

### Step ⑥ — what one hop actually yields

Chunks are the **last and smallest** of the three outputs. The primary product is facts: a fact is
already citable on its own, because it carries the quote, the document, the page and the edge id.

The chunks are collected in a strict order and then cut:

```python
for f in facts:          add(f.chunk_ids)     # 1. chunks of the KEPT facts, best fact first
for nid in label_nodes:  add(node.chunk_ids)  # 2. then the exactly matched entities
for nid in reached:      add(node.chunk_ids)  # 3. then the neighbours those facts reached
return out[:15]
```

So the ranking of the facts propagates into the chunk selection: what survives the cap proves the
best facts. Neighbour chunks only enter if there is room left. **Not** every chunk of every touched
node — measured on the example below, that would have been 52 chunks against a cap of 15.

Each fetched chunk records *which relation brought it* (`via DEPENDS_ON from Vault`), so the user
interface can show why it is in the list.

Finally, because a graph-only chunk scores a single `1/61` and loses against every two-channel hit,
the provenance chunks of the **two best facts are pinned** into the final list, replacing the tail.

### The caps, in one place

| Cap | Value | What it bounds |
|---|---|---|
| `k_per_channel` | 20 | hits requested per search channel |
| `graph_seed_hits` / `graph_seed_per_channel` | 5 / 2 | which chunks may contribute start nodes |
| `graph_max_start_nodes` | 30 | entities the hop starts from |
| `graph_max_facts` | 40 | edges rendered as facts |
| `graph_max_entities` | 15 | entity cards |
| `graph_max_chunks` | 15 | provenance chunks fetched by `mget` |
| `graph_min_sources` | 2 | fact chunks pinned into the final list |
| `final_k` | 10 | chunks in the answer context |
| `context_token_budget` | 6 000 | the rendered context block |

### Worked example B — "Was passiert, wenn Vault versiegelt ist?"

A real trace from the running system (three manuals indexed, slow mode).

**① Analyze** — no model, no I/O (0 ms):

```
identifiers      : []                       ← the question carries none
label candidates : ["vault"]                → resolved to 6 nodes (System, Component, Host, Term, …)
partial labels   : "Vault versiegelt | VPP", "Vault versiegelt | Mars Dokumentendienste",
                   "Vault versiegelt | Event-System 2.0", "Vault versiegelt | Observability", …
```

**③ Channels** — three fire (no identifier in the question), 20 hits each.

**⑥ Graph** — 30 start nodes, one hop:

```
nodes labelled "vault"        :  6
start nodes after selection   : 30
nodes touched by the hop      : 46
chunks those nodes reference  : 52          ← "all referenced chunks" would be this
chunks actually fetched       : 15          (cap)
facts kept                    : 40
entity cards                  : 15
```

Facts 1 and 2 — the two negations, both from ZSD page 19, both from one chunk:

```
Vault —DEPENDS_ON (hängt ab von)→ Keycloak (dependency_kind=identitaet): NICHT (für Vault-Unseal)
   — „Der Vault-Unseal erfolgt manuell mit drei von fünf Anteilen (Tabelle 14) und benötigt weder
      PKI noch IAM, sondern nur die Anteile aus dem Tresor des Bereichs IT-S 1.“
   [BHB-PLT-0007 S. 19; Kante f65b2a035251c673]

Vault —DEPENDS_ON (hängt ab von)→ PKI (dependency_kind=zertifikat): NICHT (für Vault-Unseal)  …
```

The showcase entity card — a node of **degree 0** that no edge can reach, brought in by a partial
label match and rendered from its attributes alone:

```
Vault versiegelt | VPP (ImpactStatement) — severity: keine; symptom: keine;
   event: Vault versiegelt; affected_system: VPP        [BHB-PLT-0001 S. 12, 15, 19]
```

**④ + ⑥ Fusion** — the final ten, with the arithmetic visible:

```
rank  chunk                   doc    page  score   found by
 1    fa9517fb84f3-0035       0001   12    0.0601  knn#10, bm25#15, label#1, graph#2
 2    2bb722f565a0-0071       0007   22    0.0560  knn#12, bm25#13, label#13, graph#8
 3    fa9517fb84f3-0046       0001   15    0.0465  knn#3,  bm25#9,  label#2
 4    fa9517fb84f3-0074       0001   22    0.0445  knn#1,  bm25#4,  label#20
 5    fa9517fb84f3-0076       0001   22    0.0422  knn#20, bm25#5,  graph#10
 6    2bb722f565a0-0037       0007   11    0.0413  knn#14, bm25#19, label#6
 7    fa9517fb84f3-0073       0001   21    0.0405  knn#16, bm25#8,  label#19
 8    2bb722f565a0-0072       0007   22    0.0318  knn#4,  bm25#2
 9    2bb722f565a0-0108       0007   29    0.0311  knn#2,  bm25#7
10    2bb722f565a0-0062       0007   19    0.0291  knn#19, graph#1
```

Three things to read out of that table:

- **Rank 1 was never a top hit anywhere.** knn#10, bm25#15 — mediocre in every single channel. Four
  lists agreeing put it first: `1/70 + 1/75 + 1/61 + 1/62 = 0.0601`.
- **Rank 4 was the best vector hit in the corpus** (knn#1) and finished fourth:
  `1/61 + 1/64 + 1/80 = 0.0445`. A single strong signal is not enough.
- **Rank 10 is the page that proves the negations** — the chunk quoted by facts 1 and 2. The vector
  search barely saw it (knn#19) and BM25 missed it entirely; the graph put it first:
  `1/79 + 1/61 = 0.0291`. It scraped into the final ten on its own score here, and the pinning rule
  is what guarantees it when the margin goes the other way. Without it the prompt would state a
  dependency negation whose source page was not shown to the user.

**Timings** (deterministic parts, this run): analyze 0 ms · search 56 ms · fuse 1 ms · graph 44 ms.
The embedding call dominates the wall clock and is the only network hop before the answer.

**Result**: 40 facts, 15 entity cards, 10 grouped sources, 22 citations — and only now is a language
model called, with a context in which every line carries a document and a page.

---

## How the two mechanisms meet

```
MECHANISM A (once per manual)              MECHANISM B (once per question)
─────────────────────────────              ──────────────────────────────
item id  →  chunk_id                       chunk hit  →  chunk.node_ids      (A's reverse index)
node     →  chunk_ids                                 →  1 hop in the graph
chunk    →  node_ids, edge_ids                        →  facts + cards
                                                      →  node.chunk_ids      (A's forward index)
                                                      →  mget → 5th list → RRF
```

Mechanism B is only possible because Mechanism A wrote the links in **both** directions. Everything
B does with the graph is a dictionary lookup in memory; the only network calls in a turn are one
embedding request, one `msearch`, one `mget` and the model call at the end.

---

## Glossary

Terms used above, in the order they first appear.

### Mechanism A

| Term | Meaning |
|---|---|
| **docling** | open-source PDF parser: layout, tables (TableFormer), OCR, figures. Produces the `DoclingDocument`. |
| **docling-graph** | separate open-source library that drives the extraction model against a schema and returns typed nodes and edges. A black box to this system. |
| **`DoclingDocument`** | the parsed document as a tree of numbered items with text, page, bounding box and heading level. The artefact both halves of the fork read. |
| **item id / `self_ref` / `dom_path`** | the address of one item in that tree: `#/texts/40`, `#/tables/17`. **The join key of Mechanism A.** |
| **`self_ref_index`** | the map `item id → [chunk_id]` built by our chunker while chunking; the lookup table that turns extraction provenance into chunk references. |
| **`HybridChunker`** | docling's structure-aware chunker used for the **retrieval** chunks: token-budgeted with the embedding model's tokenizer, tables and pictures kept whole, text peers under one heading merged. |
| **extraction slice** | docling-graph's *internal* chunk. Sent to the LLM, then discarded. Never embedded, stored or indexed. |
| **`chunk_id`** | `<sha256(file)[:12]>-<index>`, e.g. `2bb722f565a0-0007`. Stable across runs of the same PDF — the property that makes re-indexing idempotent. |
| **`provenance`** | what makes a fact citable: `document_id`, heading breadcrumb, `page`, `table_ref`, `figure_ref`, `dom_paths`, `chunk_ids`, `confidence`. On every node and every edge. |
| **`quote`** | the verbatim sentence (≤ 300 chars) the model was shown; for edges it is also the key used to find the proving chunk. |
| **`polarity`** | `positive` or `negative` on **every** edge. "A does *not* depend on B" is a negative edge, not a missing one. |
| **`qualifier`** | the free-text restriction or **reason** on an edge — for a negative edge, *why* the relation does not hold ("für Vault-Unseal"). |
| **identity rule** | the ontology's rule for when two mentions are the same node (casefolded label, ticket id, hostname, system-scoped key). Deduplication is deterministic; no model decides sameness. |
| **`ImpactStatement`** | a reified cell of an impact matrix: "event X at A affects B like so", with `severity` (where `keine` is a statement, not missing data). Often **degree 0** — reachable only as an entity card. |
| **`unresolved_target`** | an edge pointing at an entity that was never extracted. Reported, never materialised as a stub node. |
| **`degraded`** | per-stage flag (`vlm`, `embeddings`, `graph`). A degraded stage does not fail the run; only conversion is a hard error. A degraded result is not cached. |
| **reverse index** | `node_ids`, `node_labels`, `node_types`, `edge_ids` stamped onto every chunk by `osi` at ingest — the chunk → graph direction. |
| **`run_id`** | fingerprint of the canonical output. An identical re-run is recognised as a no-op; a new extraction replaces the manual as a whole. |

### Mechanism B

| Term | Meaning |
|---|---|
| **channel** | one of the four searches that run in a single `msearch`: `knn`, `bm25`, `identifier`, `label`. All four return **chunks**. |
| **`knn_vector` / HNSW** | the vector field and its index: 1024 dimensions, cosine, engine **lucene** (filters *during* the search instead of post-filtering). |
| **`de_text`** | the German analyzer: standard tokenizer → lowercase → German stop words → `german_normalization` (umlauts, ß) → **`light_german`** stemmer (the full stemmer over-stems technical vocabulary). BM25 only. |
| **`identifiers`** | keyword field holding what the six ontology regexes matched in the chunk, **verbatim** (`ZSDSUP-0247`, `SOP-ZSD-05`, `FW-CAAS-004`, hostnames). |
| **`node_labels`** | keyword field (lowercased) holding the labels and aliases of every node the chunk proves — what the label channel matches against. |
| **`norm_key`** | the shared normalisation (casefold, ß→ss, whitespace collapsed) applied to labels at index time and to question n-grams at query time, so both sides agree. |
| **label index** | the in-memory dictionary `norm_key → node ids`, built at start-up from every label and alias of the union graph. |
| **partial label match** | a node whose label contains ≥ 2 content words of the question, **anchored** by a word from an exactly resolved label or an identifier. How degree-0 `ImpactStatement`s are found. |
| **`msearch` / `mget`** | OpenSearch multi-search (all channels in one round trip) and multi-get (fetching the graph's provenance chunks by id). |
| **RRF** | reciprocal rank fusion, client-side: `score = Σ 1/(60 + rank)`. Ranks only, because BM25 scores and cosine similarities are not comparable. Rank constant 60. |
| **guardrail** | the rule that refuses **without calling the model**: strong iff an identifier matched or a label resolved; weak if there are no hits, BM25 returned nothing, or no top-3 chunk was found by ≥ 2 *search* channels. The graph channel never counts as evidence. |
| **fast / slow** | fast stops after fusion (four channels); slow adds the graph channel. Exposed as a toggle so the graph's contribution is visible. |
| **seed** | a chunk allowed to contribute start nodes: the top 5 fused plus the top 2 of every channel (so a k-NN#2-only table still seeds). |
| **start node** | an entity the hop starts from: resolved labels → partial matches → the `node_ids` of the seeds, ranked and capped at 30. |
| **expansion** | one hop over **all 32 relation types in both directions** from the start nodes. No allowlist, no depth 2. |
| **cue table** | regexes over the question's wording (`zuständig|verantwortlich|eskal` → `RESPONSIBLE_FOR, ESCALATES_TO` first, …) that **order** facts and start nodes. Nothing is excluded, and **no model is involved**. |
| **fact** | a rendered edge: `source —RELATION (deutsches Label)→ target (properties): NICHT (qualifier) — "quote" [BHB-… S. n; Kante <edge_id>]`. |
| **entity card** | a node rendered from its attributes, one occurrence per manual side by side when manuals disagree. The only way a degree-0 node reaches the prompt. |
| **`via`** | the recorded evidence for a hit: `knn#2 bm25#1 identifier#3(ZSDSUP-0247)` for search hits, `DEPENDS_ON from Vault` for graph hits. |
| **pinning** (`graph_min_sources`) | the provenance chunks of the two best facts are forced into the final list, because a graph-only chunk scores a single `1/61` and would otherwise always lose. |
| **group** | table parts sharing document and caption merged into **one** source with a page range, header row printed once. |
| **`doc_ids` filter** | the manuals a user's group may read — pushed *into* the search (inside the k-NN clause, as a `bool.filter` elsewhere), not applied to the display. |

---

## Where to read the code

| Mechanism | File |
|---|---|
| A · fork and orchestration | `docling-graph/src/docling_graph_service/pipeline.py` |
| A · retrieval chunks, `self_ref_index` | `docling-graph/src/docling_graph_service/chunking.py` |
| A · extraction config, join, quote matching | `docling-graph/src/docling_graph_service/graph.py` |
| A · ontology → schema compilation | `docling-graph/src/docling_graph_service/ontology.py` |
| A · reverse index at ingest | `opensearch-index/src/opensearch_index/transform.py` |
| B · the eight steps | `retrieval/src/rag_retrieval/retriever.py` |
| B · question analysis, label matching | `retrieval/src/rag_retrieval/query.py` |
| B · in-memory graph, `expand()` | `retrieval/src/rag_retrieval/graph.py` |
| B · facts, cards, cue table, chunk selection | `retrieval/src/rag_retrieval/facts.py` |
| B · fusion | `retrieval/src/rag_retrieval/fusion.py` |
| B · guardrail | `retrieval/src/rag_retrieval/guardrail.py` |
| B · context and prompt | `retrieval/src/rag_retrieval/prompt.py` |
