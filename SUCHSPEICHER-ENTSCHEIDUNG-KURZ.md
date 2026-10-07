# Entscheidung Suchspeicher: OpenSearch 3.8.0 behalten oder zu SQLite 3.46.1 wechseln

Stand 2026-10-06. Zahlen aus `database_comparison/vergleich.ipynb` (drei Handbücher, 401 Chunks, unveränderter Retriever gegen beide Speicher). Langfassung: `SUCHSPEICHER-VERGLEICH.md`.

## Entscheidung

**Wechsel zu SQLite 3.46.1 (FTS5) + numpy im Chat-Container.** OpenSearch bleibt bis zur Abnahme per Einstellung schaltbar.

## OpenSearch ist schwer

Was eine echte Installation braucht (`opensearch-index/compose.yaml`, `DEPLOY.md`):

1. **TLS und Nutzer:** heute Security-Plugin aus (HTTP ohne Auth, nur loopback); produktiv Zertifikate, Admin-Passwort, Nutzerkonfiguration.
2. **Speicher, nicht Platte:** JVM-Heap 2 GB + ~1 GB; gemessen 3,4 GiB RSS für 8 MB Indexdaten, unabhängig von der Datenmenge. Platte ist klein: 8 MB je 401 Chunks, hochgerechnet ≈ 240 MB bei 100 Handbüchern.
3. **Knoten-Einstellungen:** `vm.max_map_count ≥ 262144`, ulimits `memlock`/`nofile`; eigener Container mit eigener PVC; Image ≈ 2 GB über Artifactory oder `docker load`; Backup über Snapshot-Repository; Endpunkt und Zugangsdaten in Chat und Indexer.

**Pro:** eigenständiger, skalierbarer Dienst; ≈ 120–150 Suchen/s; mit 3 Knoten hochverfügbar; über das Netz erreichbar.
**Contra:** für ≈ 12 000 Chunks bei 100 Handbüchern überdimensioniert. Die Vektorsuche braucht keinen Server: exakte numpy-Suche liefert dieselben Top-20 wie OpenSearch-HNSW in 2,1 ms bei 12 000 und 9,5 ms bei 50 000 Vektoren.

## Prämisse für die Alternativen

Weniger externe Abhängigkeiten, weniger Aufwand, weniger Ressourcen gewinnt — ohne Qualitätsverlust, und Suchzeit im Millisekundenbereich; unter Last sind 1–2 s je Suche tragbar, weil je Antwort eine Suche auf 10–30 s LLM-Zeit kommt.

## Bester Kandidat nach Test: SQLite 3.46.1 + numpy

Version: SQLite **3.46.1** aus dem Python-Modul `sqlite3` des Images `python:3.12-slim` (Debian trixie); FTS5 im Image geprüft. Lokal getestet mit 3.45.1. numpy ≥ 2.0.

**Nicht „Suche in JSON-Objekten“:** Der Indexer liest wie heute die dgs-Antwort (`response.json`), baut mit dem vorhandenen Code dieselben Datensätze und schreibt sie in Tabellen einer Datei `search.db`:

| Tabelle | Inhalt | heute |
|---|---|---|
| `chunks` | `chunk_id`, `doc_id`, `run_id`, **Vektor als float32-BLOB**, Datensatz als JSON | `bhb-chunks` |
| `fts_text`, `fts_body`, `fts_caption` (FTS5) | Tokens des deutschen Analyzers je Feld | Lucene-Index |
| `chunk_identifiers`, `chunk_labels` | ein Eintrag je Begriff und Chunk, indiziert | `keyword`-Felder |
| `documents`, `nodes`, `manifest`, `meta` | Graph und Markdown als JSON, Knoten, letzter Stand je Handbuch, `data_version` | `bhb-documents`, `-nodes`, `-manifest` |

Vektoren werden beim Chat-Start aus `chunks` in eine numpy-Matrix geladen (1,6 MiB bei 401 Chunks, 49 MB bei 12 000).

