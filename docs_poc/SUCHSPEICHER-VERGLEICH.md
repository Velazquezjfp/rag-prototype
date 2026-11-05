# Suchspeicher: OpenSearch und Alternativen

Stand: 2026-10-06. Grundlage: `technical_request.md`, `ARCHITECTURE-DATAFLOW.md`, `RETRIEVAL-FLOW.md`, der Code in `opensearch-index/`, `retrieval/`, `chat-system/` und `docling-graph/` sowie der Vergleich im Notebook `database_comparison/vergleich.ipynb` (ausgeführt 2026-10-06; drei Handbücher ZSD, CaaS, Event-System = 401 Chunks, 674 Knoten; Embedding bge-m3; der **unveränderte** Retriever lief einmal gegen OpenSearch und einmal gegen SQLite).

Markierungen: **✔** = im Notebook gemessen und bestätigt · **⚠** = bestätigter Vorbehalt · **offen** = noch nicht geprüft.

§1–§2 vergleichen die Optionen. **§3 ist die Bauvorlage für die gewählte Variante SQLite + numpy.** §4–§7 behandeln Betrieb, Kubernetes, Skalierung und Empfehlung. §8 beschreibt die Ausbaustufe mit mehreren Replikas, §9 ist die Zusammenfassung für das Team.

## 1. Was der Speicher leisten muss – und warum

| Komponente | Wofür im System | Warum sie für die Antwortqualität zählt |
|---|---|---|
| **Vektorsuche mit Filter** (`doc_ids`) | k-NN-Kanal, Mandantentrennung | Findet Passagen mit gleicher Bedeutung, aber anderen Worten. Der Filter muss *in* der Suche wirken, sonst fehlen Treffer oder es werden fremde Handbücher sichtbar. |
| **BM25 mit deutscher Analyse** (Stemming, Stoppwörter, Umlaute) | BM25-Kanal | „Zertifikate“ soll „Zertifikat“ finden. **Größtes Qualitätsrisiko beim Wechsel.** Die Analyse kann in der Datenbank laufen oder vorab in Python (§3.4). |
| **Exakter Abgleich auf String-Listen** (einmal wörtlich, einmal kleingeschrieben) | Identifier- und Label-Kanal | IDs wie `SOP-ZSD-06` und Namen dürfen nicht zerlegt werden. Sie liefern die „starke Evidenz“ für den Guardrail. |
| **Lesen per ID, mehrere Suchen pro Aufruf** | Graph-Chunks (`mget`), 4 Kanäle (`msearch`) | Hält die Latenz pro Frage niedrig. |
| **Atomares Schreiben mit Versionsprüfung** | Manifest als Lock | Verhindert, dass zwei Ingests dasselbe Handbuch gleichzeitig schreiben. |
| **Löschen per Abfrage, JSON-Blobs speichern** | Sweep alter Runs, `graph`/`markdown` in `bhb-documents` | Saubere Versionswechsel; der Graph wird beim Chat-Start geladen. |

Nicht nötig, weil es bereits im Python-Code läuft: RRF-Fusion, Graph-Traversierung (1 Hop), Fakten, Entity-Cards, Prompt-Aufbau.

Datenmenge: ~600 Chunks heute (5 Handbücher), ~5 000 bei 40 und ~12 000 bei 100 Handbüchern. Bei dieser Menge reicht eine exakte Vektorsuche (Brute Force). Der Index-Typ (HNSW, IVF, PQ) spielt für die Qualität kaum eine Rolle; die **Textanalyse** schon. ✔ Exakte numpy-Suche und HNSW lieferten dieselben Top-20 in gleicher Reihenfolge; der Analyzer-Port musste dagegen Token für Token stimmen (§3.4).

## 2. Vergleich der Datenbanken

| Kriterium | **OpenSearch** (heute) | **PostgreSQL + pgvector** | **zvec** (Alibaba) | **SQLite** (FTS5) + numpy |
|---|---|---|---|---|
| Betriebsform | Server (HTTP) | Server (TCP) | Bibliothek im Prozess | Bibliothek im Prozess, eine Datei |
| Reife | stabil, ≥ 2.19 | stabil | 0.7.0 (Aug. 2026), jung | sehr stabil; FTS5 im Python-Modul `sqlite3` verfügbar (geprüft: SQLite 3.45.1) |
| Lizenz | Apache-2.0 | PostgreSQL-Lizenz | Apache-2.0 | Public Domain |
| Vektorsuche | HNSW (Lucene), approximativ | HNSW, IVFFlat oder exakt | HNSW, IVF, DiskANN, Flat; ✔ FLAT identisch mit OpenSearch | numpy, **exakt** (Vektoren als BLOB); `vec1` nicht nötig. ✔ Top-20 identisch mit HNSW |
| Filter in der Vektorsuche | ja | ja (`WHERE doc_id = ANY(...)`) | ja (Skalarfilter) | ja (Maske in numpy) |
| Volltext / BM25 | ja, BM25 | ja; `ts_rank` (BM25 mit ParadeDB `pg_search`) | ja, BM25 (seit 0.5); ⚠ eigene IDF/Längennormierung: mit unseren Tokens Top-10-Überschneidung 1,0, mit zvec-Analyse 0,6 | FTS5 als Kandidatenfilter; ⚠ FTS5s `bm25()` ordnet anders (Top-10-Überschneidung ≈ 0,9) → Lucene-Formel in Python nachgerechnet, ✔ Scores identisch (§3.3) |
| **Deutsche Analyse** | ja (`light_german`, Stoppwörter, Normalisierung) | **ja** (`to_tsvector('german')`, Snowball) | Snowball german eingebaut, ohne Stoppwörter und Normalisierung → ⚠ Python-Analyzer trotzdem nötig | **nicht eingebaut** → in Python (§3.4). ✔ Port = OpenSearch `_analyze`: 910 Felder, 41 986 Tokens, 0 Abweichungen |
| Exakte Liste / kleingeschrieben | `keyword` + Normalizer | `text[]` + GIN, `lower()` | `ARRAY_STRING` + Invert-Index; ⚠ in 0.7.0 kein Filter auf Listenfelder gefunden (`=`, `IN`, `CONTAINS` abgewiesen) → eigene Strukturen nötig | Hilfstabelle mit Index. ✔ gleiche Treffermengen |
| Hybrid / Fusion | im Client (RRF) | im Client | eingebaut oder Client | im Client |
| Lock / Versionsprüfung | `seq_no` / `primary_term` | Transaktionen, `SELECT … FOR UPDATE` | keine eigene | `BEGIN IMMEDIATE` (ein Schreiber). ✔ zwei Indexer gleichzeitig: der zweite wartet, beide schreiben nacheinander |
| Run ersetzen + Sweep | 5 Schritte | **eine Transaktion** | mehrere Schritte | **eine Transaktion**. ✔ 0,3–0,6 s je Handbuch |
| Lesen während Ingest | ja; alte und neue Chunks kurz gleichzeitig sichtbar; ⚠ gelöschte Fassungen verzerren BM25 bis zum Segment-Merge (§3.3) | ja; neuer Stand erst nach Commit | Verhalten nicht dokumentiert | ja (WAL); neuer Stand erst nach Commit. ✔ 10 Lese-Threads während drei Neuschreibungen: 0 Fehler, Vektoren nach `data_version` neu geladen |
| **Qualität gleich halten?** | Referenz | **ja** (nicht gemessen) | nur mit Python-Analyzer **und** eigenen Strukturen für Identifier/Label | **ja** ✔ Guardrail 10/10, fusionierte Top-10-Überschneidung 0,97; Rest = Gleichstände (§3.9) |
| Ressourcen (gemessen, 401 Chunks) | Container ≈ 3,4 GiB RSS (Heap 2 GB), Chunk-Index ≈ 8 MB (13 MB mit gelöschten Fassungen) | nicht gemessen | 8,3 MB auf Platte | 5,8 MB Datei + 1,6 MiB Vektormatrix im Chat-Prozess |
| 10 gleichzeitige Suchen kNN+BM25 (gemessen, p50) | ≈ 50–70 ms | nicht gemessen | nicht gemessen | ⚠ ≈ 375–415 ms (FTS5 `bm25()`) bis ≈ 1 000–1 150 ms (Lucene-Formel), GIL-gebunden (§4) |

