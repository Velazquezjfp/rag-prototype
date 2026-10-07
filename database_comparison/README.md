# database_comparison — Suchspeicher-Vergleich im Notebook

Prüft mit den echten dgs-Ergebnissen (`out/remote-zsd`, `out/remote-caas`, `out/remote-system-event`), ob ein
eingebetteter Speicher **SQLite (FTS5) + numpy** OpenSearch ersetzen kann, ohne die Antwortqualität zu verändern,
und was das an Skalierung und Verfügbarkeit kostet. **zvec** wird als Machbarkeit mitgeprüft. Grundlage:
[`../SUCHSPEICHER-VERGLEICH.md`](../SUCHSPEICHER-VERGLEICH.md) (§3 = Bauvorlage, §3.9 = Abnahme).

Der Kern des Nachweises: der **unveränderte Retriever** (`rag_retrieval`) läuft einmal gegen OpenSearch und einmal
gegen SQLite; verglichen wird alles, was der Prompt sieht. Nichts in `opensearch-index/`, `retrieval/` oder den
anderen Modulen wird geändert — sie werden nur importiert.

## Dateien

| Datei | Inhalt |
|---|---|
| `vergleich.ipynb` | das Notebook (deutsch): Variablen → Funktionsliste → Daten → OpenSearch (Index, Retrieval Schritt für Schritt, RRF) → SQLite + numpy → zvec → 10-Fragen-Batch + Gegenprobe → LLM-Antworten → Checkliste → Vor-/Nachteile |
| `de_analysis.py` | Port des OpenSearch-Analyzers `de_text` (Lucene `StandardTokenizer`, Stoppwörter `_german_`, `GermanNormalizationFilter`, `GermanLightStemmer`) + FTS5-Hilfen |
| `sqlite_store.py` | Schema §3.2, Ingest in einer Transaktion §3.5 (über `opensearch_index.transform.build_batch`), die vier Kanäle als SQL/numpy §3.3, Shim-Client (`msearch`/`mget`/`search`) für den echten Retriever |
| `nbhelpers.py` | Tabellen für die Indizes, Kanal- und Ergebnisvergleich (gleichstandsbewusst), Kontext-Normalisierung, Ressourcen- und Lastmessung, optionale Re-Vektorisierung |
| `scale_test.py` | Chunks auf einer Kopie 10× und 30× vervielfacht (≈ 4 000 / 12 000): Latenz kNN+BM25 für Lucene-Formel und FTS5 `bm25()`, 1 und 10 Threads (`data/scale/`) |
| `bm25_variants_e2e.py` | echter Retriever auf OpenSearch, SQLite mit Lucene-Formel und SQLite mit FTS5 `bm25()` über die 10 Batch-Fragen |
| `concurrent_write_test.py` | Chat und Indexer auf derselben Datei: 10 Lese-Threads, während ein zweiter Prozess alle Handbücher neu schreibt; zwei Indexer gleichzeitig (arbeitet auf einer Kopie unter `data/conc/`) |
| `requirements.txt`, `.env.example` | Umgebung; `.env`, `.venv/`, `data/` sind gitignored |

## Einrichtung und Start

```bash
cd database_comparison
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt     # installiert ../opensearch-index und ../retrieval editierbar
cp .env.example .env                                                     # Endpunkte/Schlüssel eintragen (lokal: LiteLLM :4000, bge-m3, gemini-dev)
.venv/bin/python -m ipykernel install --user --name database-comparison --display-name "Python (database_comparison)"
(cd ../opensearch-index && make up)                                      # lokaler OpenSearch-Container
.venv/bin/jupyter lab vergleich.ipynb                                    # Kernel: Python (database_comparison)
```

Headless: `.venv/bin/jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=1800 vergleich.ipynb`

Schalter in Zelle 1: `FRAGE` (Beispiel), `FRAGEN_BATCH`, `RUN_LLM`, `REINDEX_OPENSEARCH` (Läufe erzwungen neu
schreiben + Gegenprobe OpenSearch↔OpenSearch), `REEMBED` (Chunks mit dem konfigurierten Embedding-Modell neu
vektorisieren → `data/reembedded/`, dann damit indexieren — so lässt sich derselbe Test mit anderem Modell wiederholen).
Modelle und Endpunkte stehen in `.env` (`RAG__*`, `OSI__*`, `REMOTE_*`).

## Was das Notebook belegt (Stand 2026-10-06, drei Handbücher, bge-m3)

- **Deutsche Analyse:** Python-Analyzer = OpenSearch `_analyze` auf allen 910 Chunk-Feldern (41 986 Tokens, 0 Abweichungen).
- **BM25:** FTS5s eigenes `bm25()` weicht in der Reihenfolge ab (Top-10-Überschneidung ≈ 0,9–0,97); mit der in Python
  nachgerechneten Lucene-Formel sind die Scores identisch (Δ = 0), sofern der OpenSearch-Index keine gelöschten
  Fassungen enthält. Das ist ein zusätzlicher Baustein (~40 Zeilen).
