# OpenSearch-Indizes und Abfragen (aktuelle Lösung)

Stand 2026-10-08. Die vier Indizes der **laufenden** Lösung (OpenSearch 3.8.0, k-NN-Plugin, Engine `lucene`):
welche Felder jeder Index hat, woher jedes Feld kommt, welche Abfragen ihn treffen und was Python danach mit dem
Ergebnis macht. Nicht behandelt: die SQLite-Alternative (`SUCHSPEICHER-VERGLEICH.md`).

Maßgeblich ist der Code: `opensearch-index/src/opensearch_index/mappings.py` (Schema), `transform.py`
(Herkunft der Felder), `retrieval/src/rag_retrieval/search.py` + `retriever.py` (Abfragen des Chats),
`opensearch-index/src/opensearch_index/search.py` + `indexer.py` (Abfragen von `osi`).

Lesehilfe:

- **OpenSearch kennt keinen JOIN.** Datensätze verschiedener Indizes sind nur über IDs verbunden (`doc_id`,
  `chunk_id`, `node_id`). Jeder „Join“ unten passiert in Python, indem IDs nachgeladen werden.
- **Alias → physischer Index.** Der Code benutzt nur den Alias (`bhb-chunks`); der physische Index heißt
  `bhb-chunks-v1` (`MAPPING_VERSION = 1`). Eine Mapping-Änderung legt `-v2` an und hängt den Alias um.
- Alle Mappings sind `dynamic: strict`: ein Feld, das nicht im Mapping steht, wird beim Indexieren abgelehnt.
- `kw` = `keyword` (exakter Wert, nicht analysiert). `text(de_text)` = analysiert mit dem deutschen Analyzer
  (Standard-Tokenizer → Kleinschreibung → deutsche Stoppwörter → `german_normalization` → Stemmer `light_german`).
  `+ .keyword` = dasselbe Feld zusätzlich als Keyword-Unterfeld. `(nicht indexiert)` = liegt in `_source`, ist
  aber nicht durchsuchbar. `(disabled)` = undurchsichtiger JSON-Blob in `_source`, wird nicht geparst, nicht
  durchsuchbar.

## 0. Überblick

| Index (Alias) | Ein Datensatz = | `_id` | Geschrieben von | Gelesen vom Chat (`rag_retrieval`) | Gelesen von `osi` |
|---|---|---|---|---|---|
| `bhb-chunks` | ein Textabschnitt (Chunk) eines Handbuchs | `chunk_id` | `osi ingest` (bulk) | **ja**: 4 Suchkanäle + `mget` | Testabfragen, Zählungen, Sweep |
| `bhb-nodes` | eine Graph-Entität *je Dokument* (dieselbe Entität in zwei Handbüchern = zwei Datensätze) | `{sha12}:{node_id}` | `osi ingest` (bulk) | **nein** | `node_lookup`, Aggregation geteilter Knoten, Sweep |
| `bhb-documents` | ein Handbuch, inkl. des **gesamten Graphen als JSON-Blob** | `doc_id` | `osi ingest` (bulk) | **ja**: `match_all` einmal beim Start / Reload | `get` per ID |
| `bhb-manifest` | Ingest-Buchführung je Handbuch (Status, Lauf, Zählungen) | `doc_id` | `osi ingest` (create/update) | **nein** | `get`, `term`, `match_all` |

Wo die Indizes angelegt werden: `osi bootstrap` (`opensearch-index/src/opensearch_index/cli.py:61`) →
`Indexer.bootstrap()` (`indexer.py:115`) → `client.indices.create(...)` (`indexer.py:128`) mit den Bodies aus
`mappings.py:257` `index_bodies()`; Größen und Namen kommen aus `opensearch-index/config.yaml`.

```text
response.json ──osi ingest──► bhb-chunks ◄── 4 Kanäle + mget ── Chat
(docling-graph)              bhb-nodes                              │
                             bhb-documents ◄── match_all (graph) ───┘
                             bhb-manifest  (nur osi)
```

## 1. `bhb-chunks`

Einstellungen: `index.knn: true`, 1 Shard, 0 Replikate, Analyzer `de_text`, Normalizer `lc` (Kleinschreibung + Trim).

