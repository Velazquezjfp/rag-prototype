# Entscheidung: OpenSearch behalten oder zu SQLite wechseln

Stand: 2026-10-06 · Status: **entschieden für SQLite, Abnahme offen** (OpenSearch bleibt bis dahin per Einstellung
schaltbar). Kurzfassung von [`SUCHSPEICHER-VERGLEICH.md`](SUCHSPEICHER-VERGLEICH.md); alle Zahlen stammen aus dem
Notebook `database_comparison/vergleich.ipynb` und den Skripten daneben (drei Handbücher = 401 Chunks, Embedding
bge-m3, der **unveränderte** Retriever lief gegen beide Speicher).

Markierungen: **✔** gemessen · **⚠** bestätigter Vorbehalt · **offen** noch nicht geprüft · *hochgerechnet* = aus
Messwerten extrapoliert, nicht gemessen.

---

## 1. Entscheidung

**Der Suchspeicher wird SQLite 3.46.1 (FTS5) + numpy ≥ 2.0 im Chat-Container, statt OpenSearch 3.8.0 als eigener Dienst.**

| | heute | neu |
|---|---|---|
| Software | OpenSearch `opensearchproject/opensearch:3.8.0`, Client `opensearch-py ≥ 3.2` | SQLite **3.46.1** aus dem Python-Modul `sqlite3` des Images `python:3.12-slim` (Debian trixie; ✔ FTS5 und `fts5vocab` im Image und im gebauten `chat-system`-Image geprüft; lokal getestet mit 3.45.1) + `numpy ≥ 2.0,< 3` |
| Betrieb | eigener Container, eigene PVC, HTTP | eine Datei `search.db` neben `chat.db` auf der PVC des Chats |
| Mindestanforderung | 2 GB JVM-Heap + ~1 GB, Kernel-Einstellung auf dem Knoten | SQLite ≥ 3.35 mit FTS5 (genutzt: WAL, FTS5, `fts5vocab`, `WITHOUT ROWID`, `ON CONFLICT`), Block-Storage |

Bedingungen, die vor dem Bau bzw. vor dem Abschalten von OpenSearch erfüllt sein müssen, stehen in §8.

## 2. Ausgangslage: was OpenSearch im Betrieb verlangt

Nicht die Platte ist das Problem — der Chunk-Index dreier Handbücher ist 8 MB groß — sondern Speicher, Knoten-Einstellungen und ein zweiter zustandsbehafteter Dienst:

| Bedarf | Konkret (aus `opensearch-index/compose.yaml`, `DEPLOY.md`, Messung) |
|---|---|
| RAM | JVM-Heap 2 GB (1 GB reicht mit k-NN nicht) + ~1 GB Nebenspeicher. ✔ Container ≈ 3,3–3,4 GiB RSS für 8 MB Indexdaten; der Bedarf hängt nicht von der Datenmenge ab |
| Knoten | Kernel-Parameter `vm.max_map_count ≥ 262144`; ulimits `memlock unlimited`, `nofile 65536` (rootless podman kann memlock nicht setzen → `bootstrap.memory_lock=false`) |
| Image | ≈ 2 GB; muss über Artifactory-Mirror oder `docker save/load` auf den Server |
| Sicherheit | heute `DISABLE_SECURITY_PLUGIN=true` → HTTP ohne Auth, nur loopback. Produktiv: TLS-Zertifikate, Admin-Passwort, Nutzerkonfiguration des Security-Plugins |
| Deployment | eigener Container/StatefulSet, eigene PVC, Readiness-Wartezeit; Dateirechte des Datenverzeichnisses (UID 1000, SELinux) |
| Backup | Snapshot-Repository statt Dateikopie |
| Verbindungen | Chat und Indexer brauchen Endpunkt, ggf. Zertifikat und Zugangsdaten |
| Eigenheit | ⚠ nach erzwungenem Neuschreiben zählen gelöschte Fassungen in BM25 mit, bis ein Segment-Merge läuft (gemessen: `N` = 2 406 statt 401, max \|Δ Score\| 0,39) → `_forcemerge?only_expunge_deletes=true` nach Re-Index |
| Platte | ✔ 8 MB je 401 Chunks (13 MB mit gelöschten Fassungen); *hochgerechnet* ≈ 240 MB bei 100 Handbüchern |