## 3. Bauvorlage: SQLite + numpy

### 3.1 Was bleibt, was sich ändert

**Bleibt unverändert:** dgs und seine Antwort, `build_batch`, `doc_id`-Auflösung, `run_id`/`doc_sha256`, die Plan-Logik (noop / replace / neue Extraktion / Abweisung), Fragen-Analyse, Embedding, RRF, Guardrail, Graph (Laden, Startknoten, 1-Hop-Expansion, Fakten, Entity-Cards, Graph-Chunks als 5. RRF-Liste), Prompt, Chat-Historie (`chat.db`).

**Ändert sich:** nur die drei Stellen, an denen der Retriever die Datenbank berührt, plus der Katalog und das Schreiben im Indexer.

| Stelle | Heute (OpenSearch) | Neu (SQLite + numpy) |
|---|---|---|
| Graph beim Start (`retriever.py:77`) | `bhb-documents` | Tabelle `documents`, Spalte `graph` |
| 4 Kanäle (`retriever.py:155`) | 1× `msearch` | kNN: numpy · BM25: FTS5 · Identifier, Label: Hilfstabellen |
| Graph-Chunks (`retriever.py:263`) | `mget` | `SELECT … WHERE chunk_id IN (…)` |
| Katalog (`chat_system/catalog.py:43`) | `search` auf `bhb-documents` | Tabelle `documents` |
| Ingest (`indexer.py:240`) | lease → bulk → refresh → verify → sweep → finalize | **eine Schreibtransaktion** (§3.5) |

Die vier Indizes werden Tabellen in **`search.db`**, einer eigenen Datei neben `chat.db` auf derselben PVC. Die Schlüssel bleiben dieselben (`chunk_id`, `{sha12}:{node_id}`, `doc_id`). Die Datensätze werden als JSON gespeichert, genau wie heute `_source`. Der Retriever bekommt dadurch dieselben Felder wie bisher. ✔ Im Notebook lief der unveränderte Retriever über einen Shim-Client (`msearch`/`mget`/`search`) gegen diese Tabellen; die Chunk-Datensätze sind gleich mit `_source` (ohne `indexed_at`), die `run_id`s identisch.

### 3.2 Schema

```sql
-- einmalig beim Anlegen (bleibt in der Datei)
PRAGMA journal_mode = WAL;
-- pro Verbindung
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 30000;

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);  -- schema_version, embedding_model, embedding_dim, analyzer_version, data_version (Zähler)

CREATE TABLE manifest (                -- bhb-manifest: letzter ERFOLGREICHER Stand je Handbuch
  doc_id     TEXT PRIMARY KEY,
  run_id     TEXT NOT NULL,
  doc_sha256 TEXT NOT NULL,
  status     TEXT NOT NULL,            -- immer 'active' (Fehler stehen in ingest_log)
  body       TEXT NOT NULL             -- vollständiger Manifest-Datensatz als JSON, wie heute
);
CREATE INDEX manifest_sha ON manifest(doc_sha256);

CREATE TABLE ingest_log (              -- jeder Versuch, auch noop und Fehler
  id          INTEGER PRIMARY KEY,
  doc_id      TEXT NOT NULL,
  run_id      TEXT NOT NULL,
  owner       TEXT,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  status      TEXT NOT NULL CHECK (status IN ('active', 'noop', 'failed')),
  error       TEXT
);

CREATE TABLE documents (               -- bhb-documents
  doc_id   TEXT PRIMARY KEY,
  run_id   TEXT NOT NULL,
  source   TEXT NOT NULL,              -- Datensatz als JSON OHNE graph und markdown
  graph    TEXT,                       -- node-link-JSON, beim Chat-Start geladen
  markdown TEXT                        -- groß, wird nie beim Start gelesen
);

CREATE TABLE chunks (                  -- bhb-chunks
  rid       INTEGER PRIMARY KEY,       -- interne Zeilen-ID; verbindet FTS5 und Hilfstabellen
  chunk_id  TEXT NOT NULL UNIQUE,      -- {sha12}-{seq}, wie _id heute
  doc_id    TEXT NOT NULL,
  run_id    TEXT NOT NULL,
  embedding BLOB,                      -- float32 little-endian, dim × 4 Byte, so wie geliefert
  bboxes    TEXT,                      -- JSON, wird nie gesucht
  source    TEXT NOT NULL              -- Datensatz als JSON ohne embedding und bboxes = heutiges _source
);
CREATE INDEX chunks_doc ON chunks(doc_id);

CREATE TABLE chunk_identifiers (       -- Feld identifiers: wörtlich, Groß-/Kleinschreibung zählt
  identifier TEXT NOT NULL,
  rid        INTEGER NOT NULL REFERENCES chunks(rid) ON DELETE CASCADE,
  PRIMARY KEY (identifier, rid)
) WITHOUT ROWID;
CREATE INDEX chunk_identifiers_rid ON chunk_identifiers(rid);

CREATE TABLE chunk_labels (            -- Feld node_labels: lower(trim(label)), wie Normalizer lc
  label_lc TEXT NOT NULL,
  rid      INTEGER NOT NULL REFERENCES chunks(rid) ON DELETE CASCADE,
  PRIMARY KEY (label_lc, rid)
) WITHOUT ROWID;
CREATE INDEX chunk_labels_rid ON chunk_labels(rid);

-- BM25: eine FTS5-Tabelle je Feld, damit jedes Feld seine eigene Längennormierung hat (wie Lucene).
-- rowid = chunks.rid. Inhalt = die Tokens aus dem Python-Analyzer, durch Leerzeichen getrennt.
-- Leere Felder bekommen KEINE Zeile (wie in Lucene zählt nur, wer das Feld hat).
CREATE VIRTUAL TABLE fts_text    USING fts5(tokens, tokenize = "unicode61 remove_diacritics 0 tokenchars '.:_,;·‘’․‧⁄'");
CREATE VIRTUAL TABLE fts_body    USING fts5(tokens, tokenize = "unicode61 remove_diacritics 0 tokenchars '.:_,;·‘’․‧⁄'");
CREATE VIRTUAL TABLE fts_caption USING fts5(tokens, tokenize = "unicode61 remove_diacritics 0 tokenchars '.:_,;·‘’․‧⁄'");
-- je FTS-Tabelle eine fts5vocab-Tabelle (instance 'row'): Dokumenthäufigkeit n und Σ tf für die Lucene-Formel (§3.3)

CREATE TABLE nodes (                   -- bhb-nodes (vom Retriever nicht gelesen; für status/search)
  id      TEXT PRIMARY KEY,            -- {sha12}:{node_id}, wie _id heute
  node_id TEXT NOT NULL,
  doc_id  TEXT NOT NULL,
  run_id  TEXT NOT NULL,
  source  TEXT NOT NULL
);
CREATE INDEX nodes_doc ON nodes(doc_id);
CREATE INDEX nodes_node_id ON nodes(node_id);
```