### 1.1 Felder

`c` = das Chunk-Objekt `chunks[i]` in `response.json`. `G` = `graph` in `response.json`. `osi` = Wert, den der
Indexer beim Ingest setzt (Konfiguration `OSI__*` oder berechnet).

| Feld | Typ | Herkunft |
|---|---|---|
| `chunk_id` | kw (= `_id`) | `c.chunk_id` (`{sha12}-{nnnn}`) |
| `doc_id` | kw | **osi**: je Handbuch aufgelöst, in dieser Reihenfolge: `--doc-id`-Override → Ontologie `meta.documents` nach Dateiname → genau ein Regex-Treffer der Dokument-ID auf Seite 1 → `DOCUMENTS`-Kante in `G`. In allen vier Indizes gleich. |
| `doc_sha256` | kw | `document.sha256` |
| `run_id` | kw | **osi**: Fingerabdruck aus (Inhalt der Response, Kanten-IDs, Ontologie, Embedding-Modell/-Dimension, Mapping-Version). Gleicher Input → gleiche `run_id` → erneuter Ingest ist ein No-op. |
| `indexed_at` | date | **osi**: UTC-Zeitstempel des Ingests |
| `text` | text(de_text) | `c.text` (Whitespace bereinigt). Voller Chunk-Text inkl. Überschriften-Präfix. |
| `body_text` | text(de_text) | `c.body_text` (Chunk-Text ohne Überschriften-Präfix) |
| `heading_breadcrumb` | text(de_text) + .keyword | `c.heading_breadcrumb` (Liste der Überschriften) |
| `heading_level` | integer | `c.heading_level` |
| `kind` | kw | `c.kind` (`text`, `table`, `picture`) |
| `caption` | text(de_text) + .keyword | `c.caption` (nur Tabellen/Bilder) |
| `page_numbers` | integer (Liste) | `c.page_numbers` |
| `dom_paths` | kw (nicht indexiert) | `c.dom_paths` |
| `bboxes` | object (disabled) | `c.bboxes` (Seitenkoordinaten für Hervorhebung) |
| `token_count` | integer | `c.token_count` |
| `identifiers` | kw (Liste) | **abgeleitet**: Regexe der Ontologie (`ontology.yaml`, z. B. `SOP-\d+`, Hostnamen) über `c.text + c.caption`. Groß-/Kleinschreibung zählt. |
| `node_ids` | kw (Liste) | **abgeleitet aus `G`** (Rückwärtsindex): jeder `G.nodes[j]`, dessen `provenance.chunk_ids` diesen Chunk enthält, plus beide Enden jeder `G.edges[j]`, deren `provenance.chunk_ids` ihn enthält |
| `node_labels` | kw, Normalizer `lc` (Liste) | **abgeleitet aus `G`**: `label` **und** `aliases` der Knoten oben, vom Normalizer kleingeschrieben |
| `node_types` | kw (Liste) | **abgeleitet aus `G`**: `type` der Knoten oben |
| `edge_ids` | kw (Liste) | **abgeleitet aus `G`**: Hash-ID jeder Kante, deren `provenance.chunk_ids` diesen Chunk enthält |
| `embedding` | `knn_vector`, dim 1024, `cosinesimil`, HNSW (`lucene`, m=16, ef_construction=128) | `c.embedding` (Liste von 1024 Floats, von docling-graph mit bge-m3 berechnet). Abgelehnt bei dim ≠ `OSI__EMBEDDING__DIM` oder Nullvektor. Liegt zusätzlich in `_source`, daher schließt jede Abfrage das Feld aus. |
| `embedding_model` | kw | **osi**: `OSI__EMBEDDING__MODEL` (`bge-m3`); `response.json` nennt sein Modell nicht |

### 1.2 Abfragen

Alle Chat-Kanäle: `size = 20` (`k_per_channel`), `_source.excludes = ["embedding","bboxes"]`. Hat der Nutzer die
Handbücher eingeschränkt, hängt `doc_ids` einen Filter an: bei kNN innerhalb der `knn`-Klausel, bei den anderen als
`bool.filter`. Ohne Einschränkung gehen die drei Textkanäle ohne `bool`-Hülle raus.