**Stärken:** eigenständiger Dienst über das Netz erreichbar, ✔ ≈ 120–150 Suchen/s, mit 3 Knoten hochverfügbar, Analyse und BM25 eingebaut. Davon nutzt das System wenig: RRF, Graph, Guardrail und Prompt laufen bereits im eigenen Python-Code.

## 3. Kriterien

Prämisse: **weniger externe Abhängigkeiten, weniger Installationsaufwand, weniger Ressourcen gewinnt** — unter drei Nebenbedingungen:

1. **Qualität unverändert**: gleiche Treffer, gleiche Guardrail-Urteile, gleicher Kontext für das LLM (Abnahme §3.9 der Vorlage).
2. **Antwortzeit**: eine Suche im Millisekundenbereich; unter Last 1–2 s je Suche noch tragbar, weil je Antwort eine Suche auf 10–30 s LLM-Zeit kommt (Embedding allein ≈ 0,5 s).
3. **Datenmenge**: ≈ 600 Chunks heute (5 Handbücher), ≈ 5 000 bei 40, ≈ 12 000 bei 100 Handbüchern. Bei dieser Menge genügt exakte Vektorsuche; die **Textanalyse** entscheidet über die Qualität, nicht der Vektorindex.

## 4. Was der Speicher können muss — und was davon schwer ist

| Baustein | Wofür | Warum er zählt |
|---|---|---|
| **Vektorsuche mit Filter** (`doc_ids`) | kNN-Kanal, Trennung nach Handbuch/Gruppe | findet Passagen gleicher Bedeutung mit anderen Worten; der Filter muss *in* der Suche wirken |
| **BM25 mit deutscher Analyse** | BM25-Kanal | „Zertifikate“ muss „Zertifikat“ finden. **Größtes Risiko beim Wechsel** (unten) |
| **Exakter Abgleich auf Listen** (wörtlich / kleingeschrieben) | Identifier- und Label-Kanal | IDs wie `SOP-ZSD-06` und Namen dürfen nicht zerlegt werden; sie sind die „starke Evidenz“ des Guardrails |
| **Lesen per ID, mehrere Suchen je Frage** | Graph-Chunks, 4 Kanäle | hält die Latenz je Frage niedrig |
| **Atomares Schreiben mit Versionsprüfung** | Manifest | zwei Ingests desselben Handbuchs dürfen sich nicht überlagern; der Chat darf nie einen halben Stand sehen |
| **JSON-Blobs, Löschen je Handbuch** | Graph, Markdown, Sweep alter Runs | der Graph wird beim Chat-Start geladen |

Nicht nötig im Speicher: RRF, 1-Hop-Graph, Fakten, Entity-Cards, Prompt — das ist bereits Python.

**Der anspruchsvollste Baustein ist BM25**, aus drei Gründen:

1. **Die deutsche Analyse muss Token für Token stimmen.** OpenSearch zerlegt, entfernt Stoppwörter, normalisiert Umlaute und stemmt leicht; SQLite kann das nicht. Beispiel mit dem portierten Analyzer: `Zertifikate` und `Zertifikat` → `zertifikat`; `Störungen der Störung` → `storung storung`; `Dispatcher-Konfiguration` → `dispatch konfiguration`. Ohne diese Analyse findet die Frage „Störung“ keinen Chunk mit „Störungen“, der BM25-Kanal liefert weniger, und der Guardrail (Prüfung `bm25_returned`) urteilt anders. ✔ Der Python-Port liefert auf 910 Feldern / 41 986 Tokens 0 Abweichungen gegen OpenSearch `_analyze`.
2. **Die Rangfolge hängt an der Formel.** FTS5s eigenes `bm25()` rechnet die IDF anders (ohne `1+`) und normiert anders → ✔ Top-10-Überschneidung ≈ 0,9, Kontext für das LLM nur bei 4/10 Fragen gleich. Die Lucene-Formel in Python nachgerechnet → ✔ Scores identisch (Δ = 0), Kontext 7/10 gleich (der Rest sind Gleichstände, die OpenSearch gegen die eigene Indexgeschichte genauso anders auflöst: 6/10).
3. **Diese Nachrechnung skaliert in der Prototyp-Form nicht.** Python-Schleife über alle Kandidaten: ✔ 401 Chunks 9 ms; 4 010 Chunks 53 ms, 10 Threads p50 5,4 s; **12 030 Chunks 188 ms, 10 Threads p50 20 s**. ⚠ Vor dem Bau als Matrixprodukt über eine Termfrequenz-Matrix umsetzen (Standardtechnik, nicht gemessen) — oder FTS5 `bm25()` nehmen (✔ 12 030 Chunks: 56 ms / 0,3 s), dann entscheidet der Judge-Eval über die Qualität.

