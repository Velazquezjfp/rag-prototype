"""Entry point of the Streamlit app (``streamlit run app.py`` at the module root calls ``main()``)."""

from __future__ import annotations

import streamlit as st
from rag_users import get_settings as users_settings

from .. import wiring
from ..settings import get_settings
from . import auth, chat, sidebar

SERVICE_FACTORY = wiring.build_service  # tests replace this with a factory returning a fake-backed service


@st.cache_resource(show_spinner="Verbinde mit Suche, Graph und Sprachmodell …")
def get_service():
    """One ChatService per process: DB engine + schema, the union graph, the HTTP clients (SPEC: no per-request state)."""
    return SERVICE_FACTORY(get_settings())


def main() -> None:
    settings = get_settings()
    st.set_page_config(page_title=settings.ui.title, page_icon="📘", layout="wide")
    st.title(settings.ui.title)
    svc = get_service()
    ctx = auth.resolve(settings, users_settings())
    state = sidebar.render(svc, ctx, settings)
    chat.render(svc, ctx, settings, state)
