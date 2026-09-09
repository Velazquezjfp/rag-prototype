"""The chat pane: replay of the conversation, the input, one streamed turn, sources and diagnostics."""

from __future__ import annotations

from typing import Any

import streamlit as st
from rag_retrieval import split_material
from rag_users import AuthContext

from ..service import ERROR_TEXT_DE, ChatService, TurnRefused
from ..settings import Settings
from .sidebar import SidebarState

CAPPED_TEXT_DE = "Dieses Gespräch hat die maximale Länge erreicht. Bitte ein neues Gespräch beginnen."
GUARDRAIL_NOTE_DE = "Schutzmechanismus: keine belastbaren Treffer in den Handbüchern – das Sprachmodell wurde nicht aufgerufen."
WEAK_FOLLOW_UP_NOTE_DE = "Folgefrage ohne neue Treffer – Antwort aus dem Gesprächsverlauf, keine neuen Quellen."
OUT_OF_SCOPE_NOTE_DE = "Außerhalb des Aufgabenbereichs – der Technik-Assistent hilft nur beim Betrieb der dokumentierten Systeme."
INJECTION_NOTE_DE = "Hinweis: Die Eingabe enthielt Formulierungen wie Anweisungen an das Modell; sie wurden als Daten behandelt."
MODE_LABEL_DE = {"fast": "schnell", "slow": "Graph", "overview": "Übersicht"}
INPUT_PLACEHOLDER_DE = "Frage oder Material (Log, Befehle) einfügen – Shift+Enter für einen Zeilenumbruch"


def status_label(turn: Any) -> str:
    """What the search status line says once retrieval is done — honest about what was used (REQ-001 R9; REQ-002:
    the assistant profile names itself and the assessed evidence instead of a verdict)."""
    r = turn.result
    if turn.guardrail:
        return "Keine belastbaren Treffer · schwache Evidenz · Modell nicht aufgerufen"
    if getattr(turn, "weak_follow_up", False):
        return "Keine neuen Treffer · Antwort aus dem Gesprächsverlauf"
    mode = MODE_LABEL_DE.get(r.mode, r.mode)
    counts = f"{len(r.groups)} Quellen · {len(r.facts)} Fakten · {len(r.entities)} Entitäten"
    if getattr(turn, "profile", "strict") == "assistant":
        weak = bool(getattr(r.diagnostics, "assessed_weak", False)) or bool(r.weak_evidence)
        return f"Technik-Assistent · {counts} · Evidenz {'schwach' if weak else 'stark'} ({mode})"
    return f"{counts} ({mode})"


def format_user_message(raw: str) -> str:
    """The user bubble: the instruction as text, pasted material in a fenced block (REQ-002 R4) — ``st.markdown``
    would otherwise swallow the line breaks of a log."""
    split = split_material(raw)
    if not split.material:
        return raw
    fence = "````" if "```" in split.material else "```"
    return f"{split.instruction}\n\n{fence}text\n{split.material}\n{fence}"


def analysis_caption(analysis: dict[str, Any]) -> str:
    """One line from the persisted Einordnung (``Analysis.as_dict()``): Aufgabe · Bereich · System · Grundlage."""
    bits = [f"Aufgabe: {analysis.get('task') or 'Sonstiges'}", f"Bereich: {'innerhalb' if analysis.get('in_scope', True) else 'außerhalb'}"]
    if analysis.get("systems"):
        bits.append(f"System: {analysis['systems']}")
    if analysis.get("basis"):
        bits.append("Grundlage: " + ", ".join(analysis["basis"]))
    return "Einordnung: " + " · ".join(bits)


def render(svc: ChatService, ctx: AuthContext, settings: Settings, state: SidebarState) -> None:
    ss = st.session_state
    messages: list[dict[str, Any]] = ss.setdefault("messages", [])
    for m in messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"] if m["role"] == "assistant" else format_user_message(m["content"]))
            if m["role"] == "assistant":
                render_extras(m, state.show_diagnostics)

    if ss.get("capped"):
        st.info(CAPPED_TEXT_DE)
        st.chat_input("Gespräch beendet", disabled=True)
        return

    prompt = st.chat_input(INPUT_PLACEHOLDER_DE)
    if not prompt:
        return

    if ss.conversation_id is None:
        conv = svc.start_conversation(ctx, use_graph=state.use_graph, doc_ids=state.doc_ids)
        ss.conversation_id = conv.id

    with st.chat_message("user"):
        st.markdown(format_user_message(prompt))

    try:
        with st.status("Suche in den Handbüchern …", expanded=False) as status:
            turn = svc.ask(ctx, ss.conversation_id, prompt, use_graph=state.use_graph, doc_ids=state.doc_ids)
            status.update(label=status_label(turn), state="complete")
    except TurnRefused as exc:
        st.warning(exc.message_de)
        if exc.reason == "turn_cap":
            ss.capped = True
        return
    except Exception as exc:  # noqa: BLE001 - shown to the user, logged by the service
        st.error(f"Fehler bei der Suche: {exc}")
        return

    messages.append({"role": "user", "content": prompt})
    with st.chat_message("assistant"):
        try:
            st.write_stream(turn.tokens())
        except Exception as exc:  # noqa: BLE001 - the model failed mid-stream; the service persisted and refunded
            st.error(f"{ERROR_TEXT_DE} ({exc})")
        finally:
            if not turn.done:
                turn.abort()
        entry = {
            "role": "assistant",
            "content": turn.answer,
            "citations": turn.citations,
            "diagnostics": turn.diagnostics,
            "guardrail": turn.guardrail,
            "finish_reason": turn.finish_reason,
            "question_rewritten": turn.question_rewritten,
        }
        render_extras(entry, state.show_diagnostics)
    messages.append(entry)
    if turn.to_result().turns_left <= 0:
        ss.capped = True
    st.rerun()  # refresh quota, conversation list and title; history is replayed, never re-streamed