Die Vektorsuche ist dagegen der einfache Teil: ✔ exakte numpy-Suche und OpenSearch-HNSW liefern dieselben Top-20 in gleicher Reihenfolge; ✔ 2,1 ms bei 12 000, 9,5 ms bei 50 000 Vektoren. Ein Vektorindex (vec1, sqlite-vec, HNSW) bringt bei dieser Menge nichts (§6 der Vorlage, §7 Punkt 4).

## 5. Ergebnis der Tests

Unveränderter Retriever, 10 Fragen, OpenSearch gegen SQLite (Lucene-Formel):

| Prüfung | Ergebnis |
|---|---|
| Analyzer (Golden-Test) | ✔ 0 Abweichungen |
| kNN, Identifier, Label | ✔ gleiche Treffermengen |
| BM25-Scores | ✔ identisch (Index ohne gelöschte Fassungen) |
| Guardrail-Urteil | ✔ 10/10 gleich |
| fusionierte Top-10 | ✔ Überschneidung 0,97; Reihenfolge 7/10, Fakten 7/10, Entitäten 8/10, Kontext 7/10 |
| Gegenprobe OpenSearch gegen sich selbst (gleiche Daten, andere Schreibreihenfolge) | Reihenfolge 4/10, Fakten 7/10, Kontext 6/10 → die Abweichung zwischen den Speichern ist nicht größer als OpenSearchs eigene |
| LLM-Antwort auf die Beispielfrage | inhaltsgleich (gleicher Verantwortlicher, gleiches Zitat) |
| Antwort-Eval mit Judge, Lauf mit dem Eval-Set | **offen** (Bestätigung; entscheidend nur, falls FTS5 `bm25()` gewählt wird) |

Latenz und Ressourcen:

| | OpenSearch 3.8.0 | SQLite + numpy |
|---|---|---|
| kNN + BM25, eine Suche (401 Chunks) | ✔ 11–12 ms | ✔ 6–8 ms |
| 10 gleichzeitige Suchen, p50 (401 Chunks) | ✔ 50–70 ms | ⚠ 1,0–1,2 s (Lucene-Formel) · 0,4 s (FTS5 `bm25()`) |
| 10 gleichzeitige Suchen, p50 (12 030 Chunks) | nicht gemessen | ⚠ 20 s (Lucene-Formel, Schleife) · ✔ 0,3 s (FTS5 `bm25()`) · vektorisiert: nicht gebaut |
| Durchsatz Suchen/s | ✔ ≈ 120–150 | ⚠ ≈ 10–25 (GIL im Chat-Prozess) |
| Speicher | ✔ ≈ 3,4 GiB RSS, unabhängig von der Datenmenge | ✔ 5,8 MB Datei + 1,6 MiB Vektoren im Chat-Prozess; 49 MB Vektoren bei 12 000 Chunks |
| Ingest drei Handbücher | 5 Schritte (lease, bulk, refresh, verify, sweep) | ✔ eine Transaktion je Handbuch, 0,3–0,6 s; Indexer ≈ 70 MB RSS |
| Lesen während des Schreibens | ja, alte und neue Chunks kurz gemischt; BM25-Drift bis Merge | ✔ 10 Lese-Threads fehlerfrei während drei Neuschreibungen; neuer Stand nach Commit, Vektoren automatisch neu geladen |

## 6. Wie die SQLite-Variante läuft

Der Indexer liest weiterhin die dgs-Antwort (`response.json`) und baut daraus mit dem vorhandenen `build_batch` dieselben Datensätze wie heute — er sucht also **nicht in den JSON-Dateien**, sondern schreibt sie in Tabellen:

