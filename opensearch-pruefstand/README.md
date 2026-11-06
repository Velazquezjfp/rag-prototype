# opensearch-pruefstand

Ein Jupyter-Notebook, das eine OpenSearch-Instanz von außen prüft und die echten Indizes anlegt: Verbindung, Plugins
(k-NN), Rechte, die vier Indizes, Rollen für Indexer und Chat, danach die vier Suchkanäle, Graph-Fakten, RRF.

```bash
cp .env.example .env                       # Remote-Zugang (OS_REMOTE_*), Passwörter der technischen Benutzer, Embedding-Endpunkt
(cd ../opensearch-index && make up)        # nur für PROFIL = "lokal": lokaler OpenSearch-Container
../database_comparison/.venv/bin/jupyter lab opensearch_pruefstand.ipynb      # Kernel: Python (database_comparison)
```

Der Kernel kommt aus `database_comparison/` (dort `README.md`: venv anlegen, Kernel registrieren); er enthält
`opensearch_index`, `rag_retrieval`, `opensearch-py`, `pandas`.

## Zwei Betriebsarten (Zelle 1: `PROFIL`, `PREFIX`)

| `PREFIX` | Zweck | Ablauf |
|---|---|---|
| `bhb` (Standard) | **die echten Indizes** `bhb-chunks/-nodes/-documents/-manifest`, die Chat und `osi` benutzen | §1–§5 prüfen und anlegen (shards 1, replicas 0 = Einzelknoten), §5b Rollen, **Stopp vor §6**. Kein Beispiel-Ingest, §10 löscht nie. |
| `nbtest` | Spielwiese | Beispiel-Handbuch `out/remote-zsd` laden, Kanäle zeigen, mit `AUFRAEUMEN = True` löschen |

Ablauf gegen die entfernte Instanz (`PROFIL = "remote"`, `PREFIX = "bhb"`):

1. Notebook bis zum Stopp vor §6 ausführen. §4 legt einen temporären `bhb-verify-*`-Index an und löscht ihn wieder
   (danach meldet `_plugins/_knn/stats` `lucene_initialized: true`).
2. §5b: `ROLLEN_ANLEGEN = True`, Zelle erneut ausführen → `bhb_writer` und `bhb_reader`; die Zelle darunter prüft den
   Leser (Chat-Aufrufe erlaubt, Schreiben 403).
3. Handbücher indexieren: `integration/process_and_index.py` mit `opensearch-index/.env` (unten).
4. Notebook **ab §7** ausführen: Rauchtest der vier Kanäle, Graph und RRF auf den echten Daten.

Workspaces und Data Sources von OpenSearch Dashboards braucht das nicht: sie ordnen gespeicherte Objekte und
Verbindungen der Oberfläche, nicht Indizes oder REST-Rechte. Ein Workspace lohnt sich nur, wenn das Team in
Dashboards eigene Ansichten auf `bhb-*` bauen will.

## Ein Modell pro Index

Die Vektoren kommen fertig von docling-graph; OpenSearch hat kein eigenes Modell. Dasselbe Modell und dieselben
Präfixe müssen an drei Stellen stehen, sonst sucht kNN mit falschen Vektoren (beide Kandidaten haben 1024 Dimensionen,
ein Fehler fällt also nicht auf):

| Wo | Einstellung (PREFIX `bhb`) |
|---|---|
| docling-graph (zentral) | `DGS__EMBEDDING__MODEL=intfloat/multilingual-e5-large`, `DGS__EMBEDDING__TEXT_PREFIX="passage: "` |
| osi / `process_and_index.py` | `OSI__EMBEDDING__MODEL=intfloat/multilingual-e5-large`, `OSI__EMBEDDING__TEXT_PREFIX="passage: "` |
| Chat | `RAG__EMBEDDING__MODEL=intfloat/multilingual-e5-large`, `RAG__EMBEDDING__QUERY_PREFIX="query: "` |

## `opensearch-index/.env` für `process_and_index.py` gegen die entfernte Instanz

```
OSI__OPENSEARCH__URL=https://<host>:9200
OSI__OPENSEARCH__USERNAME=bhb_writer
OSI__OPENSEARCH__PASSWORD=<OS_WRITER_PASSWORD>
OSI__OPENSEARCH__CA_CERTS=/pfad/zur/firmen-ca.pem
OSI__INDEX__REPLICAS=0                  # Einzelknoten
OSI__INDEX__RRF_PIPELINE=false          # der Chat fusioniert selbst
OSI__EMBEDDING__MODEL=intfloat/multilingual-e5-large
OSI__EMBEDDING__DIM=1024
OSI__EMBEDDING__TEXT_PREFIX="passage: "
```

Der Chat bekommt `RAG__OPENSEARCH__URL`, `RAG__OPENSEARCH__USERNAME=bhb_reader`, `RAG__OPENSEARCH__PASSWORD`,
`RAG__OPENSEARCH__CA_CERTS`. Feld- und Abfragereferenz: `../docs_poc/OPENSEARCH-INDEXES.md`.