Hinweise zum Schema:

- `tokenchars`: Die FTS5-Tabelle soll die Python-Tokens **unverändert** übernehmen, also nicht weiter zerlegen. ✔ Golden-Test (§3.9) über drei Handbücher: mit der Liste `.:_,;·‘’․‧⁄` enthält `fts5vocab` genau die Python-Tokens. Ein ASCII-Apostroph im Token wird im Dokument und in der Abfrage einheitlich durch `’` ersetzt (FTS5-Syntax).
- `node_ids`, `edge_ids`, `node_types` bleiben im Chunk-JSON. Der Retriever liest sie aus den Treffern; dafür braucht es keine eigene Tabelle.

### 3.3 Die vier Kanäle und die Abrufe

Alle Kanäle liefern Treffer im **heutigen Format** `{"_id": chunk_id, "_score": float, "_source": dict}`. Der Rest des Retrievers bleibt dadurch unverändert. `k` = `max(k_per_channel, final_k)` = 20. Ohne `doc_ids` werden alle Handbücher durchsucht, sonst nur die genannten.

| Kanal | Heute | Neu | Gleichwertigkeit |
|---|---|---|---|
| **kNN** | `knn` auf `embedding`, `cosinesimil`, Filter in der Suche | Matrix im Speicher (normiert), `M @ q`, Maske auf `doc_ids`, Top-k; `_source` per `SELECT source … WHERE rid IN (…)` | ✔ Top-20 identisch mit HNSW, auch in der Reihenfolge. Score (1 + cos)/2 wie OpenSearch nachgebildet; RRF und Guardrail nutzen ohnehin nur Ränge (`fusion.py:36`, `guardrail.py:3`) |
| **BM25** | `multi_match` über `text^2`, `body_text`, `caption` (Typ `best_fields`, ODER-Verknüpfung) | Frage mit **demselben** Python-Analyzer zerlegen. Je Feld: Kandidaten per `SELECT rowid, tokens FROM fts_x JOIN chunks ON rid = rowid WHERE fts_x MATCH :q AND doc_id IN (…)`, Score **in Python nach der Lucene-Formel** (IDF aus `fts5vocab`, `N` und `avgdl` je Feld, Dokumentlänge wie Lucene auf 1 Byte quantisiert, float32). Score je Chunk = max(2·s_text, s_body, s_caption) | ✔ Scores identisch mit OpenSearch (max \|Δ\| = 0 über 10 Fragen, Index ohne gelöschte Fassungen). ⚠ FTS5s eigenes `bm25()` erreicht nur ≈ 0,9 Top-10-Überschneidung |
| **Identifier** | `term` auf `identifiers`, mehrere ODER | `SELECT identifier, rid FROM chunk_identifiers WHERE identifier IN (…)`, Score in Python | ✔ Score = **Anzahl der getroffenen Begriffe** (1,0 je Begriff). OpenSearch bewertet `term` auf keyword-Feldern als `ConstantScore` 1,0 (per `explain` geprüft) — nicht Σ idf, wie hier zuvor angenommen |
| **Label** | `term` auf `node_labels` (Normalizer `lc`) | wie Identifier, auf `chunk_labels` mit `lower(trim(…))` | wie Identifier |

Details, die über die Gleichwertigkeit entscheiden:

- **FTS5 verknüpft Begriffe standardmäßig mit UND; OpenSearch mit ODER.** Die Abfrage muss deshalb explizit gebaut werden: `"t1" OR "t2" OR …`. Jedes Token steht in doppelten Anführungszeichen, ein `"` im Token wird verdoppelt. Ohne diese Regel liefert BM25 weniger Treffer, und der Guardrail (Prüfung `bm25_returned`) urteilt anders.
- **Leere Abfrage** (nur Stoppwörter): kein FTS5-Aufruf, der Kanal bleibt leer, wie heute.
- **`bm25()` liefert negative Werte** (kleiner = besser). Vor dem Maximum mit −1 multiplizieren.
- **IDF-Unterschied (bekannt, getestet):**
  - FTS5 rechnet `ln((N − n + 0,5) / (n + 0,5))` und setzt negative Werte auf 1e-6; Lucene rechnet `ln(1 + …)`, also immer > 0.
  - Ein Begriff in mehr als der Hälfte der Chunks zählt in FTS5 deshalb praktisch nicht mehr, in Lucene noch wenig. Nach dem Entfernen der Stoppwörter ist das selten.
  - ✔ Der Kanal-Vergleich zeigt Abweichungen (Top-10-Überschneidung ≈ 0,9, Reihenfolge bei keiner Frage gleich); deshalb wird BM25 in Python aus den FTS5-Kandidaten berechnet. Neben der IDF unterscheiden sich: Lucene quantisiert die Dokumentlänge auf 1 Byte (`SmallFloat`), rechnet in float32 und nimmt `avgdl = sumTotalTermFreq / docCount` je Feld. Mit diesen Details sind die Scores gleich.
- **`LIMIT k` je Feld reicht:** Jeder Chunk der Gesamt-Top-k liegt in der Top-k des Feldes, aus dem sein Maximum stammt.
- **Kein IDF für Identifier/Label:** OpenSearch gibt jedem `term`-Treffer konstant 1,0 (`ConstantScore`); der Score ist die Zahl der getroffenen Begriffe. ✔ So nachgebildet, Treffermengen und Punktzahl-Stufen identisch.
- **⚠ BM25-Drift in OpenSearch:** Nach erzwungenem Neuschreiben derselben `_id`s bleiben die alten Fassungen als gelöschte Dokumente im Segment und zählen in `N` und `n` mit, bis ein Merge sie entfernt. Gemessen: 2 005 gelöschte neben 401 aktiven Chunks, `N` = 2 406 statt 401, max \|Δ Score\| 0,39 und ein anderes BM25-Top-1; nach `_forcemerge?only_expunge_deletes=true` wieder Δ = 0. SQLite kennt diesen Effekt nicht; dort hängen Scores nur vom aktuellen Inhalt ab.
- **Gleichstand:** nach `chunk_id` sortieren. Das entspricht der Lesereihenfolge (`{sha12}-{seq}`) und ist deterministisch. ⚠ OpenSearch ordnet gleiche Scores nach Lucene-Dokumentnummer, also nach Indexgeschichte; das ist nicht reproduzierbar und erklärt die verbleibenden Unterschiede in fusionierten Top-10, Fakten und Kontext (§3.9). Betroffen sind vor allem die Exakt-Kanäle, in denen alle Treffer 1,0 haben (z. B. Label `dispatcher`: 13 Chunks, Label `vault`: mehr als k = 20).
- **Identifier bleiben case-sensitiv**, wie heute. Die bekannte Lücke (kleingeschriebene IDs in der Frage) wird bewusst nicht mitgeändert, sonst wäre der Vergleich nicht mehr 1:1.

Abrufe:

- `fetch_chunks(ids)`: `SELECT chunk_id, source FROM chunks WHERE chunk_id IN (…)`; fehlende IDs werden übersprungen.
- `fetch_documents(include_graph)`: `SELECT source[, graph] FROM documents`. Anders als heute (`size: 200`, `search.py:114`) gibt es keine stille Obergrenze.
- **Vektoren beim Laden:** `SELECT rid, chunk_id, doc_id, embedding FROM chunks WHERE embedding IS NOT NULL ORDER BY rid`, dann `np.frombuffer(…, '<f4')`. Jede Zeile wird auf Länge 1 normiert; Nullvektoren werden abgewiesen (dgs normiert nicht, `docling-graph/src/docling_graph_service/embed.py`). ✔ 401 Vektoren, 1,6 MiB.
- **⚠ Reihenfolge der Handbücher:** `fetch_documents` liefert nach `doc_id`. Der Graph übernimmt Label und Aliase handbuchübergreifender Knoten vom zuerst geladenen Handbuch (104 solche `node_id`s bei drei Handbüchern); OpenSearch lieferte sie in Indexreihenfolge. Der Inhalt ist gleich, die Reihenfolge von Label, Aliasen und Zitaten im Kontext kann abweichen (Batch: Kontext gleich 7/10 bei gleicher Ladereihenfolge, 3/10 bei `doc_id`-Reihenfolge). OpenSearch mischt außerdem die Schlüsselreihenfolge in `_source`, sobald `includes`/`excludes` gesetzt sind; SQLite liefert die gespeicherte Reihenfolge.

### 3.4 Deutsche Analyse in Python

Ein gemeinsames Modul (Vorschlag: `opensearch_index/analysis.py`) wird vom **Indexer und vom Chat** genutzt. Index und Frage müssen identisch zerlegt werden. Der Chat-Container hat `opensearch_index` bereits installiert. ✔ Referenzimplementierung: `database_comparison/de_analysis.py` (≈ 190 Zeilen), Golden-Test bestanden.

Die Reihenfolge entspricht `de_text` (`opensearch-index/src/opensearch_index/mappings.py:64`):