| Tabelle | Inhalt | Entspricht heute |
|---|---|---|
| `chunks` | `chunk_id`, `doc_id`, `run_id`, **`embedding` als float32-BLOB**, `source` = Datensatz als JSON | `bhb-chunks` (`_source`) |
| `fts_text`, `fts_body`, `fts_caption` (FTS5) | die Tokens des Python-Analyzers je Feld | der Lucene-Index hinter `multi_match` |
| `chunk_identifiers`, `chunk_labels` | ein Eintrag je Begriff und Chunk, indiziert | `term` auf `keyword`-Feldern |
| `documents` | `source`, `graph` (JSON), `markdown` | `bhb-documents` |
| `nodes`, `manifest`, `ingest_log`, `meta` | Knoten, letzter erfolgreicher Stand je Handbuch, Versuche, `data_version` | `bhb-nodes`, `bhb-manifest` |

- **Wo:** eine Datei `search.db` (WAL-Modus) auf der RWO-PVC des Chats, **Block-Storage** (ext4/xfs), kein NFS/SMB — das gilt heute schon für `chat.db`. Indexer als `kubectl exec` im Chat-Pod oder als Job mit Pod-Affinität auf denselben Knoten.
- **Im Speicher:** beim Start lädt der Chat den Graph und alle Vektoren als eine normierte numpy-Matrix (✔ 1,6 MiB bei 401 Chunks; 49 MB bei 12 000, 98 MB bei 24 000). Jede Frage prüft `data_version`; nach einem Ingest werden Graph und Matrix einmal neu geladen (✔ im Test ohne Fehler und ohne Latenzspitze). Pod-Limit von 1 Gi auf 2 Gi anheben und messen.
- **Neustart:** die Datei bleibt auf der PVC; der Chat lädt beim Start neu. Kein Backup nötig: ✔ Neuaufbau aus den aufbewahrten dgs-Ergebnissen (`runs/`, 2–3 MB je Handbuch) in Sekunden bis Minuten, ohne dgs und ohne LLM. `chat.db` und `runs/` werden gesichert (VolumeSnapshot).
- **Gleiches Verhalten:** ja, bis auf Gleichstände (§5). Der Retriever-Code bleibt unverändert; nur die Stellen, die die Datenbank berühren, bekommen ein zweites Backend hinter der Schnittstelle `SearchBackend`.
- **100–200 Handbücher** (≈ 12 000–24 000 Chunks): kNN unkritisch; Datei *hochgerechnet* ≈ 175–350 MB; BM25 nur mit vektorisierter Formel oder FTS5 `bm25()` (§4 Punkt 3).
- **Zusatzcode** (Prototyp, ohne Tests): Analyzer ≈ 190 Zeilen, Schema + Ingest + Kanäle + Shim ≈ 770 Zeilen, davon Lucene-BM25 ≈ 40 und Vektorsuche ≈ 40 Zeilen. Dieser Preis fällt bei OpenSearch nicht an.

## 7. Abwägung

**Für SQLite**

- kein zweiter Dienst: kein Image-Mirror, kein Heap, keine Kernel-Einstellung, kein TLS/Nutzer-Setup, keine Snapshot-Backups, keine Verbindungskonfiguration;
- ✔ Ressourcen: MB statt GiB; eine Suche schneller als mit OpenSearch;
- ✔ Ingest in einer Transaktion: kein halber Stand sichtbar, kein Lease/TTL, kein BM25-Drift durch gelöschte Fassungen;
- ✔ Qualität auf drei Handbüchern gleich bis auf Gleichstände;
- Filter nach Handbuch und Nutzergruppe wirken in allen Kanälen (`doc_ids`).

**Gegen SQLite**

- **genau eine Chat-Instanz**: keine Hochverfügbarkeit, kurzer Ausfall bei jedem Rollout und beim Übernehmen neuer Handbücher (Recreate);
- ⚠ Suche im Chat-Prozess: ≈ 10–25 Suchen/s statt ≈ 120–150/s; für ≤ 10 gleichzeitige Antworten mit 10–30 s LLM-Zeit unkritisch, für einen Suchdienst nicht;
- ⚠ BM25 muss vor dem Bau vektorisiert werden (oder FTS5 `bm25()` + Judge-Eval);
- Block-Storage Pflicht; der Indexer muss auf dem Knoten des Chats laufen (Rückfall: fertige Datei bauen und atomar tauschen, §3.10 der Vorlage);
- Daten nur über den Chat-Prozess bzw. die Datei erreichbar, nicht über das Netz;
- ≈ 1 000 Zeilen eigener Code, der Lucene-Verhalten nachbildet und gepflegt werden muss.

