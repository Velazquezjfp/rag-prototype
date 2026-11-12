# opensearch-index

Gemeinsame Bibliothek von Chat und Ingest und der Befehl `osi`. Sie legt die Indizes an und schreibt das Ergebnis
des docling-graph-service (Markdown, Chunks mit Vektoren, Graph) nach OpenSearch. Kein eigener Dienst.

Dasselbe Ergebnis noch einmal zu indexieren ändert nichts. Ein neues Ergebnis ersetzt genau die Daten dieses
Dokuments; es entstehen keine Duplikate.

## Indizes

Vier Indizes für alle Handbücher zusammen. Standard-Präfix `bhb`; die Namen sind Aliase auf `<präfix>-<name>-v1`.

| Index | Inhalt |
|---|---|
| `bhb-chunks` | Textstellen: Text, Seiten, Vektor, Kennungen (Tickets, SOPs, Hosts …), Verweise auf Knoten |
| `bhb-nodes` | ein Eintrag je Knoten und Dokument: Typ, Name, Aliase, Attribute |
| `bhb-documents` | das Handbuch: Titel, Version, Markdown und der ganze Graph als JSON |
| `bhb-manifest` | Stand und Sperre je Dokument: `indexing`, `active` oder `failed` |

Dazu die Such-Pipeline `bhb-rrf`. Embedding-Modell und Vektorgröße stehen im Index `bhb-chunks` (`_meta`).

## Befehle

| Befehl | Zweck |
|---|---|
| `osi verify` | Cluster erreichbar, Version, k-NN-Plugin vorhanden, Probe mit einem Vektor |
| `osi bootstrap [--dry-run]` | fehlende Indizes, Aliase und die Such-Pipeline anlegen; vorhandene prüfen |
| `osi ingest <pfad>… [--doc-id X] [--force] [--replace] [--dry-run]` | ein Ergebnis von dgs indexieren |
| `osi status` | Stand je Dokument, Zählungen, was Aufmerksamkeit braucht |
| `osi search --text T` · `--identifier X` · `--node-id N` · `--knn-from-chunk ID` | Probe-Suchen, ohne Embedding-Endpunkt |
| `osi delete --doc-id X [--yes]` | alle Daten eines Dokuments löschen |

Für alle Befehle: `--url`, `--prefix`, `--ontology`, `--log-level`. `osi ingest` nimmt eine `response.json`, einen
Ordner damit oder einen Ordner von `dgs process`.

## Regeln

- **Dokument-ID** wird nie geraten. Reihenfolge: `--doc-id`, dann der Dateiname in der Ontologie
  (`meta.documents[].file`), dann genau eine Dokument-ID auf Seite 1, dann der Knoten der einzigen
  `DOCUMENTS`-Kante. Findet sich keine: Fehler mit Hinweis auf `--doc-id`.
- **Derselbe Lauf noch einmal:** `noop`. Die Lauf-ID (`run_id`) ist ein Hash über alles, was in die Indizes kommt.
- **Neuer Lauf desselben Dokuments:** erst schreiben, dann Zählungen prüfen, dann die alten Einträge löschen.
  Ein anderer Dateiname unter derselben Dokument-ID braucht `--replace`.
- **Fehler:** das Manifest steht auf `failed`, nichts wird gelöscht. Der nächste Lauf repariert.
- **Zwei Läufe gleichzeitig:** der zweite bekommt einen Fehler. Die Sperre im Manifest läuft nach
  `ingest.lock_ttl_s` (3600 s) ab.
- **Ein Embedding-Modell je Index:** `osi` schreibt nicht in Indizes mit anderer Vektorgröße oder
  Mapping-Version. Ein Vektor mit falscher Länge bricht den ganzen Lauf ab.
- **Neuer Präfix:** `osi --prefix <präfix> bootstrap`. In einem gesicherten Cluster braucht die Schreibrolle
  Rechte auf `<präfix>-*`.

## Einstellungen

Standardwerte in `config.yaml`, überschreibbar mit `OSI__<BEREICH>__<SCHLÜSSEL>` (Umgebung oder `.env`).
`OSI_CONFIG=<datei>` wählt eine andere YAML-Datei. Vorlage: `.env.example`.

| Variable | Standard | Bedeutung |
|---|---|---|
| `OSI__OPENSEARCH__URL` | `http://localhost:9200` | `https://` schaltet TLS ein |
| `OSI__OPENSEARCH__USERNAME`, `__PASSWORD` | – | Anmeldung (`bhb_writer`) |
| `OSI__OPENSEARCH__VERIFY_CERTS`, `__CA_CERTS` | `true`, – | Zertifikatsprüfung, eigene CA-Datei |
| `OSI__INDEX__PREFIX` | `bhb` | Index-Präfix |
| `OSI__INDEX__SHARDS`, `__REPLICAS` | 1, 0 | bei mehreren Knoten: 1 Replikat |
| `OSI__EMBEDDING__MODEL`, `__DIM`, `__TEXT_PREFIX` | `bge-m3`, 1024, leer | müssen zu dgs passen (`DGS__EMBEDDING__*`). Der Ingest-Dienst setzt sie selbst aus dem, was dgs meldet |
| `OSI__ONTOLOGY__PATH` | `../user-manual-books/handbuch_daten/Ontologie/ontology.yaml` | Muster für Kennungen, Regeln für IDs, Liste der Dokumente |

## Lokal

```bash
cp .env.example .env
make up                 # lokaler OpenSearch-Knoten (Docker oder Podman): http://127.0.0.1:9200
make dev                # .venv mit dem Befehl osi
make verify && make bootstrap
.venv/bin/osi ingest <ordner mit response.json>
.venv/bin/osi status
make test               # 66 Tests, ohne Cluster
make test-integration   # 12 Tests gegen den lokalen Knoten (Präfix bhbtest, räumt danach auf)
```

## Image

`Dockerfile` und `compose.yaml` sind für lokale Tests und für einen Server ohne Python: der OpenSearch-Knoten
und ein kleines Image nur mit `osi`. Für Kubernetes wird beides nicht gebaut. Die Bibliothek und der Befehl `osi`
stecken im Chat-Image und im Ingest-Image; dort braucht `osi` die Variable `OSI__ONTOLOGY__PATH`.

Mehr: [`REFERENCE.md`](REFERENCE.md) (ausführlich, Englisch), [`DEPLOY.md`](DEPLOY.md) (Knoten auf einem Server).