1. **Tokenizer:** Wortgrenzen wie der Lucene `standard`-Tokenizer (UAX #29), umgesetzt mit dem Paket `regex`: Folgen aus Buchstaben, Ziffern, Markierungen und Verbindern, dazwischen einzelne `.:'‘’·‧․` zwischen Buchstaben bzw. `.,;'‘’․⁄٬` zwischen Ziffern; Bindestriche trennen. Segmente ohne Buchstabe oder Ziffer und Tokens über 255 Zeichen verwerfen.
2. **lowercase**
3. **Stoppwörter:** die Lucene-Liste `_german_` (Snowball `german_stop.txt`, 231 Wörter, aus dem Lucene-Jar des Containers übernommen), **vor** der Normalisierung angewendet.
4. **german_normalization:** `ß` → `ss`; `ä`/`ö`/`ü` → `a`/`o`/`u`; `ae`/`oe` → `a`/`o`; `ue` → `u` (nicht nach Vokal oder `q`). Maßgeblich ist der Lucene-Quelltext `GermanNormalizationFilter`.
5. **light_german:** aus dem Lucene-Quelltext `GermanLightStemmer` portieren (kurz, nur Suffixregeln).

Eingabe sind die Felder `text`, `body_text` und `caption` aus dem Chunk-JSON (bereits durch `clean_text` gelaufen) bzw. die Frage, so wie sie heute an `bm25_body` geht.

✔ Golden-Test: alle 910 nicht leeren Felder der 401 Chunks, 41 986 Tokens, 0 Abweichungen gegenüber `POST /bhb-chunks/_analyze` mit `de_text`.

Das Modul trägt eine `ANALYZER_VERSION`, die in `meta` gespeichert wird. Erwartet der Chat eine andere Version als die Datei, startet er nicht. Ändert sich der Analyzer, baut `osi reanalyze` die FTS-Tabellen aus `chunks.source` neu auf; dgs wird dafür nicht gebraucht.

### 3.5 Ingest: eine Transaktion

```
plan()                                    unverändert (liest manifest.body, sucht doc_sha256 in manifest)
  noop  → ingest_log(noop), Ende
build_batch()                             unverändert
BEGIN IMMEDIATE                           Schreibsperre; ein zweiter Indexer wartet busy_timeout, dann LeaseHeld
  Manifest erneut lesen; run_id/doc_sha256 anders als im Plan → Abbruch "seit dem Plan geändert"
  alte Zeilen des doc_id löschen:          fts_* (über rid), chunks (Hilfstabellen per CASCADE), nodes, documents
                                           → Zahlen = swept
  neue Zeilen schreiben:                   chunks, chunk_identifiers, chunk_labels, fts_text/body/caption,
                                           nodes, documents
  Zählung prüfen (wie _verify_counts):     chunks und nodes des run_id = Batch
  manifest schreiben (wie _finalize):      status active, previous_run_id, counts, swept, history
  meta.data_version + 1
COMMIT
Fehler → ROLLBACK (alter Stand bleibt aktiv und wird weiter ausgeliefert) → ingest_log(failed, error)
```

- **Erst löschen, dann schreiben:** `chunk_id` = `{sha12}-{seq}` hängt am PDF-Hash. Eine Neu-Extraktion desselben PDFs erzeugt dieselben IDs. OpenSearch hat sie überschrieben; hier würde `UNIQUE` greifen. Innerhalb der Transaktion sieht kein Leser den Zwischenstand.
- **Entfällt:** Lease mit TTL, `--force` zum Übernehmen eines Locks, Status `indexing`/`failed` im Manifest. Ein abgestürzter Indexer hinterlässt keinen Lock; SQLite rollt beim nächsten Öffnen zurück.
- **Bleibt:** `--force` und `--replace` mit ihrer Bedeutung in der Plan-Logik.
- **`MAPPING_VERSION` 1 → 2.** Die Version geht in die `run_id` ein. Jedes Handbuch wird dadurch einmal neu geschrieben, aus den vorhandenen Run-Verzeichnissen und ohne dgs. (Im Notebook blieb die Version gleich, damit die `run_id`s vergleichbar sind: ✔ identisch mit OpenSearch.)
- **Dauer:** ✔ 0,3–0,6 s je Handbuch, drei Handbücher ≈ 1–2 s; Indexer-Prozess ≈ 70 MB RSS. Die Chat-Historie liegt in einer anderen Datei (`chat.db`) und wird nicht blockiert.
- **✔ Lesen und Schreiben gleichzeitig** (Skript `database_comparison/concurrent_write_test.py`, auf einer Kopie der Datei): 10 Lese-Threads mit kNN, BM25, Exakt und `fetch_chunks` liefen ohne Fehler, während ein zweiter Prozess alle drei Handbücher erzwungen neu schrieb. Top-1 vorher = während = nachher; die Leser übernahmen `data_version` 3 → 6 und luden die Vektormatrix neu; keine Latenzspitze. Zwei Indexer gleichzeitig: der zweite wartet an `BEGIN IMMEDIATE`, beide schreiben nacheinander. Die WAL-Datei wuchs dabei auf ≈ 10 MB und wurde automatisch zurückgeführt; `search.db` danach 6,4 MB (0,2 MB freie Seiten).

### 3.6 Chat: lesen, konsistent bleiben, neu laden

- **Verbindungen:** eine `sqlite3`-Verbindung pro Thread (Streamlit-Sitzungen sind Threads), mit `PRAGMA query_only = ON` und Autocommit.
- **Ein Snapshot pro Frage:** `retrieve()` öffnet am Anfang eine Lesetransaktion (`BEGIN`) und schließt sie nach `fetch_chunks`, also vor dem LLM. Alle drei Datenbankzugriffe einer Frage sehen damit denselben Stand. (offen: der Notebook-Shim arbeitet mit Autocommit je Abfrage.)
- **Graph und Vektormatrix** bilden zusammen ein unveränderliches Objekt mit der `data_version`, aus der sie geladen wurden. Jede Frage nimmt sich am Anfang eine Referenz darauf, wie heute `self.graph`.
- **Versionsprüfung pro Frage:** `SELECT value FROM meta WHERE key = 'data_version'` innerhalb der Lesetransaktion.
  - DB-Version **größer** als im Speicher: Graph und Vektoren in derselben Transaktion neu laden und unter Lock tauschen (wie `reload_graph()`, `retriever.py:88`). Den Katalog-Cache verwerfen.
  - DB-Version **kleiner** (ein anderer Thread hat schon neu geladen): Transaktion neu beginnen.
  - ✔ Im Test erkannten die Leser die neue `data_version` bei der nächsten Frage und luden Vektoren ohne Fehler neu.
- **⚠ Suche im Chat-Prozess:** Alle vier Kanäle laufen in Python-Threads unter dem GIL. Eine Frage allein ist schneller als mit OpenSearch (kNN + BM25 ≈ 6–8 ms statt ≈ 11–12 ms je Aufruf), zehn gleichzeitige Suchen sind langsamer (§4).
- **Start:** `meta` prüfen (`embedding_model`, `embedding_dim`, `analyzer_version`) gegen die Einstellungen, wie heute `_check_embedding_model`. Erst danach meldet der Pod „bereit“.

### 3.7 Kommandos (`osi`)

| Befehl | Neu |
|---|---|
| `bootstrap` | Datei anlegen, WAL setzen, Schema und `meta`. Bei bestehender Datei `schema_version` und `embedding_dim` prüfen (wie `check_indices`) |
| `ingest` | §3.5 |
| `status` | Zeilen je `doc_id`, Manifest, letzte Fehler aus `ingest_log`; handbuchübergreifende `node_id`s per `GROUP BY node_id HAVING COUNT(DISTINCT doc_id) > 1` |
| `verify` | `PRAGMA integrity_check`; FTS5 `INSERT INTO fts_text(fts_text) VALUES('integrity-check')` (je Tabelle); Zählungen gegen `manifest.counts`; Vektorlänge = `embedding_dim`, kein Nullvektor |
| `search` | dieselben Kanäle wie der Chat (Fehlersuche) |
| `delete` | alle Zeilen eines `doc_id` in einer Transaktion, `data_version` + 1 |
| `reanalyze` (neu) | FTS-Tabellen aus `chunks.source` neu aufbauen, `analyzer_version` setzen |

### 3.8 Codeänderungen je Datei

| Modul | Datei | Änderung |
|---|---|---|
| opensearch-index | `analysis.py` (neu) | deutscher Analyzer, `ANALYZER_VERSION` |
| | `sqlite_store.py` (neu) | Schema, Verbindungen (PRAGMAs), Schreibtransaktion, Lesefunktionen |
| | `indexer.py` | Plan-Logik bleibt; Lease → `BEGIN IMMEDIATE`; bulk/refresh/verify/sweep/finalize → §3.5; `_fail` → `ingest_log` |
| | `transform.py` | `build_batch` bleibt; statt `bulk_actions` Zeilen für die Tabellen |
| | `mappings.py` | `MAPPING_VERSION` = 2; OpenSearch-Mappings bleiben für das alte Backend |
| | `cli.py`, `settings.py` | Backend-Wahl `opensearch` \| `sqlite`, Pfad zu `search.db`, Befehl `reanalyze` |
| retrieval | `search.py` | Schnittstelle `SearchBackend` (`channels`, `fetch_chunks`, `fetch_documents`, `data_version`) mit zwei Implementierungen; Trefferformat wie heute |
| | `retriever.py` | Backend statt `make_client`; Schritt 3 übergibt Vektor, Text, IDs und Labels statt OpenSearch-Bodies; Snapshot und Versionsprüfung (§3.6); `check()` |
| | `graph.py`, `facts.py`, `fusion.py`, `guardrail.py`, `query.py` | **unverändert** |
| chat-system | `catalog.py` | liest `documents`; Cache bei neuer `data_version` verwerfen |
| | `wiring.py`, `cli.py` (doctor) | Backend statt OpenSearch-Client |
| integration | `process_and_index.py` | nur Backend-Einstellung |

Das OpenSearch-Backend bleibt per Einstellung erhalten, bis die Abnahme (§3.9) bestanden ist. Für den Vergleich werden beide gebraucht.

Umfang des Zusatzcodes im Notebook-Prototyp: Analyzer ≈ 190 Zeilen (`de_analysis.py`), Schema, Ingest, Kanäle inkl. Lucene-BM25 (≈ 40 Zeilen) und Shim ≈ 770 Zeilen (`sqlite_store.py`), ohne Tests. Das ist der Preis für die Gleichwertigkeit; er fällt bei OpenSearch nicht an.

### 3.9 Abnahme

1. **Golden-Test Analyzer:**
   - Für alle Chunk-Texte und alle Eval-Fragen die Tokens von OpenSearch holen (`POST /bhb-chunks/_analyze` mit `"analyzer": "de_text"`) und als Fixture speichern.
   - Der Python-Analyzer muss **identische** Tokens liefern.
   - Zusätzlich über `fts5vocab` prüfen, dass FTS5 die Tokens unverändert gespeichert hat.
   - ✔ bestanden (drei Handbücher: 910 Felder, 41 986 Tokens, 0 Abweichungen; `fts5vocab` = Python-Tokens).
2. **Kanal-Vergleich:** Fragen aus `test-quality/2026-09-09_v2/test-questions.yaml`, beide Backends nebeneinander. (Im Notebook mit 10 abgeleiteten Fragen; der Lauf mit dem Eval-Set ist **offen**.)
   - kNN, Identifier, Label: gleiche Treffermengen (Reihenfolge bei Gleichstand egal). ✔ identisch.
   - BM25: Überschneidung der Top-10, Vorschlag ≥ 0,9 im Mittel; Abweichungen einzeln ansehen. ✔ Lucene-Formel: Scores identisch; FTS5 `bm25()`: ≈ 0,9.
   - Guardrail-Urteil: identisch für alle Fragen. ✔ 10/10.
   - Fusionierte Top-10 inklusive Graph-Kanal: Überschneidung, Abweichungen ansehen. ✔ Überschneidung 0,97, gleiche Reihenfolge 7/10, Fakten 7/10, Entitäten 8/10, Kontext 7/10. Alle Abweichungen liegen bei Gleichstand in Exakt-Kanälen (§3.3). Gegenprobe: dieselben Daten in umgekehrter Reihenfolge in OpenSearch geschrieben, gelöschte Fassungen entfernt → OpenSearch gegen sich selbst: Reihenfolge 4/10, Fakten 7/10, Kontext 6/10. Die Abweichung zwischen den Speichern ist also nicht größer als die von OpenSearch gegen die eigene Indexgeschichte.
3. **Antwort-Eval** (Judge) ohne Rückschritt gegenüber OpenSearch. **offen.** Im Notebook antwortet das LLM auf die Beispielfrage aus beiden Kontexten inhaltsgleich (gleicher Verantwortlicher, gleiches Zitat). Mit der Lucene-Formel ist der Kontext bis auf Gleichstände gleich, der Judge-Eval also eine Bestätigung; **entscheidend wird er, falls FTS5-`bm25()` gewählt wird** (Kontext gleich 4/10, §6).

Erst danach wird OpenSearch abgeschaltet.

### 3.10 Rückfall: Dateitausch

Nur nötig, wenn der Indexer **nicht** auf dem Knoten des Chats laufen kann.

- Der Indexer baut irgendwo eine vollständige `search-<zeit>.db` (gleiches Schema) und kopiert sie auf die PVC.
- Dann benennt er sie atomar in `search.db` um.
- Der Chat erkennt den Tausch an der geänderten Inode (`os.stat(...).st_ino`), öffnet seine Verbindungen neu und lädt Graph und Vektoren neu.
- Offene Verbindungen lesen bis dahin die alte Datei weiter.

## 4. Verbindungen, mehrere Nutzer und parallele Aufrufe

**Zugriffe pro Frage:** 1× Embedding, 4 Kanäle, 1× Graph-Chunks, dann LLM. Mit SQLite sind das lokale Dateizugriffe im Millisekundenbereich statt HTTP-Aufrufe. ✔ kNN + BM25, ein Thread, 50 Aufrufe: SQLite p50 ≈ 6–8 ms, OpenSearch (lokaler Container) ≈ 11–12 ms; das Embedding (≈ 0,5 s) dominiert ohnehin.

**Parallele Antworten:** `max_concurrent_answers = 10` (`chat-system/src/chat_system/settings.py:47`). Die Semaphore wartet nicht (`service.py:453`): Die 11. gleichzeitige Frage bekommt die „busy“-Meldung. Die eigentliche Grenze ist das LLM (geplant: 3–5 parallele Streams, `technical_request.md` §3.1).

| | **OpenSearch** | **PostgreSQL** | **SQLite (WAL, gleicher Knoten)** | **Dateitausch** (§3.10) |
|---|---|---|---|---|
| Zugriff aus mehreren Containern | ja, über das Netz | ja, über das Netz | nur Pods **auf demselben Knoten** (gleiche RWO-PVC) | jeder Container hat seine eigene Kopie |
| Gleichzeitige Leser | viele | viele (MVCC) | viele (eine Verbindung pro Thread) | viele |
| Schreiber im Betrieb | ja, Konflikte über Versionen | ja, über Transaktionen | **einer** (`BEGIN IMMEDIATE`); Leser werden nicht blockiert | keiner |
| Neue Daten sichtbar | nach Refresh | nach Commit | nach Commit, ohne neu zu öffnen; Graph und Vektoren nach der Versionsprüfung | nach Neu-Öffnen |
| Netzlaufwerk | nicht nötig | nicht nötig | **nicht erlaubt**, auch nicht als RWO auf NFS | nicht nötig |
| Mehrere Chat-Replikas | ja | ja | nein | ja, je Replika eine Kopie |
| Verbindungen | HTTP-Client mit Pool | Connection-Pool | `sqlite3` pro Thread | `sqlite3` pro Thread |
| 10 gleichzeitige Suchen kNN+BM25 (gemessen, p50) | ≈ 50–70 ms, eigene Thread-Pools | nicht gemessen | ⚠ ≈ 1 000–1 150 ms (Lucene-Formel in Python) bzw. ≈ 375–415 ms (FTS5 `bm25()`), GIL-gebunden | wie SQLite |

**⚠ Parallelität (gemessen):** Die Suche läuft im Python-Prozess des Chats, und der GIL serialisiert den Python-Anteil (Lucene-Formel, Trefferaufbau). Eine Suche allein ist schneller als mit OpenSearch, zehn gleichzeitige dauern p50 ≈ 1 000–1 150 ms statt ≈ 50–70 ms (Durchsatz ≈ 9–10/s statt ≈ 120–150/s). Für `max_concurrent_answers = 10` mit 10–30 s LLM-Zeit je Antwort ist das unkritisch, weil je Antwort nur eine Suche anfällt; für einen eigenständigen Suchdienst nicht. `OPENBLAS_NUM_THREADS=1` ändert daran nichts, numpy ist nicht der Engpass. Auswege, falls nötig: die BM25-Berechnung vektorisieren (§6; nötig ohnehin ab einigen Tausend Chunks), FTS5-`bm25()` statt Lucene-Formel (bei 12 000 Chunks p50 ≈ 0,3 s mit 10 Threads, aber geringere Treue: Kontext gleich 4/10 statt 7/10), ein Prozess-Pool für die Suche, oder ein Server-Speicher (§8).

## 5. Aufbau unter Kubernetes

```
chat (Deployment, 1 Replika, Strategie Recreate)   Streamlit + retrieval + users + osi (im Image enthalten)
  └─ PVC (RWO, Block-Storage): chat.db + search.db (+ -wal, -shm) + runs/ (dgs-Ergebnisse)
indexer                                            ruft dgs über HTTP, schreibt search.db
ConfigMap: ontology.yaml                           für Indexer und Chat
extern: dgs (zentral) · LLM · Embedding · Ingress + IAM
```

- **Kein RWX-Volume.** `POST /v1/process` liefert das vollständige Ergebnis in der HTTP-Antwort (`docling-graph/src/docling_graph_service/api.py:91`); `integration/process_and_index.py` arbeitet bereits so.
  - Der Aufruf ist synchron und dauert 4–6 Minuten pro Handbuch. Hinter einem Ingress die Proxy-Timeouts erhöhen (oft 60 s) oder clusterintern aufrufen.
- **Indexer starten**, zwei Wege:
  - **manuell:** `kubectl exec deploy/chat -- osi ingest …`. `osi` ist im Chat-Image installiert (`chat-system/Dockerfile`).
  - **automatisiert:** Job mit dem Chat-Image und derselben PVC, mit `podAffinity` (required) auf das Chat-Label und `topologyKey: kubernetes.io/hostname`.
- **PVC:** `ReadWriteOnce`, nicht `ReadWriteOncePod`, denn der Job muss sie mitbenutzen. Die StorageClass muss **Block-Storage** sein (ext4/xfs auf einem Knoten). NFS-basierte Klassen brechen WAL, auch bei RWO. Das gilt schon heute für `chat.db`.
- **Gleiche UID/GID** in Chat und Job (`runAsUser: 10001`, `runAsGroup: 10001`, `fsGroup: 10001`). Beide schreiben die `-wal`- und `-shm`-Dateien.
- **numpy-Threads begrenzen:** `OPENBLAS_NUM_THREADS=1` (bzw. `OMP_NUM_THREADS`). Sonst zählt numpy die Kerne des Hosts statt des CPU-Limits, und der Pod wird gedrosselt. ✔ Auf die Suchlatenz hat die Einstellung keine messbare Wirkung; sie dient nur dem CPU-Limit.
- **Readiness** erst nach dem Laden von Graph und Vektoren.
- **Daten und Backup:**

  | Daten | Ort | Backup |
  |---|---|---|
  | `chat.db` (Gespräche, Kontingente) | PVC | **ja**, nicht wiederherstellbar. VolumeSnapshot oder online mit `VACUUM INTO`; nie die Datei im laufenden Betrieb kopieren |
  | `runs/` (dgs-Ergebnisse, 2–3 MB pro Handbuch, ~300 MB bei 100) | PVC; der Indexer schreibt sie wie `integration/process_and_index.py` | **ja**, mit demselben VolumeSnapshot. Sie sind die Grundlage für jeden Neuaufbau |
  | `search.db` | PVC | **nein**. Neuaufbau aus `runs/` in Minuten (✔ drei Handbücher ≈ 2 s, 5,8 MB; WAL während des Ingests bis ≈ 10 MB). Ohne `runs/` heißt Neuaufbau Neuverarbeitung über dgs: 5–8 h bei 100 Handbüchern, und das LLM wird belastet |
  | PDFs | Dokumentenablage | Quelle der Wahrheit (`technical_request.md` §6) |

## 6. Skalierung

| | 40 Handbücher / 10 Nutzer | 100 Handbücher / 40 Nutzer | Was zu tun ist |
|---|---|---|---|
| Chunks | ~5 000 | ~12 000 | – |
| Vektoren im RAM | 20 MB | 49 MB | – |
| kNN mit numpy, 1 Thread (gemessen) | 1,6 ms | 2,1 ms | – (50 000 Chunks: 9,5 ms) |
| kNN + BM25, 1 Thread (gemessen, 401 Chunks) | SQLite p50 ≈ 6–8 ms · OpenSearch ≈ 11–12 ms | – | – |
| 10 gleichzeitige Suchen kNN+BM25 (gemessen, 401 Chunks) | SQLite p50 ≈ 0,4 s (FTS5 `bm25()`) bis ≈ 1,2 s (Lucene-Formel) · OpenSearch ≈ 50–70 ms | ⚠ Suche im Chat-Prozess, GIL | unkritisch, solange je Antwort eine Suche auf 20–40 s LLM-Zeit kommt; sonst Prozess-Pool oder Server (§4, §8) |
| kNN+BM25 mit **Lucene-Formel in Python**, Chunks vervielfacht (gemessen: 4 010 bzw. 12 030 Chunks) | 1 Thread 53 ms · 10 Threads p50 5,4 s | 1 Thread 188 ms · 10 Threads **p50 20 s** | **⚠ skaliert in der Prototyp-Form nicht** (Python-Schleife über alle FTS5-Kandidaten, ≈ 2 500 je Frage bei 12 000 Chunks). Vor dem Bau vektorisieren: Termfrequenzen je Chunk als dünn besetzte Matrix, BM25 je Frage als Matrixprodukt |
| kNN+BM25 mit **FTS5 `bm25()`**, Chunks vervielfacht (gemessen) | 1 Thread 23 ms · 10 Threads p50 0,25 s | 1 Thread 56 ms · 10 Threads p50 0,3 s | skaliert (C-Code gibt den GIL frei), aber geringere Treue zu OpenSearch: mit dem echten Retriever Guardrail 10/10, Top-10-Überschneidung 0,93, Kontext gleich 4/10 (Lucene-Formel 7/10, OpenSearch gegen sich selbst 6/10) → Judge-Eval nötig |
| Chat-Pod Speicher | Limit 1 Gi | Graph + Vektoren größer | Limit auf 2 Gi, messen |
| Gleichzeitige Antworten (Annahme: 1 Frage / 2 min, 20–40 s pro Antwort) | ~2–3 | **~10**, Spitzen höher | Semaphore an die LLM-Kapazität anpassen oder kurz warten statt abweisen |
| LLM-Streams | 3–5 geplant | ~10–15 | **eigentlicher Engpass**: GPU-Kapazität bzw. Batching |
| Erstbefüllung über dgs | 2–3 h | ~5–8 h | dgs nimmt einen Auftrag zur Zeit; LLM teilt sich Ingest und Chat → außerhalb der Nutzungszeit |

**Grenzen dieser Variante:**

- **Eine Replika, keine HA.** Jeder Rollout ist ein kurzer Ausfall.
- **Mehrere Chat-Replikas** brauchen externe Datenbanken (§8).
- **⚠ Suche im Chat-Prozess (GIL):** Durchsatz ≈ 10–25 Suchen/s statt ≈ 120–150/s bei OpenSearch (§4).
- **⚠ BM25-Berechnung muss vektorisiert werden, bevor sie gebaut wird.** Die im Notebook geprüfte Lucene-Formel ist eine Python-Schleife über alle Kandidaten; sie ist bei 401 Chunks exakt und schnell genug, bei 12 000 Chunks aber 188 ms je Frage und 20 s bei 10 gleichzeitigen Suchen (Tabelle oben). Dieselbe Formel als Matrixprodukt über eine vorab gebaute Termfrequenz-Matrix ist Standard und behebt das; die Treue zu OpenSearch bleibt. Nicht gemessen, da nicht gebaut.

## 7. Empfehlung

1. **Bauen: SQLite + numpy** nach §3. Der Indexer schreibt in einer Transaktion im WAL-Modus auf demselben Knoten. Das OpenSearch-Backend bleibt bis zur Abnahme (§3.9) per Einstellung erhalten. ✔ Qualität im Notebook bestätigt (§3.9 Schritte 1–2 auf drei Handbüchern); Schritt 3 und der Lauf mit dem Eval-Set sind offen. ⚠ Vor dem Bau die BM25-Berechnung vektorisieren (§6), sonst trägt die Variante keine 100 Handbücher.
2. **Rückfall Dateitausch** (§3.10), falls der Indexer nicht auf dem Knoten des Chats laufen darf.
3. **HA oder mehrere Replikas:** §8. Je nach Plattform C (PostgreSQL für alles) oder D (OpenSearch + PostgreSQL).
4. **zvec und vec1:** nicht nötig. numpy deckt die exakte Vektorsuche ab (≈ 40 Zeilen, `VectorIndex` im Prototyp), FTS5 die Volltextsuche. **vec1** (Erweiterung des SQLite-Projekts, 0.7, laut eigener Roadmap „Testing is insufficient“) sucht ohne Modell ebenfalls exakt und muss daher dieselben Treffer liefern wie numpy (nicht gemessen); der ANN-Modus (IVFADC + OPQ) braucht Training und einen Neuaufbau je Ingest und bringt bei ≤ 12 000 Vektoren nichts (numpy: 2,1 ms je Suche, §6). Dagegen kostet vec1: nicht im Python-Modul `sqlite3`, nicht auf PyPI, muss als Erweiterung mit AVX2-Flags kompiliert, im Container ausgeliefert und per `enable_load_extension` geladen werden. `sqlite-vec` (PyPI) sucht ebenfalls nur exakt — bequemere Verpackung, kein besserer Algorithmus. ✔ zvec 0.7.0 geprüft: kNN identisch, Volltext braucht ebenfalls den Python-Analyzer, kein Filter auf Listenfelder, kein Lock und kein Dokumenttyp für Graph und Manifest — ohne Zusatzcode kein Ersatz, mit Zusatzcode kein Vorteil gegenüber SQLite.

## 8. Ausbaustufe: mehrere Replikas

Die Bauvorlage (§3) setzt **eine** Chat-Replika voraus: `chat.db` und `search.db` liegen auf einer RWO-PVC auf einem Knoten. Mit externen Datenbanken wird der Chat zustandslos und kann mit N Replikas auf mehreren Knoten laufen.

**Gewinn:**

| | 1 Replika (SQLite) | N Replikas (externe Datenbanken) |
|---|---|---|
| Ausfall eines Knotens | Ausfall, bis der Pod woanders neu startet | die übrigen Replikas antworten weiter |
| Updates | `Recreate`: kurzer Ausfall | `RollingUpdate`: ohne Ausfall |
| Neue Handbücher übernehmen | Neustart = kurzer Ausfall | rollierender Neustart, ohne Ausfall |
| CPU des Chats | ein Prozess | N Prozesse, über Knoten verteilt |
| Volume im Chat-Pod | RWO-Block-Storage, an einen Knoten gebunden | keines |
| Indexer | auf dem Knoten des Chats | beliebig |

**Kein Gewinn beim LLM:** Bei 40 Nutzern ist das LLM der Engpass (§6). Mehr Chat-Replikas teilen sich dieselben Streams.

**Voraussetzung: Die Datenbanken selbst sind hochverfügbar.** Sonst verschiebt sich nur der Single Point of Failure.

- OpenSearch: mindestens 3 Knoten (Quorum der Cluster-Manager), `number_of_replicas: 1`.
- PostgreSQL: Primary und Standby mit Failover, am besten von der Plattform betrieben (oder ein Operator wie CloudNativePG).

**Änderungen in der Anwendung:**

| Punkt | Heute | Mit N Replikas |
|---|---|---|
| Chat-Historie | SQLite | PostgreSQL: eine Umgebungsvariable (`technical_request.md` §7, bereits unterstützt) |
| Tageskontingent, Turn-Limits | in der Datenbank | funktionieren, weil PostgreSQL gemeinsam ist |
| `max_concurrent_answers = 10` | pro Prozess = Systemgrenze | **pro Replika**, Summe N × 10. Auf LLM-Kapazität ÷ N setzen oder ein Gateway vor dem LLM einreihen lassen |
| Datenbank-Migrationen (Alembic beim Start) | sicher bei einer Instanz | **einmal**, als Job vor dem Rollout, nicht in jeder Replika |
| Graph im Speicher | beim Start geladen, Reload nicht angebunden | jede Replika lädt selbst: Versionsprüfung (Manifest abfragen) oder rollierender Neustart |
| Streamlit-WebSocket | Affinität ohne Bedeutung | **Sticky Sessions** im Ingress. Fällt eine Replika aus, verbinden sich ihre Sitzungen neu; das Gespräch bleibt in PostgreSQL |
| Kubernetes | Deployment, `Recreate` | `RollingUpdate`, PodDisruptionBudget (`minAvailable: 1`), Anti-Affinität bzw. Topology Spread über Knoten |

**Optionen:**

| | **A: ein Pod** (§3) | **B: PostgreSQL für die Historie + SQLite-Kopie je Replika** | **C: PostgreSQL für alles** (mit pgvector) | **D: OpenSearch + PostgreSQL** (Plattform) |
|---|---|---|---|---|
| Chat-Replikas | 1 | N | N | N |
| Externe Datenbanken | keine | PostgreSQL | PostgreSQL | OpenSearch + PostgreSQL |
| Neue Handbücher erreichen den Chat | direkt | **jede Replika braucht eine Kopie**; die Verteilung ist Zusatzaufwand | zentral | zentral |
| Suchcode | Bauvorlage SQLite | Bauvorlage + Verteilung (§3.10) | neues Backend (pgvector + deutsche Volltextsuche) | **keiner**, wie heute |
| Qualität | ✔ Abnahme §3.9 Schritte 1–2 bestanden, Schritt 3 offen | wie A | Abnahme | Referenz |
| Passt, wenn | keine HA nötig | PostgreSQL vorhanden, kein OpenSearch, seltene Updates | PostgreSQL vorhanden, HA gewünscht | die Plattform betreibt beides |

**Weg dorthin:** Mit A beginnen. Der Ausbau bleibt offen:

- Die Chat-Historie wechselt per Umgebungsvariable nach PostgreSQL.
- Die Schnittstelle `SearchBackend` (§3.8) behält das OpenSearch-Backend und kann später ein pgvector-Backend aufnehmen.

Wird HA gefordert:

- stellt die Plattform nur PostgreSQL bereit → C;
- stellt sie beides bereit → D;
- B nur bei seltenen Updates.

## 9. Zusammenfassung für das Team

> **Suchspeicher: SQLite statt OpenSearch**
>
> OpenSearch und PostgreSQL sind eigene Datenbankserver, die wir betreiben und absichern müssten. OpenSearch braucht 2–4 GB JVM-Heap und eine Kernel-Einstellung auf dem Knoten (gemessen: ≈ 3,4 GiB RSS bei 2 GB Heap für drei Handbücher mit wenigen MB Daten). Beide bringen BM25-Volltextsuche und Vektorsuche fertig mit. Wir nutzen davon nur einen kleinen Teil: Fusion (RRF), Wissensgraph und Guardrail laufen bereits in unserem eigenen Python-Code.
>
> Bei unserer Datenmenge (rund 12 000 Textabschnitte bei 100 Handbüchern) läuft der Rest im Chat-Container:
>
> - **Vektorsuche:** numpy berechnet die exakt nächsten Nachbarn statt der Näherung von OpenSearch. Gemessen: identische Treffer.
> - **BM25-Volltextsuche:** die eingebaute Volltextsuche von SQLite (FTS5) findet die Kandidaten; die BM25-Formel von Lucene rechnen wir in Python nach, weil die eingebaute Formel von SQLite die Reihenfolge leicht ändert. Die deutsche Textanalyse (Stemming, Stoppwörter, Umlaute) läuft in Python. Das ist der heikle Teil; geprüft Token für Token gegen OpenSearch: 0 Abweichungen auf drei Handbüchern, BM25-Scores identisch.
> - **Exakter Abgleich von IDs und Namen:** indizierte SQLite-Tabellen.
> - **Ingest:** eine SQLite-Transaktion mit derselben Versionsprüfung wie heute. Ein unverändertes Handbuch wird übersprungen, und der Chat sieht nie einen halb geschriebenen Stand.
>
> Alles liegt in einer SQLite-Datei (`search.db`) auf dem Volume des Chats, mit festem Tabellenschema. Der Indexer prüft jeden Datensatz vor dem Schreiben, wie heute. Ein Vergleich mit dem unveränderten Retriever auf drei Handbüchern zeigt gleiche Guardrail-Urteile und gleiche Treffer bis auf Gleichstände, die OpenSearch selbst je nach Indexgeschichte anders auflöst. Die Bewertung der Antworten mit dem Eval-Set steht noch aus und erfolgt, bevor OpenSearch abgeschaltet wird.
>
> **Backups:** `search.db` braucht keines. Sie lässt sich in Minuten aus den gespeicherten dgs-Ergebnissen (2–3 MB pro Handbuch) neu aufbauen, die wir aufbewahren. Die Gesprächsdatenbank (`chat.db`) auf demselben Volume braucht Backups.
>
> Alle Nutzer lesen dieselben aufbereiteten Daten, gefiltert auf die Handbücher ihrer Gruppen.
>
> **Einschränkungen:**
>
> - eine Chat-Instanz: keine Hochverfügbarkeit, kurzer Ausfall bei jedem Update;
> - das Volume muss Block-Storage sein, kein NFS;
> - der Indexer läuft auf demselben Knoten wie der Chat (geprüft: der Chat liest ohne Fehler weiter, während er schreibt);
> - die Suche läuft im Chat-Prozess: bei 10 gleichzeitigen Suchen ≈ 1 s statt ≈ 50–70 ms mit OpenSearch — bei 10–30 s LLM-Zeit je Antwort unkritisch, für einen Suchdienst nicht.
>
> Wird Hochverfügbarkeit gefordert, ist der Ausbau auf mehrere Instanzen vorbereitet: Die Chat-Historie wechselt nach PostgreSQL, die Suche nach PostgreSQL oder OpenSearch der Plattform (§8).
>
> **Bleibende externe Anbindungen:** LLM-Endpunkt, Embedding-Endpunkt, Ingress mit PGA (Nutzeridentität) und der zentrale dgs-Dienst.

## Quellen

- SQLite: [FTS5](https://www.sqlite.org/fts5.html) (bm25, Abfragesyntax, Tokenizer), [WAL](https://www.sqlite.org/wal.html)
- vec1: [Übersicht](https://sqlite.org/vec1/doc/trunk/doc/vec1.md), [Benutzerhandbuch](https://sqlite.org/vec1/doc/trunk/doc/vec1intro.md)
- zvec: [Startseite](https://zvec.org/en/), [GitHub](https://github.com/alibaba/zvec), [Collection öffnen (`read_only`)](https://zvec.org/en/docs/db/collections/open/), [Volltextindex](https://zvec.org/en/docs/db/concepts/fts-index/)
- Kubernetes: [Access Modes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/#access-modes)
- Nachweis: `database_comparison/vergleich.ipynb` (ausgeführt 2026-10-06, Zahlen je Frage, Lastprobe, Gegenprobe), `database_comparison/README.md`
