# Suchspeicher: OpenSearch und Alternativen

Stand: 2026-10-02. Grundlage: `technical_request.md`, `ARCHITECTURE-DATAFLOW.md`, `RETRIEVAL-FLOW.md` und der Code in `opensearch-index/` und `retrieval/`.

## 1. Was der Speicher leisten muss – und warum

| Komponente | Wofür im System | Warum sie für die Antwortqualität zählt |
|---|---|---|
| **Vektorsuche mit Filter** (`doc_ids`) | k-NN-Kanal, Mandantentrennung | Findet Passagen mit gleicher Bedeutung, aber anderen Worten. Der Filter muss *in* der Suche wirken, sonst fehlen Treffer oder es werden fremde Handbücher sichtbar. |
| **BM25 mit deutscher Analyse** (Stemming, Stoppwörter, Umlaute) | BM25-Kanal | „Zertifikate“ soll „Zertifikat“ finden. **Größtes Qualitätsrisiko beim Wechsel.** |
| **Exakter Abgleich auf String-Listen** (einmal wörtlich, einmal kleingeschrieben) | Identifier- und Label-Kanal | IDs wie `SOP-ZSD-06` und Namen dürfen nicht zerlegt werden. Sie liefern die „starke Evidenz“ für den Guardrail. |
| **Lesen per ID, mehrere Suchen pro Aufruf** | Graph-Chunks (`mget`), 4 Kanäle (`msearch`) | Hält die Latenz pro Frage niedrig. |
| **Atomares Schreiben mit Versionsprüfung** | Manifest als Lock | Verhindert, dass zwei Ingests dasselbe Handbuch gleichzeitig schreiben. |
| **Löschen per Abfrage, JSON-Blobs speichern** | Sweep alter Runs, `graph`/`markdown` in `bhb-documents` | Saubere Versionswechsel; der Graph wird beim Chat-Start geladen. |

Nicht nötig, weil es bereits im Python-Code läuft: RRF-Fusion, Graph-Traversierung, Prompt-Aufbau.

Datenmenge heute: ~600 Chunks (5 Handbücher). Bei dieser Menge ist sogar eine exakte Vektorsuche (Brute Force) schnell genug. Der Index-Typ (HNSW, IVF, PQ) spielt für die Qualität kaum eine Rolle; die **Textanalyse** schon.

## 2. Vergleich

| Kriterium | **OpenSearch** (heute) | **PostgreSQL + pgvector** | **zvec** (Alibaba) | **SQLite vec1** (+ FTS5) |
|---|---|---|---|---|
| Betriebsform | Server (HTTP) | Server (TCP) | Bibliothek im Prozess | Bibliothek im Prozess, eine Datei |
| Reife | stabil, ≥ 2.19 | stabil | 0.7.0 (Aug. 2026), jung | 0.7, laut eigener Doku „Testing is insufficient“ |
| Lizenz | Apache-2.0 | PostgreSQL-Lizenz | Apache-2.0 | SQLite-Projekt |
| Vektorindex | HNSW (Lucene) | HNSW, IVFFlat oder exakt | HNSW, IVF, DiskANN, Flat; Quantisierung | IVF + PQ (Training nötig) |
| Filter in der Vektorsuche | ja | ja (`WHERE doc_id = ANY(...)`) | ja (Skalarfilter) | nur einfache Vergleiche; `IN`-Listen erst nachträglich |
| Volltext / BM25 | ja, BM25 | ja; Ranking `ts_rank` (BM25 mit ParadeDB `pg_search`) | ja, BM25 (seit 0.5) | nur über FTS5 (BM25) |
| **Deutsche Analyse** | ja (`light_german`, Stoppwörter, Normalisierung) | **ja** (`to_tsvector('german')`, Snowball) | **unklar** (Tokenizer standard/jieba/n-gram; Sprache des Stemmers nicht dokumentiert) | **nein** (FTS5-Stemmer nur Englisch/Porter) |
| Exakte Liste / kleingeschrieben | `keyword` + Normalizer | `text[]` + GIN, `lower()` | `ARRAY_STRING` + Invert-Index | Hilfstabelle nötig |
| Hybrid / Fusion | im Client (RRF) | im Client | eingebaut (RRF, gewichtet) oder Client | im Client |
| Lock / Versionsprüfung | `seq_no` / `primary_term` | Transaktionen, `SELECT … FOR UPDATE` | keine; Lösung über Single-Writer-Regel | Datei-Lock der DB |
| Run ersetzen + Sweep | mehrere Schritte | **eine Transaktion** | mehrere Schritte | eine Transaktion |
| Änderungsumfang im Code | – | `mappings.py`, `search.py`, `indexer.py` neu; Rest bleibt | dieselben Module + Lock-Konzept + Deployment | dieselben + Hilfstabellen + Ersatz für deutsches Stemming |
| **Qualität gleich halten?** | Referenz | **ja** | wahrscheinlich, **nach Test** der deutschen BM25 | **nein** (BM25 ohne deutsches Stemming) |

