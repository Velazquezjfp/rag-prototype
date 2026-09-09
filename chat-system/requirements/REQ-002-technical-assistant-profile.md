# REQ-002 — Technical-assistant profile: the chat side

| Field | Value |
|---|---|
| ID | REQ-002 (chat-system part) |
| Module | `chat-system` (`chat_system`) — owns the turn semantics of the profile, raw question + material handling, the UI half of R6 and R10 |
| Sibling document | [`retrieval/requirements/REQ-002-technical-assistant-profile.md`](../../retrieval/requirements/REQ-002-technical-assistant-profile.md) (motivation, R1–R9, acceptance classes) |
| Status | accepted 2026-09-09 · **implemented 2026-09-09**, live-checked with `chat-ask` on the dev box |

## 1. Motivation (chat view)

With the guardrail relaxed (REQ-001) the chat still answered from the manuals only: "Mach daraus ein Skript, das alle
20 Minuten prüft …" or a pasted error log had no grounded path, a multi-line paste was whitespace-collapsed before it
reached the DB or the model, and nothing told the user which behaviour was active.

## 2. Requirements

| # | Requirement | Level | Status |
|---|---|---|---|
| C1 | **Profile.** `ChatService.profile` = `resolve_profile(rag_settings)` (`RAG__PROMPT__PROFILE`, `auto` = assistant iff `RAG__GUARDRAIL__ENABLED=false`), `strict` without rag settings; `ChatService(profile=…)` overrides (tests). `ChatService.guardrail_enabled` for the UI. | MUST | **implemented** |
| C2 | **Assistant turns never refuse.** `ask()` step 6 builds the prompt for every assistant turn with `profile="assistant"`, `material=`, `ecosystem=retriever.ecosystem_summary(doc_ids)` (duck-typed); the weak verdict is the `Evidenzlage` only; `weak_follow_up` stays a strict-profile notion; weak turns cite nothing. | MUST | **implemented** |
| C3 | **Raw question and material.** The message is `strip()`ped, never whitespace-collapsed; `begin_turn` stores the raw text (line breaks kept); `split_material(raw)` gives the instruction (rewritten from the second turn on unless it is the default "Analysiere das folgende Material.") and the material (`retrieve(material=…)` only when present). `TurnStream.diagnostics["material_chars"]`. | MUST | **implemented** |
| C4 | **Block off the stream.** `TurnStream.tokens()` wraps the model stream in `AnalysisSplitter` in the assistant profile; the persisted `Message.content` is the answer without the block; `TurnStream.analysis`, `.profile`, `.off_topic`; `citations == []` when `Bereich: außerhalb`; diagnostics: `profile`, `analysis` (as_dict), `off_topic`, `history_turns_used`. `finish_reason` duck-typing and `GeneratorExit` handling unchanged. | MUST | **implemented** |
| C5 | **UI honesty.** Sidebar caption "Modus: Technik-Assistent · Guardrail aus" / "Modus: Handbuch-Antworten · Guardrail an" (`sidebar.mode_caption`); status line "Technik-Assistent · n Quellen · n Fakten · n Entitäten · Evidenz stark\|schwach (mode)"; captions "Einordnung: Aufgabe … · Bereich … · System … · Grundlage …" (`analysis_caption`), "Außerhalb des Aufgabenbereichs …", injection note; user bubble shows material in a fenced block (`format_user_message`, also on replay); Diagnostik shows Profil, assessed evidence when the guardrail is off, material size, history turns used, the raw block; input placeholder invites material (Shift+Enter). | MUST | **implemented** |
| C6 | **CLI.** `chat-ask --material-file m.log` appends the file as material; the summary line adds `Profil`, `Einordnung: <task> / <scope> / <systems>`, `Außerhalb des Aufgabenbereichs`. | MUST | **implemented** |
| — | Per-conversation toggle of the profile (sidebar switch, `Conversation` column) | COULD | later (decision 2026-09-09: server setting only this round) |

## 3. Acceptance

