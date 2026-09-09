# rag-retrieval — module 3: from a question to the prompt (and the answer)

Takes a German question about the indexed operations manuals and returns everything the chat needs: the best
passages from OpenSearch (four search channels fused client-side), the graph facts and entity cards around the
entities the question names (one hop over the union graph of all indexed books), citations with document id and
page for every source, a guardrail verdict, and the rendered German context block for the model. It also ships the
OpenAI-compatible chat client (complete/stream), question rewriting from the last turns (SPEC §8) and `answer()`,
which refuses without a model call when the evidence of a first turn is weak (ADR-0011) and answers a weak
follow-up from the conversation ([`requirements/REQ-001`](requirements/REQ-001-robust-question-understanding.md)).
Pure library + `rag-retrieve` CLI; the Streamlit UI (module `chat-system/`) only wraps it.

Verified 2026-09-04 against the local stack (OpenSearch 3.8.0 with CaaS `BHB-PLT-0001` and ZSD `BHB-PLT-0007`
indexed, bge-m3 embeddings and `gemini-dev` through the LiteLLM proxy): the 8 ground-truth questions of
[`REPORT.md`](REPORT.md) land on the expected pages in fast and slow mode, the deliberate non-couplings of the test
corpus come out as explicit negations ("Vault hängt NICHT von PKI/Keycloak ab", "Vault versiegelt → VPP:
severity keine"), the off-topic question is refused without calling the model; 103 unit + 13 integration tests
green; a slow-mode retrieval takes ~0.3–0.5 s of which ~0.2 s is the query embedding.

## How a question is answered

```
question ──► analyze ──► embed ──► msearch (4 channels) ──► RRF ──► guardrail ──► graph (slow) ──► RRF ──► groups + citations
              │                       knn · bm25 · identifier · label                │   1 hop over all relations
              │ identifiers (ontology regexes)                                       │   facts · entity cards · provenance chunks
              └ node labels/aliases as n-grams, partial label matches                └ skipped when evidence is weak
```

1. **Analyze** (`query.py`, no I/O): identifiers by the ontology regexes (tickets, SOPs, firewall rules, hosts,
   zones, document ids); node labels and aliases of the in-memory graph found as n-grams in the question
   ("Vault", "Kai Ostermann", "ZSD"); labels that *contain* two question words, one of them an already resolved
   label or identifier ("Vault versiegelt | VPP" for "Vault versiegelt") — this is how the degree-0
   `ImpactStatement` nodes are reached, no edge leads to them.
2. **Embed** the question (`embed.py`) with the configured model and prefix; a mismatch with the model recorded on
   the indexed documents is reported as a warning, an unreachable endpoint degrades to the lexical channels.
3. **Four channels in one `msearch`** (`search.py`): kNN, BM25 on `text^2/body_text/caption`, `term identifiers`,
   `term node_labels`. All bodies exclude `embedding`/`bboxes` from `_source`; a document filter goes inside the
   knn clause (lucene filter-during-search) and into a `bool.filter` elsewhere.
4. **Reciprocal rank fusion client-side** (`fusion.py`, rank constant 60) so every chunk keeps *which* channel found
   it at *which* rank (`via knn#2 bm25#1 label#7(vault)`); the server-side `bhb-rrf` pipeline would lose that and
   cannot take the graph list.
5. **Guardrail** (`guardrail.py`): weak evidence iff no identifier hit, no resolved label, and either BM25 found
   nothing or none of the top 3 fused chunks was found by two search channels. Rank/channel based only — bge-m3
   cosine scores compress to ~0.96 for everything, so no absolute threshold (integration REPORT §7). A weak verdict
   refuses without a model call only on a first turn; with conversation history the model answers from the
   conversation (REQ-001 R6, below). Planned (REQ-001 R1–R4): fuzzy and glossary entity matches and an overview
   mode count as evidence.
6. **Graph channel in slow mode** (`graph.py`, `facts.py`): start nodes = resolved labels, partial label matches,
   then node ids of the seed chunks (top fused hits plus the top hits of every channel), ordered by "label mentions
   a question word", the node types the question asks about, presence in several seeds, a static type priority.
   One hop over **all** relation types (graph-retrieval-patterns §4.4, not ADR-0004's intent allowlist). Facts are
   ordered: touching a resolved label first, then the relation types the question's wording asks about
   (`zuständig/eskal` → RESPONSIBLE_FOR/ESCALATES_TO, `Reihenfolge` → PRECEDES, `passiert/Ausfall` →
   DEPENDS_ON/IMPACT_OF, tickets → PARTNER_TICKET), negative before positive. Entity cards = node attributes per
   book, side by side when they differ, alias variants merged ("Kai Ostermann"/"Ostermann"). The provenance chunks
   of the kept facts are fetched by `mget` and fused as the fifth list; the provenance of the best two facts is
   guaranteed a slot (a graph-only hit would otherwise lose against every two-channel hit).
7. **Groups and citations**: table parts with the same caption become one source (header rows once), pages are the
   union; one citation per (document, pages) plus one per fact.
8. **Prompt** (`prompt.py`): German system prompt (cite as `[BHB-PLT-0007 S. 19]`, render NICHT facts as
   negations; earlier answers of the conversation may be reused and transformed; a partial match or a question
   without a concrete system gets "what the manuals contain" plus one clarifying question that names the systems
   of the context as options; exactly "Dazu steht nichts in den Handbüchern." only when neither context nor
   earlier answers hold anything — REQ-001 R5) + context block `## Entitäten` → `## Fakten` → `## Quellen`,
   budgeted with the stored `token_count` of every chunk; the last `history_turns` user/assistant pairs (default
   3, `RAG__RETRIEVAL__HISTORY_TURNS`) precede it. `OVERVIEW_INSTRUCTION_DE` is appended for overview results
   (mode emitted from REQ-001 phase 4 on); `WEAK_FOLLOW_UP_NOTE_DE` replaces the context on a weak follow-up.
9. **Answer** (`chat.py`): `answer()` refuses a weak *first* turn without a model call, answers a weak follow-up
   from the conversation (`weak_note`), otherwise `ChatClient.complete()` or `.stream()` (SSE) against the
   OpenAI-compatible endpoint. `.stream()` returns a `TokenStream` whose `finish_reason` (`length` = cut by
   `max_tokens`) is known after the iteration — consumers read it duck-typed. `rewrite_question()` turns a
   follow-up into a standalone question from the last two turns and falls back to the original on any error.

## Quick start

```bash
cd retrieval
cp .env.example .env                    # dev-box block is active: OpenSearch :9200, LiteLLM :4000 (bge-m3, gemini-dev)
make dev                                # .venv with opensearch-index (sibling, editable) + this package
make check                              # aliases, indexed embedding model vs configured, embedding probe, LLM probe
make graph-stats                        # 2 documents, 400 node ids (60 shared), 281 edges (8 negative)
.venv/bin/rag-retrieve ask "Was passiert, wenn Vault versiegelt ist?"                 # slow mode: hits, facts, entities
.venv/bin/rag-retrieve ask "Was war bei ZSDSUP-0247?" --no-graph                      # fast mode
.venv/bin/rag-retrieve ask "Wer darf Vault entsiegeln und wie?" --answer --stream     # + model answer
.venv/bin/rag-retrieve ask "Wie backe ich einen Apfelkuchen?" --answer                # guardrail -> exit 2, no model call
.venv/bin/rag-retrieve ask "Auf welchen Servern läuft ZSD?" --show-context --budget 3000
.venv/bin/rag-retrieve entities "Vault"                                               # node ids across books + 1-hop facts
make test && RAG_INTEGRATION=1 make test-integration
make questions                          # all ground-truth questions fast/slow -> out/questions/ (ANSWER=1 adds answers)
```

## Library API (what chat-system uses)

```python
from rag_retrieval import Retriever, get_settings, retrieve, build_messages, render_context
from rag_retrieval import ChatClient, answer, rewrite_question, Message, NO_EVIDENCE_ANSWER

r = Retriever(get_settings())                       # one per process; holds the union graph, no per-request state
result = r.retrieve("Was passiert, wenn Vault versiegelt ist?", use_graph=True, k=10, doc_ids=None)
result.chunks      # list[ChunkHit]     fused, deduplicated, with channels[] (channel, rank, score, via)
result.groups      # list[ChunkGroup]   table parts under one caption; .cite -> "BHB-PLT-0007 S. 8–10"
result.facts       # list[GraphFact]    .rendered, .polarity, .quote, .pages, .chunk_ids, .edge_id
result.entities    # list[EntityCard]   .rendered, .occurrences per book
result.citations   # list[Citation]     key "BHB-PLT-0007 S. 19", chunk_ids, edge_ids
result.weak_evidence, result.weak_evidence_reason, result.diagnostics

llm = ChatClient(get_settings().llm)
rw = rewrite_question(history, "und bei Keycloak?", llm)          # RewriteResult(rewritten, used_llm, error)
messages = build_messages(result, question, history)              # [{"role","content"}]; ValueError above the context limit
text = answer(result, question, llm)                              # NO_EVIDENCE_ANSWER when weak, else the model's text
for token in answer(result, question, llm, stream=True): ...      # streamed deltas
r.reload_graph()                                                  # after a new manual was indexed (ADR-0005)
```

`retrieve()` returns a `RetrievalResult` — a superset of SPEC §7.1's `list[Chunk]` (the chunks are in `.chunks`).
Everything is pydantic, so chat-system stores `citations`/`facts`/`diagnostics` as JSON with `model_dump()`.

## Configuration

`config.yaml` in this folder holds the defaults; every key is overridable as `RAG__<SECTION>__<KEY>` from the
environment or `.env` (highest precedence first: environment, `.env`, YAML). `RAG_CONFIG=<file>` selects another
YAML; `./config.yaml` of the working directory is deliberately **not** consulted so chat-system's own `config.yaml`
never leaks in. Secrets stay in `.env`.

| Section | Keys (defaults) | Notes |
|---|---|---|
| `opensearch` | `url` http://localhost:9200, `username`, `password`, `verify_certs`, `ca_certs`, `timeout_s`, `max_retries` | same shape as `OSI__OPENSEARCH__*`; the client ignores proxy variables |
| `index` | `prefix` bhb | aliases `bhb-chunks`, `bhb-nodes`, `bhb-documents` |
| `embedding` | `base_url` http://localhost:4000/v1, `api_key`, `model` bge-m3, `dim` 1024, `query_prefix` "", `timeout_s` 30, `max_attempts` 3 | must match `bhb-documents.embedding_model`; server: `intfloat/multilingual-e5-large` + `"query: "` |
| `llm` | `base_url`, `api_key`, `model` gemini-dev, `temperature` 0.0, `max_tokens` 4000 (reasoning models think ~1300 tokens of it first), `timeout_s` 120, `max_attempts` 2, `context_limit_tokens` 32000 | the only place the chat model is configured (chat-system reuses it) |
| `retrieval` | `k_per_channel` 20, `final_k` 10, `rrf_rank_constant` 60, `graph_seed_hits` 5, `graph_seed_per_channel` 2, `graph_max_start_nodes` 30, `graph_max_facts` 40, `graph_max_chunks` 15, `graph_min_sources` 2, `graph_max_entities` 15, `label_max_ngram` 4, `label_min_chars` 3, `partial_label_min_tokens` 2, `partial_label_max_nodes` 8, `context_token_budget` 6000, `max_facts_in_prompt` 25, `history_turns` 3 | small Ollama models: budget 2500, `RAG__LLM__CONTEXT_LIMIT_TOKENS=4096`; large served context: `history_turns` 10 |
| `guardrail` | `enabled` true, `min_agreeing_channels` 2, `top_n` 3 | ADR-0011, amended by REQ-001 (follow-up rule now; fuzzy/glossary/overview evidence planned) |
| `ontology` | `path` ../user-manual-books/…/ontology.yaml | identifier regexes and relation `label_de` |

## CLI

| Command | What it does |
|---|---|
| `rag-retrieve ask "Frage" [--graph/--no-graph] [--k N] [--doc ID …] [--json] [--show-context] [--budget N]` | retrieval only: identifiers, labels, partial label matches, channels with timings, guardrail verdict, ranked sources with `via`, facts (NICHT prefixed), entity cards |
| `… ask "Frage" --answer [--stream] [--model M] [--force] [--history-file h.json]` | plus the model answer; `--history-file` (JSON list of `{role, content}`) enables question rewriting and the follow-up rule (a weak verdict is then answered from the conversation, "Hinweis: schwache Evidenz"); exit code 2 only when the guardrail refuses a first turn (`--force` overrides); a truncated stream prints "[Antwort vom Modell gekürzt …]" |
| `rag-retrieve graph-stats [--json]` | size of the in-memory union graph |
| `rag-retrieve entities "Vault"` | resolve a label/alias to node ids across books, occurrences with attributes, 1-hop facts |
| `rag-retrieve check [--json]` | aliases present, indexed documents and their embedding model vs the configured one, embedding probe (dimension), LLM probe; exit 1 when something is off |

Global options: `--url`, `--prefix`, `--ontology`, `--log-level` (set the corresponding `RAG__*` for the call).

## Tests

```bash
make test                                   # 111 unit tests, no services: fake OpenSearch client (cosine kNN, token-overlap
                                            # BM25 with German stopwords, term/terms/bool, msearch, mget) over the indexer's
                                            # own transform of the small ZSD fixture; httpx.MockTransport for embed/chat
RAG_INTEGRATION=1 make test-integration     # 13 live tests: check(), 1024-dim embedding, the ground-truth table of REPORT.md
                                            # fast and slow, guardrail without model call, rewrite and answer with the LLM
```

The graph tests also run against the real extraction graphs in `../out/remote-*/graph.json` when present (60 shared
node ids, the two negative `Vault —DEPENDS_ON→ PKI/Keycloak` edges, 21 PRECEDES edges) and skip otherwise.

## Deployment notes

The module is a library: it runs wherever chat-system runs (`pip install -e ../opensearch-index -e ../retrieval`,
see `requirements.txt`). Nothing listens on a port. Remote server: use the second block of `.env.example`
(e5 model + `"query: "` prefix, endpoints through SSH tunnels, ontology under `/srv/rag`), never put proxy variables
in `.env` — both httpx clients run with `trust_env=False` and the OpenSearch client never consults the proxy either.

## Design notes and limitations

- **Client-side RRF** instead of the `bhb-rrf` search pipeline: per-channel attribution and the graph list.
- **1 hop over all relations** (graph-retrieval-patterns §4.4) rather than ADR-0004's intent-routed allowlist; the
  question-cue *ordering* of relations and node types (`facts.RELATION_CUES`) is a heuristic on wording, not an
  intent router. ADR addendum: this module supersedes ADR-0004's allowlist for retrieval; a router can later
  restrict `expand()` per intent.
- Entity cards are part of the graph context because "VPP unaffected by Vault" is an `ImpactStatement` node with
  `severity: keine`, not a negative edge.
- `node_labels` terms are the lowercased original spellings (`lc` normalizer), never `norm_key` (ß → ss).
- No compaction of long conversations; rewriting looks at the last two turns only (SPEC §8).
- Cross-document merge is by shared `node_id` and label/alias spelling only (no fuzzy entity resolution); a person
  extracted as "Ostermann" in one book and "Kai Ostermann" in the other is merged through the alias, two
  differently spelled systems are not.
- The graph is loaded once per process (~1 MB per book); `reload_graph()` swaps it after a new ingest.
- `estimate_tokens` is `len / 2.6` (measured on this corpus with Gemini: 19,120 chars = 7,336 tokens); chunk budgets
  use the stored `token_count`. No tokenizer dependency. The 6000-token default budget is ~7,000 real tokens.