| Kanal | Wer | OpenSearch-Request (Index `bhb-chunks`) | Suchart / Algorithmus / Grenzen | Nachbearbeitung |
|---|---|---|---|---|
| **kNN** (dicht) | Chat | `{"size": 20, "_source": {"excludes": ["embedding","bboxes"]}, "query": {"knn": {"embedding": {"vector": [0.012, -0.044, …1024 Floats], "k": 20, "filter": {"terms": {"doc_id": ["BHB-PLT-0042"]}}}}}}` | **Vektorsuche** auf `embedding`. Frage → dasselbe Embedding-Modell (bge-m3, HTTP-Aufruf `RAG__EMBEDDING__*`) → 1024 Floats. HNSW-Graphdurchlauf, Kosinus-Distanz, **näherungsweise**. Der Filter steht *innerhalb* der `knn`-Klausel → filter-during-search (liefert immer k gültige Treffer). Score: höher = näher; nur innerhalb dieser Liste vergleichbar. Wird (mit Warnung) übersprungen, wenn der Embedding-Dienst ausfällt. | Rang 1…20 → RRF. Der Score selbst geht nicht in die Fusion ein. |
| **BM25** (lexikalisch) | Chat | `{"size": 20, "_source": {…}, "query": {"bool": {"must": [{"multi_match": {"query": "Wer ist verantwortlich für SOP-6?", "fields": ["text^2", "body_text", "caption"]}}], "filter": [{"terms": {"doc_id": […]}}]}}}` | **Volltext**, Lucene **BM25** (Defaults k1=1,2, b=0,75), `best_fields`: Chunk-Score = Maximum über die drei Felder, `text` ×2 gewichtet. Frage und Index laufen beide durch `de_text`: aus `"SOP-6"` werden die Tokens `sop`, `6`; Umlaute gefaltet; gestemmt. Findet gleiche Wörter, nicht gleiche Bedeutung. | Rang → RRF. Die Trefferzahl von BM25 fließt in den Guardrail ein. |
| **Identifier** (exakt) | Chat | `{"size": 20, "_source": {…}, "query": {"bool": {"should": [{"term": {"identifiers": "SOP-6"}}, {"term": {"identifiers": "vault-p01"}}], "minimum_should_match": 1, "filter": […]}}}` | **Exakter Keyword-Treffer**, **Groß-/Kleinschreibung zählt**, keine Analyse. Terme = Ontologie-Regexe über die *Frage* (dieselben Regexe wie beim Indexieren). Einziger Kanal, der `SOP-6` als Ganzes findet. Wird nur gesendet, wenn die Frage mindestens einen Identifier enthält. | Rang → RRF. `via` des Treffers = welche Identifier getroffen haben (in der UI sichtbar). Jeder Identifier-Treffer = starke Evidenz für den Guardrail. |
| **Label** (exakt) | Chat | `{"size": 20, "_source": {…}, "query": {"bool": {"should": [{"term": {"node_labels": "sop-6"}}, {"term": {"node_labels": "vault"}}], "minimum_should_match": 1, "filter": […]}}}` | **Exakter Keyword-Treffer**, beidseitig vom Normalizer `lc` kleingeschrieben. Terme = Labels/Aliase von Graph-Knoten, die als N-Gramme (≤ 4 Wörter) in der Frage vorkommen, aufgelöst gegen den **Graph im Speicher** (nicht OpenSearch), plus „partielle“ Labels (≥ 2 Fragewörter). Wird nur gesendet, wenn mindestens ein Label gefunden wurde. | Rang → RRF. `via` = getroffene Labels. Die getroffenen Knoten werden Startknoten der Graph-Expansion. |
| **Graph-Chunks** (Nachladen per ID) | Chat, langsamer Modus | `POST bhb-chunks/_mget?_source_excludes=embedding,bboxes` Body `{"ids": ["b6d7d486423e-0010", "b6d7d486423e-0093", …]}` | **Lookup per `_id`**, keine Suche, kein Score. Bis zu 15 IDs (`graph_max_chunks`) = die `provenance.chunk_ids` der besten Graph-Fakten. Das ist der „Join“ Graph → Chunks, in Python. | Wird die 5. Liste (`graph`) in einem zweiten RRF; die ersten 2 Graph-Chunks werden in die Endliste gezwungen (`_guarantee_graph_sources`). |
| Test: kNN mit gespeichertem Vektor | `osi search --knn-from-chunk` | `GET bhb-chunks/_doc/{chunk_id}?_source_includes=embedding` → danach die kNN-Abfrage oben ohne Filter | wie kNN; Vektor wird aus einem indexierten Chunk gelesen statt eine Frage einzubetten | keine (Ausgabe) |
| Test: Hybrid-RRF | `osi search --hybrid` | `{"query": {"hybrid": {"queries": [{knn…}, {multi_match…}, {"terms": {"identifiers": […]}}, {"terms": {"node_labels": […]}}]}}}` mit `?search_pipeline=bhb-rrf` | **serverseitige** Fusion durch die Search-Pipeline `bhb-rrf` (`score-ranker-processor`, `rrf`, rank_constant 60). Braucht OpenSearch ≥ 2.19. **Vom Chat nicht genutzt** (liefert nur einen Score, kann die Graph-Liste nicht aufnehmen). | keine |
| Wartung | `osi ingest` / `delete` / `status` | Zählen: `{"query": {"bool": {"filter": [{"term": {"doc_id": "BHB-PLT-0042"}}, {"term": {"run_id": "…"}}]}}}` · Sweep (alte Läufe eines Handbuchs): `delete_by_query {"query": {"bool": {"filter": [{"term": {"doc_id": "…"}}], "must_not": [{"term": {"run_id": "<neuer Lauf>"}}]}}}` · Handbuch löschen: `delete_by_query {"query": {"term": {"doc_id": "…"}}}` · Zählung je Handbuch: `{"size": 0, "aggs": {"by_doc": {"terms": {"field": "doc_id", "size": 1000}}}}` | exakte Keyword-Filter / Aggregation, kein Scoring | keine |

