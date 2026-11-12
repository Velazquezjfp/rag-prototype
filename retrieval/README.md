# rag-retrieval

Bibliothek für den Chat: macht aus einer Frage die Treffer aus OpenSearch, die Fakten aus dem Graphen, die
Quellenangaben und den Prompt für das Sprachmodell. Kein eigener Dienst, kein Port; sie läuft im Chat-Image.
Zum Testen ohne Oberfläche gibt es den Befehl `rag-retrieve`.

```
Frage ─▶ Analyse ─▶ Embedding ─▶ 4 Suchkanäle ─▶ Fusion ─▶ Evidenz-Prüfung ─▶ Graph ─▶ Quellen + Prompt ─▶ Antwort
                                 kNN · BM25 · Kennungen · Namen              (nur Graph-Modus)
```

## Ablauf

1. **Analyse:** findet in der Frage Kennungen (Tickets, SOPs, Hosts, Dokument-IDs) nach den Mustern der Ontologie
   und Namen aus dem Graphen („Vault“, „ZSD“).
2. **Suche:** vier Kanäle in einem Aufruf an OpenSearch: Vektorsuche (kNN), Stichwortsuche (BM25), Kennungen,
   Namen von Knoten.
3. **Fusion:** die Trefferlisten werden im Client zusammengeführt (RRF). Jeder Treffer behält, welcher Kanal ihn
   gefunden hat.
4. **Evidenz-Prüfung (Guardrail):** bei schwacher Evidenz kommt auf eine erste Frage die feste Antwort
   „Dazu steht nichts in den Handbüchern.“, ohne Aufruf des Modells. Eine Folgefrage beantwortet das Modell aus
   dem Gespräch.
5. **Graph (nur im Graph-Modus):** ein Schritt über alle Beziehungen der gefundenen Knoten. Das liefert Fakten
   (auch verneinte), Entitäts-Karten und weitere Textstellen.
6. **Prompt:** deutscher System-Prompt und der Kontext `Entitäten → Fakten → Quellen` innerhalb eines
   Token-Budgets, dazu die letzten Runden des Gesprächs. Jede Quelle trägt Dokument-ID und Seite, zum Beispiel
   `[BHB-PLT-0007 S. 19]`.
7. **Antwort:** `ChatClient` ruft das Sprachmodell über eine OpenAI-kompatible Adresse, auch als Stream.

## Prompt-Profile

| Profil | Verhalten |
|---|---|
| `strict` | antwortet nur aus den Handbüchern; der Guardrail blockiert |
| `assistant` | technischer Assistent (Skripte, Log-Analyse, Befehle anpassen), gestützt auf die Handbücher; der Guardrail gibt nur einen Hinweis |
| `auto` (Standard) | `assistant`, wenn `RAG__GUARDRAIL__ENABLED=false`, sonst `strict` |

## Einstellungen

Standardwerte in `config.yaml`, überschreibbar mit `RAG__<BEREICH>__<SCHLÜSSEL>` (Umgebung oder `.env`).
`RAG_CONFIG=<datei>` wählt eine andere YAML-Datei. Vorlage: `.env.example`.

| Variable | Standard | Bedeutung |
|---|---|---|
| `RAG__OPENSEARCH__URL`, `__USERNAME`, `__PASSWORD` | `http://localhost:9200`, –, – | OpenSearch; Lesen genügt (`bhb_reader`) |
| `RAG__OPENSEARCH__VERIFY_CERTS`, `__CA_CERTS` | `true`, – | Zertifikatsprüfung, eigene CA-Datei |
| `RAG__INDEX__PREFIX` | `bhb` | Index-Präfix |
| `RAG__EMBEDDING__BASE_URL`, `__API_KEY`, `__MODEL`, `__DIM`, `__QUERY_PREFIX` | `http://localhost:4000/v1`, –, `bge-m3`, 1024, leer | Vektor für die Frage; Modell, Größe und Präfix müssen zum Index passen |
| `RAG__LLM__BASE_URL`, `__API_KEY`, `__MODEL` | `http://localhost:4000/v1`, –, `gemini-dev` | das Sprachmodell; die einzige Stelle dafür, auch für den Chat |
| `RAG__LLM__MAX_TOKENS`, `__CONTEXT_LIMIT_TOKENS` | 4000, 32000 | Länge der Antwort, Kontextgrenze des Modells |
| `RAG__LLM__EXTRA_BODY` | `{}` | JSON, das jede Anfrage mitbekommt, z. B. `{"think": false}` |
| `RAG__RETRIEVAL__CONTEXT_TOKEN_BUDGET` | 6000 | Größe des Kontexts im Prompt |
| `RAG__RETRIEVAL__HISTORY_TURNS` | 3 | Runden des Gesprächs im Prompt |
| `RAG__GUARDRAIL__ENABLED`, `__MIN_AGREEING_CHANNELS` | `true`, 2 | Evidenz-Prüfung; `false` = nur Hinweis |
| `RAG__PROMPT__PROFILE` | `auto` | siehe oben |
| `RAG__ONTOLOGY__PATH` | `../user-manual-books/handbuch_daten/Ontologie/ontology.yaml` | Muster für Kennungen, Namen der Beziehungen |

Weitere Schlüssel für Suche und Graph stehen mit Erklärung in `config.yaml`.

## Lokal

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt       # installiert auch ../opensearch-index
cp .env.example .env
.venv/bin/rag-retrieve check                                                # Indizes, Modell im Index, Embedding und Sprachmodell
.venv/bin/rag-retrieve ask "Was passiert, wenn Vault versiegelt ist?"       # Graph-Modus: Treffer, Fakten, Entitäten
.venv/bin/rag-retrieve ask "Was war bei ZSDSUP-0247?" --no-graph            # schneller Modus
.venv/bin/rag-retrieve ask "Wer darf Vault entsiegeln?" --answer --stream   # mit Antwort des Modells
.venv/bin/rag-retrieve entities "Vault"                                     # ein Name über alle Bücher
make test                                                                   # 154 Tests, ohne Dienste
RAG_INTEGRATION=1 make test-integration                                     # gegen OpenSearch und die Modelle
```

## Verwendung im Code

```python
from rag_retrieval import ChatClient, Retriever, answer, build_messages, get_settings

r = Retriever(get_settings())                           # einmal pro Prozess
result = r.retrieve("Frage", use_graph=True, k=10, doc_ids=None)
result.chunks, result.facts, result.entities, result.citations, result.weak_evidence
messages = build_messages(result, "Frage", history)     # der Prompt als Liste von Nachrichten
text = answer(result, "Frage", ChatClient(get_settings().llm))
r.reload_graph()                                        # nach dem Indexieren eines neuen Buchs
```

## Hinweise

- **Der Graph liegt im Speicher** und wird einmal beim Start geladen. Nach einem neuen Buch: `reload_graph()`
  aufrufen oder den Prozess neu starten. Der Chat ruft `reload_graph()` heute nicht auf.
- **Embedding-Modell:** Frage und Index brauchen dasselbe Modell. `rag-retrieve check` vergleicht die Einstellung
  mit dem Modell im Index.
- **Proxy:** die HTTP-Clients beachten keine Proxy-Variablen.
- **Lange Gespräche** werden nicht zusammengefasst. Die Grenze ist das Rundenlimit im Chat.

Mehr: [`REFERENCE.md`](REFERENCE.md) (ausführlich, Englisch), [`requirements/`](requirements) (REQ-001, REQ-002),
[`REPORT.md`](REPORT.md) (Testfragen und Ergebnisse).
