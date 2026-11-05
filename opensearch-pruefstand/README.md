# opensearch-pruefstand

Ein Jupyter-Notebook, das eine OpenSearch-Instanz von außen prüft: Verbindung, Plugins (k-NN), Rechte, die vier
Indizes anlegen, ein Handbuch (`out/remote-zsd/response.json`) laden, die vier Suchkanäle, Graph-Fakten, RRF.
Erst gegen den lokalen Container, dann – nur über `PROFIL = "remote"` – gegen die entfernte Instanz.

```bash
cp .env.example .env                       # Remote-Zugang (OS_REMOTE_*) und Embedding-Endpunkt eintragen; .env ist gitignored
(cd ../opensearch-index && make up)        # lokaler OpenSearch-Container
../database_comparison/.venv/bin/jupyter lab opensearch_pruefstand.ipynb      # Kernel: Python (database_comparison)
```

Der Kernel kommt aus `database_comparison/` (dort `README.md`: venv anlegen, Kernel registrieren); er enthält
`opensearch_index`, `rag_retrieval`, `opensearch-py`, `pandas`. Headless:

```bash
../database_comparison/.venv/bin/jupyter nbconvert --to notebook --execute --inplace \
  --ExecutePreprocessor.kernel_name=database-comparison opensearch_pruefstand.ipynb
```

Alle Indizes des Notebooks heißen `nbtest-*` (Variable `PREFIX`); `AUFRAEUMEN = True` löscht sie am Ende.
Feld- und Abfragereferenz: `../OPENSEARCH-INDEXES.md`.
