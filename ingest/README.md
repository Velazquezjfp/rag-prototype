# ingest-service

Nimmt ein PDF und eine Ontologie an, lässt den docling-graph-service (dgs) das Dokument verarbeiten und schreibt
das Ergebnis in OpenSearch. Der Indexer (`opensearch-index`) ist als Bibliothek eingebaut. Der Dienst speichert
keine Dateien.

```
PDF + Ontologie ──▶ ingest-service ──▶ dgs  POST /v1/process   (Markdown, Chunks mit Vektoren, Graph)
   (X-API-Key)            │
                          └──────────▶ OpenSearch  <präfix>-chunks / -nodes / -documents / -manifest
```

## API

Swagger: `/docs`, Definition: `/openapi.json`. Alle Aufrufe außer `/healthz` brauchen den Header `X-API-Key`
(oder `Authorization: Bearer <key>`).

| Aufruf | Zweck |
|---|---|
| `GET /healthz` | Lebenszeichen, ohne Schlüssel |
| `GET /v1/info` | Standardwerte, Zielindex (Embedding-Modell, Vektorgröße), was dgs gerade liefert |
| `POST /v1/ingest` | ein Dokument verarbeiten und indexieren |
| `GET /v1/jobs`, `GET /v1/jobs/{id}` | die letzten Aufträge mit Ergebnis (nur im Speicher) |

### `POST /v1/ingest` (multipart/form-data)

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `pdf` | ja | das Dokument, höchstens 50 MB |
| `ontology` | eins von beiden | Name einer eingebauten Ontologie, z. B. `bhb` |
| `ontology_file` | eins von beiden | eigene Ontologie als YAML-Datei |
| `prefix` | nein | Index-Präfix, Standard `bhb` |
| `doc_id` | nein | Dokument-ID, wenn Ontologie und Seite 1 keine liefern |
| `ocr`, `vlm` | nein | OCR bzw. Bildbeschreibungen für dieses Dokument an/aus; Standard: Einstellung von dgs |
| `force` | nein | neu indexieren, obwohl dieses Ergebnis schon aktiv ist |
| `replace` | nein | anderer Dateiname unter derselben Dokument-ID erlaubt |
| `dry_run` | nein | verarbeiten und planen, nichts in OpenSearch schreiben |

```bash
curl -H "X-API-Key: $KEY" -F pdf=@Handbuch.pdf -F ontology=bhb            http://localhost:8090/v1/ingest
curl -H "X-API-Key: $KEY" -F pdf=@Handbuch.pdf -F ontology_file=@mein.yaml -F prefix=bhb -F ocr=true \
     http://localhost:8090/v1/ingest
```

### Regeln

- **Ontologie:** genau eine Angabe. Ohne `ontology` und ohne `ontology_file` wird der Aufruf abgelehnt (400).
- **Index-Präfix:** die Indizes `<präfix>-*` müssen in OpenSearch schon existieren. Der Dienst legt keine an
  (`osi bootstrap` ist ein eigener Schritt, dazu Rechte für die Schreibrolle). Unbekannter Präfix: 404.
- **Embedding-Modell:** ein Index enthält Vektoren von genau einem Modell. Der Dienst liest Modell und Vektorgröße
  aus `<präfix>-chunks` und vergleicht sie mit dem, was dgs liefert (`/v1/capabilities`). Bei Abweichung: 409,
  es wird nichts verarbeitet.
- **Ein Dokument zur Zeit.** Ein zweiter Aufruf bekommt 503 mit `Retry-After`.
- **Ein Aufruf läuft, bis das Buch indexiert ist** (Minuten). Bricht die Verbindung ab, läuft der Auftrag zu Ende;
  das Ergebnis steht in `GET /v1/jobs`. Dasselbe Buch noch einmal senden ist unschädlich (`noop`).

### Antwort

Der Auftrag als JSON; dieselbe Zeile steht im Log, sobald der Auftrag angenommen ist.

| Feld | Inhalt |
|---|---|
| `job_id`, `state` | `running`, `done` oder `failed` |
| `status` | `active` (indexiert), `noop` (unverändert), `dry-run` |
| `doc_id` | die Dokument-ID im Index |
| `parameters` | wirksame Werte: Präfix, Index, Embedding-Modell und Vektorgröße, Ontologie, Optionen |
| `dgs` | Seiten, Chunks, Knoten, Kanten, Dauer, `degraded`, Fehler von dgs |
| `index` | Bericht des Indexers: Plan, Zählungen, Warnungen |
| `error` | Fehlertext, sonst `null` |