def render_extras(m: dict[str, Any], show_diagnostics: bool) -> None:
    cits = m.get("citations") or []
    if cits:
        with st.expander(f"Quellen ({len(cits)})"):
            for i, c in enumerate(cits, 1):
                title = f" {c['doc_title']}" if c.get("doc_title") else ""
                key = c.get("key", "")
                pages = key.split(" S. ", 1)[1] if " S. " in key else ""
                crumb = f" · {c['breadcrumb']}" if c.get("breadcrumb") else ""
                tags = " ".join(f"`{ch}`" for ch in c.get("channels") or [])
                st.markdown(f"**[{i}] {c['doc_id']}**{title} · S. {pages}{crumb} {tags}")
                if c.get("snippet"):
                    st.caption(c["snippet"])
                for fact in c.get("facts") or []:
                    st.caption(f"Fakt: {fact}")
    d = m.get("diagnostics") or {}
    analysis = d.get("analysis")
    if m.get("guardrail"):
        st.caption(GUARDRAIL_NOTE_DE)
    elif d.get("weak_follow_up"):
        st.caption(WEAK_FOLLOW_UP_NOTE_DE)
    elif analysis and not analysis.get("in_scope", True):
        st.caption(OUT_OF_SCOPE_NOTE_DE)
    elif analysis:
        st.caption(analysis_caption(analysis))
    if d.get("injection_suspected"):
        st.caption(INJECTION_NOTE_DE)
    if m.get("finish_reason") == "aborted":
        st.caption("Antwort abgebrochen – Text unvollständig.")
    elif m.get("finish_reason") == "length":
        st.caption("Antwort vom Modell gekürzt (max_tokens).")
    if show_diagnostics and m.get("diagnostics"):
        with st.expander("Diagnostik"):
            render_diagnostics(m["diagnostics"], m.get("question_rewritten"))


def render_diagnostics(d: dict[str, Any], rewritten: str | None) -> None:
    mode = d.get("mode")
    st.markdown(
        f"**Modus** {mode} ({MODE_LABEL_DE.get(mode, mode)}) · **Profil** {d.get('profile', 'strict')} · **Modell** {d.get('model') or '–'} · **Modell aufgerufen** {d.get('llm_called')} · "
        f"**schwache Evidenz** {d.get('weak_evidence')}" + (f" ({d.get('weak_evidence_reason')})" if d.get("weak_evidence_reason") else "")
        + (f" · **Evidenz bewertet (Guardrail aus)** {'schwach' if d.get('assessed_weak') else 'stark'}" + (f" ({d.get('assessed_reason')})" if d.get("assessed_reason") else "") if d.get("guardrail_enabled") is False else "")
        + (" · **Folgefrage ohne neue Evidenz** True" if d.get("weak_follow_up") else "")
        + (" · **Antwort gekürzt (max_tokens)**" if d.get("finish_reason") == "length" else "")
    )
    if d.get("analysis") or d.get("material_chars") or d.get("injection_suspected") or d.get("history_turns_used"):
        bits = []
        if d.get("material_chars"):
            bits.append(f"**Material** {d['material_chars']} Zeichen" + (" (gekürzt)" if d.get("material_truncated") else ""))
        if d.get("history_turns_used"):
            bits.append(f"**Verlauf im Prompt** {d['history_turns_used']} Runden")
        if d.get("injection_suspected"):
            bits.append("**Anweisungs-Formulierungen** " + ", ".join(d["injection_suspected"]))
        if bits:
            st.markdown(" · ".join(bits))
        if d.get("analysis"):
            st.markdown("**Einordnung (Modell):**")
            st.code(d["analysis"].get("raw") or "", language="text")
    if rewritten or d.get("rewritten_question"):
        st.markdown(f"**Umformulierte Frage:** {rewritten or d.get('rewritten_question')}")
    if d.get("doc_ids"):
        st.markdown(f"**Handbuch-Filter:** {', '.join(d['doc_ids'])}")
    ids = d.get("identifiers") or []
    labels = d.get("resolved_labels") or []
    partial = d.get("partial_labels") or []
    if ids or labels or partial:
        st.markdown(
            f"**Identifier** {', '.join(ids) or '–'} · **Labels** {', '.join(labels) or '–'}"
            + (f" · **Teiltreffer** {', '.join(partial)}" if partial else "")
        )
    chans = d.get("channels") or []
    if chans:
        st.table(
            [
                {"Kanal": c.get("channel"), "angefragt": c.get("requested_k"), "Treffer": c.get("returned"), "ms": c.get("took_ms")}
                for c in chans
            ]
        )
    timings = d.get("timings_ms") or {}
    if timings:
        st.markdown("**Zeiten (ms):** " + " · ".join(f"{k} {v}" for k, v in timings.items()))
    st.markdown(f"**Prompt:** {d.get('prompt_chars', 0)} Zeichen")
    facts = d.get("facts") or []
    if facts:
        st.markdown(f"**Fakten ({len(facts)})**")
        for f in facts:
            text = f.get("rendered") or f"{f.get('source_label')} —{f.get('relation')}→ {f.get('target_label')}"
            st.markdown(f"- :red[{text}]" if f.get("polarity") == "negative" else f"- {text}")
    ents = d.get("entities") or []
    if ents:
        st.markdown(f"**Entitäten ({len(ents)})**")
        for e in ents:
            st.markdown(f"- {e}")
    if d.get("warnings"):
        st.warning("\n".join(d["warnings"]))
    if d.get("error"):
        st.error(d["error"])
