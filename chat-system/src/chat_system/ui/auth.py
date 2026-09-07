"""Who is asking: the sidebar user switch on the dev box (the "simulated ingress" of ADR-0008) or the configured
``rag_users`` adapter over the request headers (``st.context.headers``; ``st.user`` does not see proxy headers)."""

from __future__ import annotations

import streamlit as st
from rag_users import USERS, AuthContext, Unauthenticated, UsersSettings, get_adapter

from ..settings import Settings


def resolve(settings: Settings, users_settings: UsersSettings) -> AuthContext:
    if settings.ui.allow_user_switch and users_settings.adapter == "env":
        ids = list(USERS)
        default = ids.index(users_settings.dev_user) if users_settings.dev_user in ids else 0
        if "user_switch" not in st.session_state:
            st.session_state.user_switch = ids[default]
        uid = st.sidebar.selectbox(
            "Benutzer (simulierter Ingress)",
            ids,
            key="user_switch",
            format_func=lambda u: f"{u} · {', '.join(USERS[u].groups)}",
        )
        ctx = USERS[uid]
    else:
        try:
            ctx = get_adapter(users_settings, headers=st.context.headers).current()
        except Unauthenticated as exc:
            st.error(f"Nicht angemeldet: {exc}")
            st.stop()
    if st.session_state.get("user_id") != ctx.user_id:
        # a different person: forget the other user's conversation
        st.session_state.user_id = ctx.user_id
        st.session_state.conversation_id = None
        st.session_state.messages = []
        st.session_state.capped = False
        st.session_state.pop("conversation_pick", None)
    return ctx