| Status | Bedeutung |
|---|---|
| 200 | verarbeitet (`active`, `noop`, `dry-run`) |
| 400 | Ontologie fehlt oder ist unbrauchbar, Präfix ungültig, Dokument leer |
| 401 | Schlüssel fehlt oder ist falsch |
| 404 | Index-Präfix existiert nicht |
| 409 | Embedding-Modell passt nicht zum Index; Dokument-ID schon anders belegt |
| 413 | Dokument zu groß |
| 422 | dgs lehnt Dokument oder Ontologie ab; keine Dokument-ID gefunden (`doc_id` mitgeben) |
| 502 | dgs oder OpenSearch nicht erreichbar oder fehlgeschlagen |
| 503 | ein anderes Dokument läuft gerade |

## Einstellungen

Eigene Variablen `INGEST__*`; die Verbindung zu OpenSearch nutzt die Variablen des Indexers `OSI__*`.

| Variable | Standard | Bedeutung |
|---|---|---|
| `INGEST__API_KEY` | – | Pflicht. Ohne Schlüssel startet der Dienst nicht. |
| `INGEST__DGS__URL` | `http://localhost:8080` | Adresse von dgs |
| `INGEST__DGS__TIMEOUT_S` | `3600` | Wartezeit je Dokument; größer als die Zeitgrenze von dgs |
| `INGEST__ONTOLOGIES` | `{"bhb": "<pfad>/ontology.yaml"}` | eingebaute Ontologien als JSON: Name → Datei |
| `INGEST__DEFAULT_PREFIX` | `bhb` | Präfix, wenn der Aufruf keinen nennt |
| `INGEST__MAX_UPLOAD_MB` | `50` | größtes Dokument |
| `OSI__OPENSEARCH__URL` | `http://localhost:9200` | OpenSearch |
| `OSI__OPENSEARCH__USERNAME` / `__PASSWORD` | – | Benutzer mit Schreibrecht (`bhb_writer`) |
| `OSI__OPENSEARCH__VERIFY_CERTS` / `__CA_CERTS` | `true` / – | Zertifikatsprüfung, eigene CA-Datei |
| `OSI__ONTOLOGY__PATH` | im Container `/ontology/ontology.yaml` | nur für den Befehl `osi` (siehe Hinweise) |

Vorlage mit allen Variablen: [`.env.example`](.env.example).

## Lokal starten

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                             # INGEST__API_KEY eintragen
.venv/bin/uvicorn --factory ingest_service.api:create_app --port 8090
.venv/bin/pytest -q                              # 17 Tests mit Attrappen
INGEST_INTEGRATION=1 .venv/bin/pytest -q         # dazu 4 Tests gegen OpenSearch auf localhost:9200
```

Als Container (Build-Kontext ist die Wurzel des Repos): `docker compose up -d --build` in diesem Ordner.
Auch dafür muss `.env` existieren.

## Hinweise

- **Prüfung des Embedding-Modells.** Steht im Index kein Modellname (der Index wurde nicht mit `osi bootstrap`
  angelegt), vergleicht der Dienst nur die Vektorgröße. Ein anderes Modell mit gleicher Größe fällt dann nicht
  auf. Kontrolle: in `GET /v1/info` darf `opensearch.index.embedding_model` nicht leer sein.
- **Nach einem neuen Buch den Chat neu starten.** Der Chat lädt den Graphen einmal beim Start. Namen und Fakten
  aus dem Graphen eines neuen Buchs kennt er erst nach einem Neustart (`oc rollout restart deployment/chat`).
  In der Testphase sind danach die Gespräche weg.
- **`osi` im Container.** Der Befehl des Indexers ist im Image: `oc exec deploy/ingest -c ingest -- osi status`.
  Indizes für einen neuen Präfix: `osi --prefix <präfix> bootstrap`. Dafür braucht der Benutzer in OpenSearch
  das Recht, Indizes anzulegen; `bhb_writer` hat es nicht unbedingt.

## Image

`ingest/Dockerfile`: `python:3.12-slim`, Python-Pakete, `opensearch-index` und dieser Dienst. Kein apt-Schritt.
Läuft unter beliebiger Benutzer-ID (Gruppe 0) mit schreibgeschütztem Dateisystem. Port 8090.
Schreibbar sein muss nur `/tmp`: ein Upload über 1 MB liegt während des Aufrufs dort als Datei ohne Namen. Sie
verschwindet, wenn der Aufruf endet oder der Prozess stirbt. Es bleibt nichts liegen, es gibt nichts aufzuräumen.
Manifest: [`../deploy/k8s`](../deploy/k8s).
