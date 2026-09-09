# REQ-001 — Robust question understanding: the chat side

| Field | Value |
|---|---|
| ID | REQ-001 (chat-system part) |
| Module | `chat-system` (`chat_system`) — owns R6 (turn semantics), R8 (persisted/shown truncation), R9 (UI honesty) |
| Sibling document | [`retrieval/requirements/REQ-001-robust-question-understanding.md`](../../retrieval/requirements/REQ-001-robust-question-understanding.md) (motivation, R1–R5, R7, acceptance classes) |
| Status | accepted 2026-09-08 · **phase 1 implemented 2026-09-08** |

## 1. Motivation (chat view)

Users saw "Dazu steht nichts in den Handbüchern." on general questions while the status line reported "8 Quellen ·
40 Fakten · 15 Entitäten", follow-ups such as "Mach ein Script mit diesen Befehlen" were refused for lack of new
evidence, and answers cut by `max_tokens` appeared as empty bubbles because the truncation never reached the turn.

## 2. Requirements

| # | Requirement | Level | Status |
|---|---|---|---|
| R6 | **Follow-up rule.** `ChatService.ask()` calls the model when the retrieval is weak **and** the conversation has history (`build_messages(..., weak_note=True)`); a weak first turn stays a guardrail turn (canned sentence, model not called). Weak turns cite nothing (`TurnStream.citations == []`); the diagnostics carry `weak_follow_up`. | MUST | **implemented** |
| R7 | **Conversation window.** `ask()` passes `max_history_turns=rag_settings.retrieval.history_turns` to `build_messages` (`RAG__RETRIEVAL__HISTORY_TURNS`, 10 on the server). The rewrite keeps `CHAT__RETRIEVAL__HISTORY_TURNS_FOR_REWRITE`. | MUST | **implemented** |
| R8 | **Truncation persisted and shown.** `TurnStream.tokens()` reads `finish_reason` from the stream after the iteration (duck-typed) and finishes the turn as `length` (text kept, usage counted); the UI caption "Antwort vom Modell gekürzt (max_tokens)." and the Diagnostik line show it; `chat-ask` prints it in the summary line. | MUST | **implemented** |
| R9 | **UI honesty.** The search status line says "Keine belastbaren Treffer · schwache Evidenz · Modell nicht aufgerufen" on a guardrail turn and "Keine neuen Treffer · Antwort aus dem Gesprächsverlauf" on a weak follow-up; otherwise it counts sources/facts/entities with the mode in words (`schnell`, `Graph`, `Übersicht`). A weak follow-up gets its own caption; the Diagnostik shows the mode, `Folgefrage ohne neue Evidenz` and the truncation. | MUST | **implemented** |
| — | Clickable option chips for the clarifying question (the systems named in the answer) | COULD | later |

## 3. Acceptance

| Scenario | Expected | Test |
|---|---|---|
| Weak first turn ("Apfelkuchen") | canned sentence, `guardrail=True`, `llm_called=False`, no Quellen expander, status line without counts | `test_service_guardrail.py::test_weak_evidence_yields_the_canned_sentence_without_calling_the_model`, `test_ui_smoke.py::test_guardrail_answer_is_shown_with_note` |
| Weak follow-up after an answer with commands | model called with history + note, `guardrail=False`, `weak_follow_up=True`, `citations == []`, `finish_reason=stop`, counted | `test_service_guardrail.py::test_weak_follow_up_is_answered_from_the_conversation` |
| `history_turns=1` in the retrieval settings | the prompt carries one earlier pair | `test_service_flow.py::test_history_window_comes_from_the_retrieval_settings` |
| Stream reports `length` | turn and row `finish_reason=length`, text kept, usage counted | `test_service_flow.py::test_truncated_stream_is_persisted_as_length` |
| Normal turn | status line "2 Quellen · 1 Fakten · 1 Entitäten (Graph)" | `test_ui_smoke.py::test_status_label_counts_sources_on_a_normal_turn` |

Live: `make smoke`; `chat-ask "Wie entsiegle ich den Vault?" --json` → conversation id → `chat-ask "Mach ein Script
mit diesen Befehlen" --conversation <id>` yields a script with `guardrail=False`; `RAG__LLM__MAX_TOKENS=200 make ask …`
shows `length` in the summary line.

## 4. Configuration

No new `CHAT__*` keys. `.env`: `RAG__RETRIEVAL__HISTORY_TURNS=10` in the server block; `RAG__LLM__MAX_TOKENS` sized for
enumerating answers and reasoning models (truncation is visible now, not silent).

## 5. Affected files

`src/chat_system/service.py` (`ask()` step 6, `TurnStream.citations`/`weak_follow_up`/`diagnostics`/`tokens()`),
`ui/chat.py` (`status_label()`, captions, Diagnostik), `cli.py` (summary line), `.env.example`; tests
`tests/unit/test_service_guardrail.py`, `test_service_flow.py`, `test_ui_smoke.py`. Documentation: `README.md`
("How a question is answered", steps 7–8).