| Scenario | Expected | Test |
|---|---|---|
| Assistant profile, weak retriever, block reply | `guardrail False`, `weak_follow_up False`, answer starts after the block, `analysis.task == "Skript"`, persisted content without tag, `diagnostics["profile"] == "assistant"`, citations blank (weak), strong turn cites and says `Evidenzlage: stark`, `history_turns_used` | `test_service_flow.py::test_assistant_profile_answers_weak_turns_and_strips_the_block` |
| Default profile | `strict`, system prompt == `SYSTEM_PROMPT_DE` (pre-existing assertion at `test_service_flow.py:22` unchanged) | same test + `test_first_turn_streams_persists_and_counts` |
| Multi-line paste | user row keeps `\n`; `retriever.calls[-1]["material"]` = the log; prompt has the fenced material and ends with `Frage: <instruction>`; follow-up rewrite sees the instruction only; bare log → default instruction, no rewrite call; `format_user_message` fences it | `test_service_flow.py::test_multiline_paste_keeps_the_raw_text_and_passes_the_material` |
| Off-topic verdict | answer == `OUT_OF_SCOPE_ANSWER_DE`, `off_topic True`, `citations == []`, persisted `off_topic`/`analysis.in_scope False`, counted | `test_service_guardrail.py::test_off_topic_analysis_blanks_the_citations` |
| Labels and captions | assistant status line, `analysis_caption`, `mode_caption`, fenced user message | `test_ui_labels.py::test_assistant_labels_and_captions` |
| UI | sidebar shows "Technik-Assistent", answer without the tag, "Einordnung: Aufgabe: Skript" caption | `test_ui_smoke.py::test_assistant_mode_shows_the_mode_line_and_the_einordnung` |

Live (dev box, gemini-dev, `RAG__GUARDRAIL__ENABLED=false`): `chat-ask "Wie entsiegle ich den Vault?" --json` →
`profile assistant`, analysis `Verfahren / innerhalb / Zentrale Sicherheitsdienste (Vault), CaaS-Plattform /
Handbücher`, 25 citations, no block in the answer; `chat-ask "Mach daraus ein Skript, das alle 20 Minuten den Zustand
prüft und über den dokumentierten Alarmweg meldet" --conversation <id>` → bash script around `vault status`, Sev-1
mail to the documented mailbox and the Rufbereitschaft number from the manuals, cron and OpenShift CronJob labelled
"(allgemeines Fachwissen, nicht aus den Handbüchern)", `<SA_MIT_EXEC_RECHTEN>` placeholder.

## 4. Configuration

No new `CHAT__*` keys. `.env`: `RAG__GUARDRAIL__ENABLED=false` (profile `auto`) switches the chat to the assistant;
`RAG__PROMPT__PROFILE` forces one; `RAG__LLM__EXTRA_BODY='{"think": false}'` for Gemma on Ollama. Settings are read
once per process — restart `make run` after a `.env` change.

## 5. Affected files

`src/chat_system/service.py` (`_Turn.profile/instruction/material`, `ChatService(profile=)`, `.profile`,
`.guardrail_enabled`, `ask()` raw/split/rewrite/retrieve/build, `TurnStream.analysis/profile/off_topic/citations/
weak_follow_up/diagnostics/tokens`), `ui/chat.py` (`status_label`, `format_user_message`, `analysis_caption`,
captions, `render_diagnostics`, placeholder), `ui/sidebar.py` (`mode_caption`), `cli.py` (`--material-file`, summary),
`.env.example`; tests `tests/unit/conftest.py` (`FakeRetriever.retrieve(**kwargs)`, `ecosystem_summary`,
`make_service(profile=)`), `test_service_flow.py`, `test_service_guardrail.py`, `test_ui_labels.py`,
`test_ui_smoke.py` → 58 unit + 6 AppTest. Documentation: `README.md` ("How a question is answered" steps 6–8,
configuration hint, CLI, tests), `REPORT.md` ("Update 2026-09-09 — REQ-002").