## 2. `bhb-nodes`

### 2.1 Felder

`n` = `graph.nodes[j]` in `response.json`.

| Feld | Typ | Herkunft |
|---|---|---|
| `node_id` | kw | `n.id` (`Person_fd3e064a23582274`); dieselbe ID kann in mehreren Handbüchern vorkommen → `_id` = `{sha12}:{node_id}` |
| `doc_id`, `doc_sha256`, `run_id`, `indexed_at` | kw / date | wie in `bhb-chunks` |
| `scope` | kw | Konstante `"document"` (`"corpus"` ist für einen späteren Merge-Schritt reserviert) |
| `type` | kw | `n.type` (`Person`, `Procedure`, `System`, …) |
| `label` | text(standard) + .keyword(`lc`) | `n.label` (Standard-Analyzer: Namen werden nicht gestemmt) |
| `aliases` | text(standard) + .keyword(`lc`) | `n.aliases` |
| `identity`, `identity_norm` | kw | **abgeleitet**: Identitätsschlüssel aus den Identitätsregeln der Ontologie je Typ + `root_system` (zum Zusammenführen derselben Entität über Handbücher hinweg) |
| `attributes` | `flat_object` | `n.attributes` (freie Schlüssel/Werte; nur wenn nicht leer) |
| `attributes_text` | text(de_text) | **abgeleitet**: alle Attributwerte, mit Leerzeichen verbunden |
| `quote` | text(de_text) | `n.quote` (Belegsatz) |
| `identifiers` | kw (Liste) | **abgeleitet**: Ontologie-Regexe über `label + aliases + attributes` |
| `chunk_ids` | kw (Liste) | `n.provenance.chunk_ids` |
| `pages` | integer (Liste) | `n.provenance.pages` |
| `match` | kw | `n.provenance.match` (wie der Extraktor den Knoten verankert hat, z. B. `verbatim`) |
| `degree` | integer | **abgeleitet**: Anzahl der Kanten in `G`, die diesen Knoten berühren |
| `provenance` | object (disabled) | `n.provenance` als Ganzes |

### 2.2 Abfragen

