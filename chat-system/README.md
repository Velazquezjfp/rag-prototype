# chat-system

Der Chat über die indexierten Betriebshandbücher: Streamlit-Oberfläche, Gespräche in SQLite, Suche in OpenSearch,
Antworten vom Sprachmodell mit Quellenangaben. Der Chat liest nur; neue Bücher kommen über den
[`ingest-service`](../ingest).

```
Browser ──▶ chat-system ──▶ Embedding-Endpunkt   (Frage → Vektor)
                 │────────▶ OpenSearch           (vier Suchkanäle + Graph, nur lesen)
                 │────────▶ Sprachmodell         (Antwort, gestreamt)
                 └────────▶ SQLite               (Gespräche pro Benutzer)
```

Bausteine im Image: `chat-system` (dieser Ordner), `retrieval` (Suche und Prompt), `users` (Benutzer),
`opensearch-index` (gemeinsame Bibliothek: Verbindung, Indexnamen, IDs).

## Lokal starten

```bash
cp .env.example .env        # Endpunkte und Schlüssel eintragen
make dev                    # venv mit allen Bausteinen
make doctor                 # prüft Datenbank, OpenSearch, Sprachmodell, Benutzer
make run                    # http://127.0.0.1:8501
make ask Q="Was passiert, wenn Vault versiegelt ist?"      # ohne Oberfläche
make test test-ui           # 79 Tests
```

Als Container: `make up` (Build-Kontext ist die Wurzel des Repos).

## Benutzer

| Profil | Einstellung | Verhalten |
|---|---|---|
| lokal | `USERS__ADAPTER=env` | ein fester Test-Benutzer (`USERS__DEV_USER`, Standard `dev`) |
| remote | `USERS__ADAPTER=header` | Benutzer aus den Headern des Anmelde-Proxys; ohne Header kein Zugang |

Es gibt keine Benutzerauswahl und kein Tageslimit. Jeder Benutzer sieht alle Handbücher, kann sie filtern und
zwischen schnellem Modus und Graph-Modus wählen. Gespräche gehören dem Benutzer, der sie begonnen hat.
Details: [`../users`](../users).

## Grenzen eines Gesprächs

- **Rundenlimit:** nach `USERS__MAX_TURNS` Runden (Standard 10) ist das Gespräch beendet; ein neues beginnen.
- **Kontextlimit:** passt der Text nicht in das Sprachmodell, stürzt nichts ab. Der Chat zeigt
  „Kontextlimit erreicht …“, zählt die Nachricht nicht und beendet das Gespräch.
- Das Modell bekommt nur die letzten Runden (`RAG__RETRIEVAL__HISTORY_TURNS`) und ein begrenztes Token-Budget.

## Einstellungen

Eine `.env`, drei Gruppen. Vorlage: `.env.example`.

| Gruppe | Wichtigste Variablen |
|---|---|
| `CHAT__*` | `CHAT__DB__URL` (Standard `sqlite:///./data/chat.db`), `CHAT__RETRIEVAL__K`, `CHAT__RETRIEVAL__K_GRAPH` |
| `RAG__*` | `RAG__OPENSEARCH__URL`, `__USERNAME`, `__PASSWORD`, `__VERIFY_CERTS`, `__CA_CERTS`; `RAG__INDEX__PREFIX`; `RAG__EMBEDDING__BASE_URL`, `__API_KEY`, `__MODEL`, `__DIM`, `__QUERY_PREFIX`; `RAG__LLM__BASE_URL`, `__API_KEY`, `__MODEL`; `RAG__ONTOLOGY__PATH` |
| `USERS__*` | `USERS__ADAPTER`, `USERS__DEV_USER`, `USERS__HEADER_USER`, `USERS__MAX_TURNS` |

Das Embedding-Modell muss dasselbe sein wie im Index (Modell, Vektorgröße, Präfix). Der Chat warnt, wenn der
Name abweicht. Die alte Variable `CHAT__UI__ALLOW_USER_SWITCH` gibt es nicht mehr; sie wird ignoriert.

## Datenbank

SQLite in `./data` (im Container `/app/chat-system/data`). Das Schema entsteht beim ersten Start (Alembic).
Postgres: `CHAT__DB__URL=postgresql+psycopg://…`. Mit SQLite nur ein Replikat betreiben.

## Image

`chat-system/Dockerfile`: `python:3.12-slim` und Python-Pakete, kein apt-Schritt. Läuft unter beliebiger
Benutzer-ID (Gruppe 0) mit schreibgeschütztem Dateisystem. Schreibbar sein müssen nur `/tmp` und
`/app/chat-system/data`. Port 8501, Prüfadresse `/_stcore/health`. Manifest: [`../deploy/k8s`](../deploy/k8s).

Mehr Hintergrund (Ablauf einer Frage, Befehle, Fehlersuche): [`REFERENCE.md`](REFERENCE.md) (älter, Englisch),
[`DEPLOY.md`](DEPLOY.md).