**Was die Nutzerzahl wirklich begrenzt** (Annahme der Vorlage: 1 Frage je 2 min, 20–40 s je Antwort):

| | 40 Handbücher / 10 Nutzer | 100 Handbücher / 40 Nutzer |
|---|---|---|
| gleichzeitige Antworten | ≈ 2–3 | ≈ 10, Spitzen höher (`max_concurrent_answers = 10`, die 11. bekommt „busy“) |
| LLM-Streams | 3–5 geplant | ≈ 10–15 → **eigentlicher Engpass: GPU-Kapazität bzw. Batching** |
| Suche (SQLite) | unkritisch | unkritisch mit vektorisiertem BM25 (eine Suche je Antwort) |
| Chat-Pod | ein Prozess; CPU-Limit ≥ 1 Kern, Speicher 2 Gi | gleich; mehr Prozesse = mehrere Replikas = externe Datenbanken (§8 der Vorlage) |

GPU-Referenz aus `technical_request.md` §3.1: `gemma4:26b`; 26–30B-Modell 4-bit ≈ 16–20 GB Gewichte + KV-Cache → eine GPU der 48-GB-Klasse für 3–5 parallele Streams bei ≥ 20–30 tok/s je Stream. Ob dieselbe GPU 10 parallele Streams trägt, ist eine Frage des LLM-Servers, nicht des Suchspeichers (**offen**, unabhängig von dieser Entscheidung). Für ein Pilotszenario mit 10 angemeldeten Nutzern reicht nach der Annahme oben ein Pod und eine GPU; 10 *gleichzeitig* antwortende Nutzer brauchen 10 LLM-Streams.

**Wann OpenSearch (oder PostgreSQL) die bessere Wahl wäre:**

- Hochverfügbarkeit oder mehrere Chat-Replikas werden gefordert (dann OpenSearch mit 3 Knoten oder PostgreSQL + pgvector; Chat-Historie wechselt per Umgebungsvariable nach PostgreSQL);
- andere Systeme — etwa weitere Agenten — sollen den Index **über das Netz** lesen; mit SQLite geht das nur über eine schreibgeschützte Kopie der Datei oder eine kleine API vor dem Chat;
- die Suche wird ein eigener Dienst mit > 25 Suchen/s;
- die Plattform bietet nur NFS-Storage oder erlaubt den Indexer nicht auf dem Chat-Knoten (Rückfall Dateitausch prüfen);
- die Plattform betreibt OpenSearch/PostgreSQL ohnehin für uns (Option D der Vorlage).

Ein späterer Wechsel bleibt möglich: die `runs/` bleiben erhalten, das OpenSearch-Backend bleibt im Code, `SearchBackend` nimmt auch ein pgvector-Backend auf.

## 8. Bedingungen und offene Punkte

Vor dem Bau:

1. ⚠ **BM25 vektorisieren** (Termfrequenz-Matrix, Matrixprodukt) — oder bewusst FTS5 `bm25()` wählen und den Judge-Eval zur Pflicht machen.
2. **StorageClass** der Ziel-Plattform prüfen: Block-Storage, RWO, kein NFS.
3. **HA-Anforderung** klären; bei „ja“ nicht A (ein Pod) bauen, sondern C oder D der Vorlage.

Vor dem Abschalten von OpenSearch (Abnahme §3.9 der Vorlage):

4. Kanal-Vergleich mit dem Eval-Set `test-quality/2026-09-09_v2/test-questions.yaml` (**offen**, bisher 10 abgeleitete Fragen).
5. Antwort-Eval mit Judge ohne Rückschritt (**offen**).
6. Ein Lesesnapshot je Frage im Chat (§3.6 der Vorlage; im Prototyp-Shim noch Autocommit, **offen**, geringe Auswirkung).

## 9. Referenztabelle aller Optionen

