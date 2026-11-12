# RAG über Betriebshandbücher

Fragen an IT-Betriebshandbücher stellen und Antworten mit Quellenangabe bekommen. Ein Handbuch (PDF) wird einmal
verarbeitet: Text, Chunks mit Vektoren und ein Wissensgraph nach einer Ontologie. Die Suche verbindet Vektorsuche,
Stichwortsuche und den Graphen.

## Drei Dienste

| Dienst | Aufgabe | Spricht mit | Port |
|---|---|---|---|
| **chat** | Oberfläche, Gespräche (SQLite), Suche, Antwort | Sprachmodell, Embeddings, OpenSearch (lesen) | 8501 |
| **ingest** | API für neue Bücher: PDF + Ontologie → verarbeiten → indexieren | dgs, OpenSearch (schreiben) | 8090 |
| **dgs** | docling-graph-service: PDF → Markdown, Chunks, Vektoren, Graph | Sprachmodell, Bildmodell, Embeddings | 8080 |

```
Benutzer ─▶ Anmelde-Proxy ─▶ chat ───────────────▶ OpenSearch ◀──────┐
                                 └─▶ Sprachmodell, Embeddings        │ schreiben
Betreiber ─▶ Gateway (API-Key) ─▶ ingest ─▶ dgs ─▶ Sprachmodell, Embeddings
                                     └───────────────────────────────┘
```

Der Chat liest nur. Der Chat ruft weder ingest noch dgs auf.

## Zwei Repos, drei Images

| Repo | Ordner | Image | Manifest |
|---|---|---|---|
| App-Repo (dieses) | `chat-system/` + `retrieval/` + `users/` + `opensearch-index/` | `chat-system` | `deploy/k8s` |
| App-Repo (dieses) | `ingest/` + `opensearch-index/` | `ingest-service` | `deploy/k8s` |
| `docling-graph` (eigenes Repo) | `docling-graph/` | `docling-graph-service` | `docling-graph/deploy/k8s` |

`opensearch-index` ist eine gemeinsame Bibliothek, kein Dienst: Verbindung zu OpenSearch, Indexnamen, Indexer und
die Regeln für IDs. Chat und Ingest müssen dieselben Regeln benutzen, sonst findet die Suche nicht, was indexiert
wurde. Deshalb liegt sie einmal im App-Repo und wird in beide Images kopiert.

## Ordner

| Ordner | Inhalt |
|---|---|
| [`chat-system/`](chat-system) | der Chat (Streamlit, Datenbank, Befehle `chat-ask`, `chat-doctor`) |
| [`retrieval/`](retrieval) | Bibliothek: Suche in vier Kanälen, Graph, Prompt |
| [`users/`](users) | Bibliothek: Benutzer (lokal ein Test-Benutzer, remote aus Headern), Rundenlimit |
| [`ingest/`](ingest) | die Ingest-API |
| [`opensearch-index/`](opensearch-index) | gemeinsame Bibliothek und der Befehl `osi` (Indizes anlegen, indexieren, Status) |
| [`deploy/k8s/`](deploy/k8s) | Manifeste für Chat und Ingest |
| [`deploy/auth-test/`](deploy/auth-test) | lokaler Test des Anmelde-Proxys |
| `user-manual-books/handbuch_daten/Ontologie/` | die Ontologie `ontology.yaml`: für Chat, Ingest und die Tests |
| [`docs/`](docs) | Entscheidungen (ADR), Anforderungen und [`OFFENE-PUNKTE.md`](docs/OFFENE-PUNKTE.md) |

Jeder Ordner hat eine eigene `README.md`. Der docling-graph-service liegt in einem eigenen Repo.

## Profile

| Profil | Benutzer | Dienste |
|---|---|---|
| lokal | ein Test-Benutzer (`USERS__ADAPTER=env`) | `make run` im Chat, Container mit `docker compose` |
| remote (dev, test, prod) | aus den Headern des Anmelde-Proxys (`USERS__ADAPTER=header`) | Kubernetes, Werte je Umgebung in den ConfigMaps |

## Schnellstart lokal

```bash
cd chat-system && cp .env.example .env && make dev && make doctor && make run     # Chat: http://127.0.0.1:8501
cd docling-graph && docker compose --profile local up -d                           # dgs (eigenes Repo): http://localhost:8080
cd ingest && docker compose up -d --build                                          # API:  http://127.0.0.1:8090/docs
curl -H "X-API-Key: $KEY" -F pdf=@Handbuch.pdf -F ontology=bhb http://127.0.0.1:8090/v1/ingest
```

## Regeln, die überall gelten

- **Ein Embedding-Modell je Index.** dgs, Ingest und Chat müssen dasselbe Modell, dieselbe Vektorgröße und die
  passenden Präfixe benutzen. Der Ingest-Dienst prüft das vor jeder Verarbeitung.
- **Neuer Index-Präfix nur von Hand:** Indizes mit `osi bootstrap` anlegen und Rechte in OpenSearch vergeben.
- **Nichts wird gespeichert** (Testphase): Gespräche liegen im Pod, dgs und Ingest halten keine Dateien.
- **Images laufen ohne Schreibrechte** auf Home und Wurzel, unter beliebiger Benutzer-ID, ohne Internet.
- **Passwörter und API-Keys** stehen nie im Repo: lokal in `.env`, im Cluster in Secrets.

Ältere, ausführliche Beschreibung (Englisch): [`docs/README-alt-en.md`](docs/README-alt-en.md).
