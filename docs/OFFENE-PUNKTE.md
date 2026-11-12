# Offene Punkte vor dem Deployment

Stand: 2026-11-12. Jeder Punkt braucht eine Antwort von außen (Plattform, Security, Team). Die Manifeste
markieren dieselben Stellen mit `PRÜFEN`.

## Kritisch (blockiert oder ändert das Deployment)

| # | Punkt | Frage | Wer |
|---|---|---|---|
| 1 | **Ingest-API ohne Anmelde-Proxy** | Die API soll von außen über das Gateway erreichbar sein, nur mit `X-API-Key`. Ist eine Route ohne PAG erlaubt? Alternative: Anmeldung per CLI, danach Aufruf über die Domain. | Security, Plattform |
| 2 | **Quellen für den Image-Build** | Der Build lädt aus dem Internet (Liste unten). Was davon gibt es in Artifactory? Sonst: Images außerhalb bauen und in die Registry schieben. | Plattform |
| 3 | **Registry für Images** | `helm-dev` ist für Helm-Charts, die beiden `.git`-Einträge sind Git-Repos. In welches Repository kommen Container-Images? | Plattform |
| 4 | **Externe Dienste über `http`** | LLM und Embeddings laufen als `http://<dienst>:<port>` mit API-Key. API-Key und Handbuchtext gehen unverschlüsselt. Erlaubt im Firmennetz? | Security, Team |
| 5 | **Service Mesh, ausgehend** | Darf ein Pod externe Adressen (LLM, Embeddings, OpenSearch) erreichen, oder braucht jede einen Eintrag (ServiceEntry)? | Plattform |
| 16 | **Pipeline** | Wer baut die Images, und mit welcher Definition? In beiden Repos gibt es noch keine Pipeline-Datei. Was erwartet der Eintrag `pipelines`? | Plattform |

## Zu bestätigen (Platzhalter in den Manifesten)

| # | Punkt | Frage | Wer |
|---|---|---|---|
| 6 | Benutzer-Header | Welcher Header trägt die Benutzerkennung (`X-Forwarded-User` = `sub`, E-Mail oder Login)? Einstellbar über `USERS__HEADER_USER`. | Test mit PAG |
| 7 | Gateway | Name und Namespace des Gateways, Hostnamen, VirtualService oder Route? Zeitgrenze für lange Aufrufe: Ingest braucht bis 3600 s. | Plattform |
| 8 | Sidecar | Reicht die Annotation `sidecar.istio.io/inject: "true"` am Pod? | Plattform |
| 9 | NetworkPolicy | Labels des Auth-Proxy-Pods und Namespace des Gateways. Bis dahin ist `networkpolicy.yaml` nicht aktiv. | Plattform |
| 10 | Helm oder Manifeste | Die Manifeste sind einfaches YAML mit Kustomize. Verlangt die Pipeline (ArgoCD) Helm-Charts? | Plattform |
| 11 | Secrets | Kommen Passwörter und API-Keys aus Vault? Heute: normale Secrets, von Hand angelegt. | Plattform |
| 12 | Quota | `request_cpu: 2000m`. Bedarf: dgs 1000m + Chat 250m + Ingest 100m + Sidecars. Gibt es eine LimitRange mit eigenen Vorgaben? | `oc describe limitrange` |
| 13 | OpenSearch-Zertifikat | Die CA fehlt noch; im Test lief es mit `VERIFY_CERTS=false`. Für den Betrieb: CA als ConfigMap `opensearch-ca`. | OpenSearch-Team |
| 14 | OCR-Modelle | Drei `.pth`-Dateien von GitHub (EasyOCR). Dieses Format kann Code enthalten: vor der Freigabe scannen. Ohne Freigabe: Image mit `WITH_OCR=0` bauen. | Security |
| 15 | Speicher für dgs | Limit 6Gi. Gemessen mit 29 Seiten und 2 CPU: ohne OCR höchstens 3,2 GiB (114 s), mit OCR 5,8 GiB (226 s). Für OCR oder große Bücher das Limit erhöhen (8–10Gi). | Test im Cluster |
| 17 | Ingest mit Graph | Die Ingest-API ist lokal nur ohne den Graph-Schritt getestet (er braucht das Sprachmodell). Der erste Lauf mit Graph kommt auf dem Server. | Test im Cluster |
| 18 | Graph im Chat | Der Chat lädt den Graphen einmal beim Start. Nach einem neuen Buch muss der Chat neu starten; in der Testphase sind dann die Gespräche weg. Reicht das, oder soll der Chat den Graphen selbst neu laden? | Team |

## Bewusst so entschieden (Testphase)

- **Nichts wird gespeichert.** Gespräche liegen in SQLite im Pod und sind nach jedem Neustart weg. Später Postgres.
- **Ein Replikat je Dienst.** Der Chat wegen SQLite, Ingest und dgs verarbeiten ein Dokument zur Zeit.
- **Kein Tageslimit, keine Benutzerauswahl.** Jeder angemeldete Benutzer sieht alle Handbücher; ein Gespräch endet nach 10 Runden.
- **Neuer Index-Präfix nur von Hand.** Der Ingest-Dienst legt keine Indizes an (`osi bootstrap`, Rechte in OpenSearch).
- **dgs-Parameter pro Aufruf** (Embedding-Modell, Sprachmodell) kommen nach dem ersten Deployment.

## Was der Build aus dem Internet lädt

| Quelle | Inhalt | Image |
|---|---|---|
| Docker Hub | Basis-Image `python:3.12` (dgs) und `python:3.12-slim` (Chat, Ingest) | alle |
| PyPI | Python-Pakete (`pyproject.toml` je Dienst; dgs zusätzlich `requirements.txt`) | alle |
| `download.pytorch.org/whl/cpu` | torch (CPU) | dgs |
| `deb.debian.org` | `libgl1`, `libglib2.0-0` – das aktuelle `python:3.12` bringt libGL nicht mehr mit | dgs |
| `huggingface.co` | `docling-project/docling-layout-heron` (+ `-onnx`), `docling-project/docling-models` (Layout, Tabellen; safetensors) | dgs |
| `huggingface.co` | Tokenizer-Dateien von `intfloat/multilingual-e5-large` und `sentence-transformers/all-MiniLM-L6-v2` | dgs |
| `github.com/JaidedAI/EasyOCR` (Releases) | `craft_mlt_25k`, `latin_g2`, `english_g2` (`.pth`) – nur mit `WITH_OCR=1` | dgs |
| `openaipublic.blob.core.windows.net` | tiktoken-Vokabular `cl100k_base` | dgs |

Zur Laufzeit lädt kein Image etwas nach.

## Noch von Hand zu tun (Git)

- **App-Repo:** `chat-system`, `retrieval`, `users`, `ingest`, `opensearch-index`, `deploy`, `docs`, `README.md`,
  `.gitignore`, `.dockerignore` und die Ontologie `user-manual-books/handbuch_daten/Ontologie/ontology.yaml`.
- `opensearch-index`: der eigene Ordner `.git` ist entfernt. Es fehlt noch `git add opensearch-index`.
- **Zweites Repo:** `docling-graph` allein (mit eigenem Manifest unter `deploy/k8s` und eigener Kopie der Ontologie).
- Beide Images des App-Repos werden aus der Wurzel gebaut: `docker build -f chat-system/Dockerfile .`
