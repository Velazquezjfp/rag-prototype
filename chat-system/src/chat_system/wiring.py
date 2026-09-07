"""Build the real ``ChatService``: DB engine + schema, rag-retrieval ``Retriever``/``ChatClient``, rag-users ``Policy``.

Imports of the heavy neighbours are lazy so unit tests (which inject fakes) never touch OpenSearch or the LLM.
"""

from __future__ import annotations

import logging
from typing import Any

from .db import ensure_schema, make_engine, make_session_factory
from .repository import Repository
from .service import ChatService
from .settings import Settings, get_settings

log = logging.getLogger(__name__)


def rag_settings() -> Any:
    from rag_retrieval import get_settings as rag_get_settings

    return rag_get_settings()


def build_engine(settings: Settings | None = None) -> Any:
    settings = settings or get_settings()
    engine = make_engine(settings.db.url, echo=settings.db.echo)
    if settings.db.auto_upgrade:
        ensure_schema(engine)
    return engine


def build_service(settings: Settings | None = None, *, engine: Any | None = None) -> ChatService:
    from rag_retrieval import ChatClient, Retriever
    from rag_users import Policy

    from .catalog import Catalog

    settings = settings or get_settings()
    rag = rag_settings()
    engine = engine if engine is not None else build_engine(settings)
    repo = Repository(make_session_factory(engine))
    retriever = Retriever(rag)
    llm = ChatClient(rag.llm)
    catalog = Catalog(retriever.client, retriever.names.documents)
    log.info(
        "chat-system wired: db=%s, opensearch=%s, llm=%s/%s",
        settings.db.url.split("@")[-1],
        rag.opensearch.url,
        rag.llm.base_url,
        rag.llm.model,
    )
    return ChatService(
        repo, Policy(), retriever, llm, settings, rag_settings=rag, catalog=catalog.list_documents
    )
