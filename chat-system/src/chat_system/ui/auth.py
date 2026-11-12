"""Who is asking: the configured ``rag_users`` adapter. Local: the one mock user (``USERS__ADAPTER=env``). Remote:
the request headers of the authenticating proxy (``USERS__ADAPTER=header``; ``st.context.headers``, because
``st.user`` does not see proxy headers). A missing header stops the page - there is no fallback user."""

from __future__ import annotations

import streamlit as st
from rag_users import AuthContext, Unauthenticated, UsersSettings, get_adapter


def resolve(users_settings: UsersSettings) -> AuthContext:
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
