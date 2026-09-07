"""Sidebar: identity and quota, new/resume conversation, graph toggle, manual filter, diagnostics switch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st
from rag_users import AuthContext

from ..catalog import label as doc_label
from ..models import Message
from ..service import ChatService, TurnRefused
from ..settings import Settings

NEW_LABEL = "— neues Gespräch —"


@dataclass
class SidebarState:
    conversation_id: str | None
    use_graph: bool
    doc_ids: list[str] | None
    show_diagnostics: bool


def message_to_display(m: Message) -> dict[str, Any]:
    return {
        "role": m.role,
        "content": m.content,
        "citations": m.citations or [],
        "diagnostics": m.diagnostics,
        "guardrail": bool(m.guardrail),
        "finish_reason": m.finish_reason,
        "question_rewritten": m.question_rewritten,
    }


def load_conversation(svc: ChatService, ctx: AuthContext, conversation_id: str | None, doc_options: list[str]) -> None:
    ss = st.session_state
    if conversation_id is None:
        ss.conversation_id = None
        ss.messages = []
        ss.capped = False
        return
    try:
        conv, rows = svc.resume(ctx, conversation_id)
    except TurnRefused as exc:
        st.sidebar.warning(exc.message_de)
        ss.conversation_id = None
        ss.messages = []
        ss.capped = False
        return
    ss.conversation_id = conv.id
    ss.messages = [message_to_display(m) for m in rows]
    ss.capped = conv.status == "capped"
    ss.use_graph = bool(conv.use_graph_default)
    ss.doc_ids_pick = [d for d in (conv.doc_ids or []) if d in doc_options]


def render(svc: ChatService, ctx: AuthContext, settings: Settings) -> SidebarState:
    ss = st.session_state
    ss.setdefault("conversation_id", None)
    ss.setdefault("messages", [])
    ss.setdefault("capped", False)
    docs = svc.documents(ctx)
    doc_options = [d["doc_id"] for d in docs]
    labels = {d["doc_id"]: doc_label(d) for d in docs}

    with st.sidebar:
        st.caption(f"**{ctx.user_id}** · {', '.join(ctx.groups) or '–'}")
        q = svc.quota(ctx)
        st.metric("Nachrichten heute", f"{q.used_today}/{q.daily_cap}", help=f"Tageslimit der Gruppe; max. {q.max_turns} Runden pro Gespräch")

        if st.button("Neues Gespräch", use_container_width=True):
            load_conversation(svc, ctx, None, doc_options)
            ss.conversation_pick = None

        convs = svc.list_conversations(ctx)
        titles = {c.id: f"{c.title or '(ohne Titel)'} · {c.updated_at:%d.%m. %H:%M}" for c in convs}
        options: list[str | None] = [None] + [c.id for c in convs]
        current = ss.conversation_id if ss.conversation_id in options else None
        if ss.get("conversation_pick", "∅") != current:
            ss.conversation_pick = current  # keep the widget in step with the state (new conversation, other user)
        picked = st.selectbox(
            "Gespräche",
            options,
            key="conversation_pick",
            format_func=lambda cid: NEW_LABEL if cid is None else titles.get(cid, cid),
        )
        if picked != current:
            load_conversation(svc, ctx, picked, doc_options)

        if "use_graph" not in ss:
            ss.use_graph = settings.retrieval.use_graph_default
        use_graph = st.toggle("Graph-Modus (langsam)", key="use_graph", help="1-Hop-Erweiterung über den Wissensgraphen: Fakten und Entitätskarten zusätzlich zu den Textstellen")

        if "doc_ids_pick" not in ss:
            ss.doc_ids_pick = []
        ss.doc_ids_pick = [d for d in ss.doc_ids_pick if d in doc_options]
        selected = st.multiselect(
            "Handbücher",
            doc_options,
            key="doc_ids_pick",
            format_func=lambda d: labels.get(d, d),
            help="leer = alle Handbücher, die die Gruppe lesen darf",
        )

        if "show_diagnostics" not in ss:
            ss.show_diagnostics = settings.ui.show_diagnostics_default
        show_diag = st.checkbox("Diagnostik anzeigen", key="show_diagnostics")

    return SidebarState(
        conversation_id=ss.conversation_id,
        use_graph=bool(use_graph),
        doc_ids=list(selected) or None,
        show_diagnostics=bool(show_diag),
    )
