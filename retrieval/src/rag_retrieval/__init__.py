"""rag-retrieval: question → hybrid OpenSearch retrieval + 1-hop graph expansion → German prompt context → answer."""

from __future__ import annotations

from .chat import NO_EVIDENCE_ANSWER, ChatClient, TokenStream, answer, rewrite_question
from .models import (
    ChannelEvidence,
    ChannelStats,
    ChunkGroup,
    ChunkHit,
    Citation,
    Diagnostics,
    EntityCard,
    EntityOccurrence,
    GraphFact,
    Message,
    RenderedContext,
    RetrievalResult,
    RewriteResult,
)
from .prompt import (
    OVERVIEW_INSTRUCTION_DE,
    SYSTEM_PROMPT_DE,
    WEAK_FOLLOW_UP_NOTE_DE,
    build_messages,
    estimate_tokens,
    render_context,
    scope_line,
)
from .retriever import Retriever, default_retriever, retrieve
from .settings import Settings, get_settings

__all__ = [
    "NO_EVIDENCE_ANSWER",
    "OVERVIEW_INSTRUCTION_DE",
    "SYSTEM_PROMPT_DE",
    "WEAK_FOLLOW_UP_NOTE_DE",
    "ChannelEvidence",
    "ChannelStats",
    "ChatClient",
    "ChunkGroup",
    "ChunkHit",
    "Citation",
    "Diagnostics",
    "EntityCard",
    "EntityOccurrence",
    "GraphFact",
    "Message",
    "RenderedContext",
    "RetrievalResult",
    "Retriever",
    "RewriteResult",
    "Settings",
    "TokenStream",
    "answer",
    "build_messages",
    "default_retriever",
    "estimate_tokens",
    "get_settings",
    "render_context",
    "retrieve",
    "rewrite_question",
    "scope_line",
]