**Pro:** kein zweiter Dienst, läuft im Chat-Container, eine Datei auf der Chat-PVC, keine Verbindungen zu konfigurieren, kein Backup (Neuaufbau aus den aufbewahrten dgs-Ergebnissen in Minuten). Eine Suche 6–8 ms statt 11–12 ms.
**Contra:** genau eine Chat-Instanz (keine HA, kurzer Ausfall je Rollout); Block-Storage Pflicht, kein NFS; Suche im Chat-Prozess: ≈ 10–25 Suchen/s statt ≈ 120–150/s.

**Was die Nutzerzahl begrenzt:** Annahme 1 Frage je 2 min, 20–40 s je Antwort.

| | 10 Nutzer / 40 Handbücher | 40 Nutzer / 100 Handbücher |
|---|---|---|
| gleichzeitige Antworten | ≈ 2–3 | ≈ 10 (`max_concurrent_answers = 10`) |
| LLM-Streams | 3–5 | 10–15 → **Engpass GPU** |
| Suche in SQLite | unkritisch | unkritisch mit vektorisiertem BM25 |
| Chat-Pod | ein Prozess, ≥ 1 Kern, 2 Gi RAM | gleich; mehr Prozesse = Replikas = externe DB |

Außer der GPU skaliert nur der Chat-Pod (CPU, RAM), und der bleibt bei dieser Variante ein Prozess. Für ein Pilotszenario mit 10 Nutzern reicht ein Pod; 10 *gleichzeitig* antwortende Nutzer brauchen 10 LLM-Streams. GPU laut `technical_request.md` §3.1: `gemma4:26b`, 26–30B 4-bit ≈ 16–20 GB + KV-Cache → eine 48-GB-GPU für 3–5 Streams. Ob sie 10 Streams trägt, hängt vom LLM-Server ab, nicht vom Suchspeicher (offen).

## Begründung

Alle Nutzer lesen dieselben Daten; Filter nach Handbuch und Nutzergruppe wirken in allen Kanälen (`doc_ids`). Ausfallzeit ist im Pilot nicht kritisch. Keine Integration in andere Systeme geplant; ein späterer Wechsel zu OpenSearch bleibt möglich (dgs-Ergebnisse bleiben erhalten, OpenSearch-Backend bleibt im Code).

**OpenSearch wäre vorzuziehen, wenn:** Hochverfügbarkeit oder mehrere Chat-Replikas gefordert sind; andere Systeme (z. B. weitere Agenten) den Index über das Netz lesen sollen; die Suche ein eigener Dienst mit > 25 Suchen/s wird; die Plattform nur NFS bietet.
**Einschränkung ja:** mit SQLite sind Index und Daten nur über den Chat-Prozess oder eine Kopie der Datei erreichbar, nicht über das Netz.

## Nötige Suchbausteine

| Baustein | Warum |
|---|---|
| **Vektorsuche mit Filter** | findet Passagen gleicher Bedeutung mit anderen Worten; Filter nach Handbuch muss in der Suche wirken |
| **BM25 mit deutscher Analyse** | „Zertifikate“ muss „Zertifikat“ finden |
| **Exakter Abgleich auf IDs und Labels** | `SOP-ZSD-06` und Namen dürfen nicht zerlegt werden; starke Evidenz für den Guardrail |
| **Lesen per ID, atomares Schreiben, JSON-Blobs** | Graph-Chunks je Frage; kein halber Stand sichtbar; Graph wird beim Start geladen |

RRF, Graph, Guardrail und Prompt laufen bereits in Python — kein Speicher nötig.

## Der anspruchsvollste Baustein: BM25