| Kanal | Wer | OpenSearch-Request (Index `bhb-nodes`) | Suchart / Grenzen | Nachbearbeitung |
|---|---|---|---|---|
| — | Chat | **keine.** Der Chat fragt `bhb-nodes` nie ab; er bekommt den Graphen aus `bhb-documents.graph`. | | |
| Knoten nachschlagen | `osi search --node-id` | `{"size": 50, "_source": {"excludes": ["provenance"]}, "query": {"term": {"node_id": "Procedure_53d37ee243c4f7f3"}}}` | exaktes Keyword; alle Handbücher, die den Knoten nennen | Python-„Join“: für jede `doc_id` der Treffer → `GET bhb-documents/_doc/{doc_id}?_source_includes=graph` → Kanten dieses Knotens aus dem JSON-Blob gesammelt |
| geteilte Knoten | `osi status` | `{"size": 0, "aggs": {"shared": {"terms": {"field": "node_id", "min_doc_count": 2, "size": 10000}}}}` | Aggregation: Knoten-IDs, die in ≥ 2 Handbüchern vorkommen | Ausgabe |
| Wartung | `osi ingest` / `delete` | dieselben Zählungen / Sweep / delete_by_query / `by_doc`-Aggregation wie bei den Chunks | exakte Keyword-Filter | keine |

Die Felder `label`, `aliases`, `attributes_text`, `quote` sind durchsuchbar (text), aber **keine Abfrage nutzt sie
heute**. Sie sind für eine spätere handbuchübergreifende Entitätssuche gedacht.

## 3. `bhb-documents`

### 3.1 Felder

`d` = `document` in `response.json`; `own` = der Knoten vom Typ `Document` in `graph.nodes`, dessen
`attributes.doc_id` der `doc_id` dieses Handbuchs entspricht.

| Feld | Typ | Herkunft |
|---|---|---|
| `doc_id` | kw (= `_id`) | **osi**: siehe `bhb-chunks` |
| `doc_id_source` | kw | **osi**: welche Regel die `doc_id` aufgelöst hat (`override`, `ontology_file`, `page1_regex`, `documents_edge`) |
| `doc_sha256`, `run_id`, `indexed_at` | kw / date | wie oben |
| `scope` | kw | Konstante `"document"` |
| `name` | kw | `d.name` (Dateiname) |
| `format` | kw | `d.format` (`pdf`) |
| `pages`, `tables`, `pictures` | integer | `d.pages`, `d.tables`, `d.pictures` |
| `title` | text(de_text) + .keyword | `own.attributes.title`, sonst `own.label` |
| `version`, `valid_from`, `classification`, `ci_id` | kw | `own.attributes.*` (`valid_from` bleibt ein ungeparster String: „22. Juli 2026“) |
| `root_system` | kw | **osi**: `ontology.root_system(doc_id)` |
| `related_doc_ids` | kw (Liste) | `attributes.doc_id` der *anderen* `Document`-Knoten in `G` (Handbücher, die dieses zitiert) |
| `markdown` | text (nicht indexiert) | `markdown` (das ganze Handbuch als Markdown, ~67 k Zeichen) |
| `graph` | object (**disabled**) | **der komplette `graph` aus `response.json`** (`nodes`, `edges`, `meta`), plus eine `id` an jeder Kante. Als undurchsichtiger Blob gespeichert: OpenSearch kann darin nicht suchen. |
| `degraded.vlm`, `.embeddings`, `.graph` | boolean | `degraded.*` (welche Pipeline-Stufe im Fallback lief) |
| `errors`, `warnings` | kw (nicht indexiert) | `errors`, `warnings` |
| `timings_s`, `versions` | object (disabled) | `timings_s`, `versions` |
| `counts.chunks`, `.nodes`, `.edges`, `.documents` | integer | **osi**: beim Ingest berechnet |
| `embedding_model` | kw | **osi**: `OSI__EMBEDDING__MODEL` |
| `embedding_dim` | integer | **osi**: `OSI__EMBEDDING__DIM` (1024) |
| `embedding_text_prefix` | kw (nicht indexiert) | **osi**: `OSI__EMBEDDING__TEXT_PREFIX` (`""` bei bge-m3, `"passage: "` bei e5) |

### 3.2 Abfragen