| | **OpenSearch 3.8.0** (heute) | **PostgreSQL + pgvector** | **zvec 0.7.0** | **SQLite 3.46.1 (FTS5) + numpy** |
|---|---|---|---|---|
| Betriebsform | Server, eigener Container | Server, eigener Container | Bibliothek im Prozess, Verzeichnis | Bibliothek im Prozess, eine Datei |
| Externe Dienste zusätzlich | 1 | 1 (kann Chat-Historie mit übernehmen) | 0 | 0 |
| Ressourcen | ✔ ≈ 3,4 GiB RSS | nicht gemessen | ✔ 8,3 MB auf Platte | ✔ 5,8 MB + 1,6 MiB RAM |
| Vektorsuche | HNSW, approximativ | HNSW/IVFFlat/exakt | ✔ FLAT identisch | ✔ exakt, identisch mit HNSW |
| Deutsche Analyse | eingebaut | eingebaut (`german`, Snowball) | Snowball ohne Stoppwörter/Normalisierung → ⚠ Python-Analyzer trotzdem nötig | ⚠ nicht eingebaut → Python-Analyzer (✔ 0 Abweichungen) |
| BM25 wie OpenSearch | Referenz | nicht gemessen | ⚠ eigene Formel; mit unseren Tokens Top-10 1,0 | ✔ Lucene-Formel nachgerechnet: identisch; FTS5 `bm25()`: ≈ 0,9 |
| Exakte Listen (IDs, Labels) | `keyword` + Normalizer | Arrays + GIN | ⚠ kein Filter auf Listenfelder gefunden → eigene Strukturen | ✔ Hilfstabellen, gleiche Treffer |
| Lock / Versionsprüfung | `seq_no`/`primary_term` | Transaktionen | keine | ✔ `BEGIN IMMEDIATE`, ein Schreiber |
| Lesen während Ingest | ja, gemischt; ⚠ BM25-Drift | nach Commit | nicht dokumentiert | ✔ nach Commit, fehlerfrei getestet |
| 1 Suche kNN+BM25 | ✔ 11–12 ms | – | – | ✔ 6–8 ms |
| 10 gleichzeitige Suchen | ✔ 50–70 ms | – | – | ⚠ 0,4–1,2 s (401 Chunks); 12 000 Chunks nur vektorisiert oder mit FTS5 `bm25()` (0,3 s) |
| HA / mehrere Replikas | ja (3 Knoten) | ja | nein | nein |
| Zugriff anderer Systeme | über das Netz | über das Netz | Datei/Verzeichnis | Datei |
| Zusatzcode | keiner | neues Backend | Analyzer + eigene Strukturen + Lock | ✔ ≈ 190 + ≈ 770 Zeilen |
| Qualität gleich? | Referenz | wahrscheinlich, **nicht gemessen** | nur mit Zusatzcode | ✔ Guardrail 10/10, Top-10 0,97, Rest Gleichstände |
| Urteil | behalten, falls HA/Netzzugriff gefordert | Weg bei HA ohne OpenSearch (§8 der Vorlage) | ohne Zusatzcode kein Ersatz, mit Zusatzcode kein Vorteil | **gewählt** für eine Instanz |

Nur-Vektor-Erweiterungen (SQLite **vec1** des SQLite-Projekts, 0.7, „Testing is insufficient“; **sqlite-vec** auf PyPI) lösen nur den einfachen Teil: ohne Modell suchen sie ebenfalls exakt und liefern damit dieselben Treffer wie numpy, der ANN-Modus braucht Training und Neuaufbau je Ingest, vec1 muss zudem kompiliert und als Erweiterung ausgeliefert werden. Nicht nötig (nicht gemessen).

## Quellen

- [`SUCHSPEICHER-VERGLEICH.md`](SUCHSPEICHER-VERGLEICH.md): §1 Anforderungen, §2 Vergleich, §3 Bauvorlage und Abnahme (§3.9), §4 Parallelität, §5 Kubernetes, §6 Skalierung, §7 Empfehlung, §8 Ausbau mit Replikas
- `database_comparison/vergleich.ipynb` (ausgeführt 2026-10-06), `database_comparison/README.md`; Skripte `concurrent_write_test.py`, `scale_test.py`, `bm25_variants_e2e.py`
- `opensearch-index/compose.yaml`, `opensearch-index/DEPLOY.md` (Installationsbedarf OpenSearch); `technical_request.md` §3.1 (LLM/GPU)