## 3. Verbindungen, mehrere Nutzer und parallele Aufrufe

**Zugriffe pro Frage (heute):** 1× Embedding, 1× `msearch` (4 Kanäle), 1× `mget` (Graph-Chunks), dann LLM. Der Graph liegt im Speicher des Chat-Containers. Gleichzeitige Fragen begrenzt die Semaphore in `chat_system.ask()`.

**Schreiber:** nur der Indexer, als einmaliger Job. **Leser:** der Chat, später evtl. mehrere Replikas.

| | **OpenSearch** | **PostgreSQL** | **zvec** | **SQLite vec1** |
|---|---|---|---|---|
| Zugriff aus mehreren Containern | ja, über das Netz | ja, über das Netz | nur über gemeinsames Verzeichnis | nur über gemeinsame Datei |
| Gleichzeitige Leser | viele (Thread-Pools) | viele (MVCC) | mehrere Prozesse lesen | mehrere (WAL-Modus) |
| Gleichzeitige Schreiber | ja, Konflikte über Versionen | ja, über Transaktionen | **ein Prozess** exklusiv | **einer** zur Zeit |
| Lesen während eines Ingests | ja | ja; neuer Stand erst nach Commit sichtbar | ja; Leser müssen neu öffnen, um Neues zu sehen | ja (WAL) |
| Netzlaufwerk (RWX-Volume) | nicht nötig | nicht nötig | **riskant** (Datei-Locks) | **bekannt problematisch** |
| Mehrere Chat-Replikas | ja | ja | nur auf demselben Knoten/Volume | nur auf demselben Knoten/Volume |
| Verbindungen | HTTP-Client mit Pool | Connection-Pool (z. B. psycopg-Pool) | keine; Objekt im Prozess | keine; Datei-Handle |

**Folge für die Architektur:**

- **Server-Lösungen (OpenSearch, PostgreSQL):** Die Container-Aufteilung aus `technical_request.md` bleibt unverändert. Indexer und Chat sprechen beide über das Netz mit derselben Datenbank.
- **Eingebettete Lösungen (zvec, vec1):** Die Datenbank wird zu Dateien. Der Indexer muss
  - im selben Pod laufen wie der Chat, oder
  - eine fertige Kopie schreiben, die der Chat danach nur liest und neu öffnet.

  Mehrere Chat-Replikas und Netzlaufwerke werden dadurch schwierig.

## 4. Empfehlung

1. **Getrennte Container behalten:** **PostgreSQL + pgvector**. Die deutsche Volltextsuche ist eingebaut, Lock und Sweep laufen als Transaktion, und die Qualität bleibt erreichbar. Auch die Chat-Historie (heute SQLite) kann mit umziehen.
2. **Eine Maschine, eingebettet:** **zvec**, aber erst nach einem Test: deutsche BM25-Treffer gegen OpenSearch auf den Eval-Fragen vergleichen.
3. **vec1:** kein Ersatz. Höchstens als Vektortabelle neben einer anderen Lösung für deutschen Volltext.

## Quellen

- vec1: [Übersicht](https://sqlite.org/vec1/doc/trunk/doc/vec1.md), [Benutzerhandbuch](https://sqlite.org/vec1/doc/trunk/doc/vec1intro.md)
- zvec: [Startseite](https://zvec.org/en/), [GitHub](https://github.com/alibaba/zvec), [Volltextindex](https://zvec.org/en/docs/db/concepts/fts-index/), [FTS-Design](https://zvec.org/en/blog/2026-07-07-zvec-fts/), [Reranker](https://zvec.org/en/docs/db/reranker/), [Collection anlegen](https://zvec.org/en/docs/db/collections/create/)