| Kanal | Wer | OpenSearch-Request (Index `bhb-documents`) | Suchart / Grenzen | Nachbearbeitung |
|---|---|---|---|---|
| Graph laden | Chat, **einmal beim Start** und bei `reload_graph()` nach einem neuen Ingest | `{"size": 200, "_source": {"includes": ["doc_id", "title", "version", "root_system", "embedding_model", "embedding_dim", "embedding_text_prefix", "counts", "name", "indexed_at", "graph"]}, "query": {"match_all": {}}}` | **keine Suche**: liefert jedes Handbuch (max. 200) mit seinem Graph-Blob. `graph` ist ein JSON-Blob, also ein Massenlesen, keine Abfrage. | Python baut den `GraphStore` im Speicher: Knoten, Kanten, Adjazenz, ein Label-/Alias-Index (`norm_key`), Titel je `doc_id`. Alles Graph-bezogene einer Chat-Anfrage (Label-Abgleich, 1-Hop-Expansion, Fakten, Steckbriefe) läuft auf dieser RAM-Kopie, **nicht** auf OpenSearch. Dient auch der Warnung, wenn das Frage-Embedding-Modell ≠ dem indexierten ist. |
| Dokumentsatz | `osi search --node-id` | `GET bhb-documents/_doc/{doc_id}?_source_includes=graph` | Lookup per `_id` | Kanten in Python gefiltert (siehe `bhb-nodes`) |
| Wartung | `osi delete` | `DELETE bhb-documents/_doc/{doc_id}` | per `_id` | keine |

## 4. `bhb-manifest`

### 4.1 Felder

Reine `osi`-Buchführung; außer `doc_sha256` und `doc_name` stammt nichts aus `response.json`.

| Feld | Typ | Herkunft |
|---|---|---|
| `doc_id` | kw (= `_id`) | aufgelöste `doc_id` |
| `status` | kw | `indexing` → `active` oder `failed` (gesetzt von `osi ingest`) |
| `run_id`, `previous_run_id` | kw | aktueller / vorheriger Lauf-Fingerabdruck |
| `doc_sha256`, `doc_name` | kw | `document.sha256`, `document.name` |
| `doc_id_source` | kw | siehe `bhb-documents` |
| `owner` | kw | `hostname:pid` des Indexer-Prozesses (Sperrinhaber) |
| `started_at`, `finished_at` | date | Ingest-Zeitstempel |
| `counts.*`, `swept.*` | integer | geschriebene Zeilen / entfernte alte Zeilen je Index |
| `embedding_model`, `mapping_version`, `indexer_version` | kw / integer / kw | was diesen Lauf erzeugt hat |
| `error` | kw (nicht indexiert) | Fehlermeldung (max. 2000 Zeichen) |
| `history` | object (disabled) | frühere Manifest-Zustände |

### 4.2 Abfragen

| Kanal | Wer | OpenSearch-Request (Index `bhb-manifest`) | Suchart / Grenzen | Nachbearbeitung |
|---|---|---|---|---|
| — | Chat | **keine** | | |
| Planung | `osi ingest` | `GET bhb-manifest/_doc/{doc_id}` (mit `seq_no`/`primary_term` für optimistisches Sperren) · `{"size": 5, "query": {"term": {"doc_sha256": "<sha>"}}}` (dieselbe PDF schon unter anderer `doc_id` indexiert?) | Lookup / exaktes Keyword | entscheidet **noop** (gleiche `run_id`, Status `active`), **Abbruch** (Status `indexing` durch anderen Owner, außer `--force`) oder **Ingest** |
| Sperre + Zustand | `osi ingest` | `PUT bhb-manifest/_doc/{doc_id}?op_type=create` (schlägt fehl, wenn vorhanden → Sperre) · Update auf `active`/`failed` mit `if_seq_no`/`if_primary_term` | Schreiben mit Nebenläufigkeitskontrolle | nach `active`: Sweep älterer Läufe in Chunks/Nodes |
| Auflistung | `osi status` | `{"size": 500, "sort": [{"doc_id": "asc"}], "query": {"match_all": {}}}` | alle Manifeste | kombiniert mit den `by_doc`-Zählungen von Chunks/Nodes; `failed`/`indexing` unter *attention* gemeldet |