- **BM25-Drift in OpenSearch:** erzwungenes Neuschreiben derselben `_id`s hinterlässt die alten Fassungen als gelöschte
  Dokumente im Lucene-Segment; `N` und `n` zählen sie mit, bis ein Merge sie entfernt (gemessen 2026-10-06: 2 005 gelöschte
  neben 401 aktiven Chunks, `N` = 2 406, max |Δ Score| 0,39, ein anderes BM25-Top-1; nach `_forcemerge?only_expunge_deletes=true`
  Δ = 0). Das Notebook entfernt gelöschte Fassungen nach jedem Neuschreiben (4.1, 7.1) und zeigt `N` laut `explain`.
  SQLite kennt den Effekt nicht.
- **kNN, Identifier, Label:** gleiche Treffermengen. OpenSearch bewertet `term`-Treffer auf keyword-Feldern als
  `ConstantScore` 1,0 je Begriff — nicht Σ idf, wie §3.3 annimmt (Doku anpassen).
- **Gleichstände:** die Reihenfolge gleich bewerteter Treffer folgt in OpenSearch der Indexposition. Daraus entstehen
  die verbleibenden Unterschiede in fusionierten Top-10 und Fakten (Batch: ~7 von 10 Fragen identisch) — eine
  Eigenschaft der Kanal-Logik: dieselben Daten in umgekehrter Reihenfolge in OpenSearch geschrieben, und OpenSearch
  weicht im selben Maß von sich selbst ab (Gegenprobe 7.1).
- **Kontext:** gleich bis auf zwei Reihenfolge-Artefakte — OpenSearch mischt Objektschlüssel bei `_source`-Filterung
  (SQLite liefert die gespeicherte Reihenfolge), und der Graph übernimmt Label/Aliase handbuchübergreifender Knoten
  vom zuerst geladenen Handbuch (OpenSearch: Indexreihenfolge, SQLite: `doc_id`; für den Vergleich gleich gesetzt).
- **Ressourcen:** OpenSearch-Container ≈ 3,3–3,4 GiB RSS (konfigurierter Heap 2 GB) für ≈ 8 MB Chunk-Index; SQLite-Datei
  ≈ 6 MB, Ingest der drei Handbücher ≈ 1–2 s, kNN + BM25 ein Thread p50 ≈ 6–8 ms (OpenSearch ≈ 11–12 ms), Vektormatrix 1,6 MiB im Prozess.
- **Lesen während des Schreibens** (`concurrent_write_test.py`, Kopie der Datei): 10 Lese-Threads (kNN, BM25, Exakt, fetch)
  liefen fehlerfrei, während ein zweiter Prozess alle drei Handbücher erzwungen neu schrieb (0,5–0,6 s je Handbuch,
  Prozess ≈ 75 MB RSS); Top-1 unverändert, `data_version` 3 → 6 übernommen und Vektormatrix neu geladen, keine
  Latenzspitze. Zwei Indexer gleichzeitig serialisieren an `BEGIN IMMEDIATE`. WAL wächst dabei auf ≈ 10–12 MB und wird
  automatisch zurückgeführt; Datei danach 6,4 MB.
- **Parallelität (Nachteil):** die eingebettete Suche läuft im Python-Prozess des Chats und ist GIL-gebunden — bei
  10 gleichzeitigen Suchen p50 ≈ 0,4 s (FTS5 `bm25()`) bis ≈ 1,0–1,2 s (Lucene-Formel in Python), OpenSearch ≈ 50–70 ms.
  Für ≤ 10 gleichzeitige Antworten mit je 10–30 s LLM-Zeit unkritisch, für einen Suchdienst nicht.
- **Skalierung der Lucene-Formel (`scale_test.py`, Chunks vervielfacht):** die Python-Schleife über alle FTS5-Kandidaten
  ist bei 401 Chunks schnell (9 ms), bei 4 010 Chunks 53 ms / 10 Threads p50 5,4 s und bei 12 030 Chunks 188 ms / 10 Threads
  p50 20 s — in dieser Form nicht tragfähig für 100 Handbücher; vor dem Bau als Matrixprodukt über eine Termfrequenz-Matrix
  umsetzen. FTS5 `bm25()` skaliert (12 030 Chunks: 56 ms / 10 Threads 0,3 s), ist aber weniger treu: mit dem echten Retriever
  (`bm25_variants_e2e.py`) Guardrail 10/10, Top-10-Überschneidung 0,93, Kontext gleich 4/10 (Lucene-Formel 7/10).
- **zvec 0.7.0:** kNN identisch (FLAT, cosine); Volltext mit eigener Analyse (Snowball german, keine Stoppwörter)
  nur ≈ 0,6 Top-10-Überschneidung mit OpenSearch-BM25, mit vorab analysierten Tokens 1,0 — der Analyzer-Port wäre
  also auch hier nötig; Filter auf `ARRAY_STRING` (Identifier/Label) nicht gefunden, kein Lock/Manifest — ohne
  Zusatzcode kein Ersatz.

Die Zahlen je Frage (Batch, Gegenprobe, Lastprobe) stehen im ausgeführten Notebook; sie ändern sich mit Daten,
Modell und Indexgeschichte.