1. **Deutsche Analyse fehlt in SQLite** und musste in Python nachgebaut werden. Beispiel: `Zertifikate`/`Zertifikat` → `zertifikat`, `Störungen` → `storung`, `Dispatcher-Konfiguration` → `dispatch konfiguration`. Ohne sie findet „Störung“ keinen Chunk mit „Störungen“, und der Guardrail urteilt anders. Geprüft: 41 986 Tokens, 0 Abweichungen zu OpenSearch.
2. **Die Rangfolge hängt an der Formel.** SQLites eigenes `bm25()` ordnet anders (Top-10-Überschneidung ≈ 0,9, LLM-Kontext nur 4/10 gleich); die Lucene-Formel in Python nachgerechnet liefert identische Scores (Kontext 7/10 gleich, Rest Gleichstände).
3. **Die Nachrechnung skaliert so nicht:** 401 Chunks 9 ms, 12 030 Chunks 188 ms und 20 s bei 10 gleichzeitigen Suchen. **Vor dem Bau vektorisieren** (Matrixprodukt) oder `bm25()` von FTS5 nehmen (0,3 s) und die Qualität per Judge-Eval nachweisen.

## Wie SQLite läuft

- **Auf der Platte:** `search.db` (WAL) neben `chat.db` auf der RWO-PVC des Chats, Block-Storage. Indexer im Chat-Pod (`kubectl exec`) oder als Job auf demselben Knoten; schreibt ein Handbuch in einer Transaktion (0,3–0,6 s), der Chat liest währenddessen fehlerfrei weiter (getestet).
- **Im Speicher:** Graph und Vektormatrix; nach einem Ingest einmal neu geladen (`data_version`).
- **Neustart:** Datei bleibt, Chat lädt neu. Verlust: Neuaufbau aus `runs/` ohne dgs und LLM.
- **Gleiches Verhalten:** Guardrail 10/10, Top-10-Überschneidung 0,97, Kontext 7/10 gleich; OpenSearch gegen die eigene Indexgeschichte 6/10. Judge-Eval mit dem Eval-Set offen.
- **100–200 Handbücher** (12 000–24 000 Chunks): Vektoren 49–98 MB RAM, Datei hochgerechnet 175–350 MB, kNN 2–4 ms; BM25 nur vektorisiert oder mit FTS5 `bm25()`.

## Referenztabelle

| | **OpenSearch 3.8.0** | **PostgreSQL + pgvector** | **zvec 0.7.0** | **SQLite 3.46.1 + numpy** |
|---|---|---|---|---|
| Betrieb | eigener Server | eigener Server | Bibliothek, Verzeichnis | Bibliothek, eine Datei |
| Ressourcen | 3,4 GiB RSS | nicht gemessen | 8,3 MB | 5,8 MB + 1,6 MiB RAM |
| Vektorsuche | HNSW, approximativ | HNSW/exakt | FLAT identisch | exakt, identisch |
| Deutsche Analyse | eingebaut | eingebaut | Snowball ohne Stoppwörter → Python-Analyzer nötig | nicht eingebaut → Python-Analyzer (0 Abweichungen) |
| BM25 wie OpenSearch | Referenz | nicht gemessen | eigene Formel | Lucene-Formel nachgerechnet: identisch; FTS5 `bm25()` ≈ 0,9 |
| IDs/Labels exakt | ja | ja | kein Filter auf Listen gefunden | Hilfstabellen, gleiche Treffer |
| 1 Suche / 10 gleichzeitig | 11–12 ms / 50–70 ms | – | – | 6–8 ms / 0,4–1,2 s |
| HA, Netzzugriff | ja | ja | nein | nein |
| Zusatzcode | keiner | neues Backend | Analyzer + Strukturen + Lock | ≈ 190 + ≈ 770 Zeilen |
| Qualität gleich | Referenz | wahrscheinlich, nicht gemessen | nur mit Zusatzcode | Guardrail 10/10, Top-10 0,97 |
| Urteil | behalten bei HA/Netzzugriff | Weg bei HA ohne OpenSearch | kein Vorteil | **gewählt** |

Vektor-Erweiterungen für SQLite (vec1, sqlite-vec) nicht nötig: suchen ohne Modell ebenfalls exakt wie numpy, ANN-Modus braucht Training; vec1 müsste kompiliert und ausgeliefert werden.
