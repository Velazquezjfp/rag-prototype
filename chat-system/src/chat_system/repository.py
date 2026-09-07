"""Persistence: conversations/messages scoped by user, and the usage counter that implements ``rag_users.UsageStore``.

One short session per call; returned rows are detached and stay readable (``expire_on_commit=False``). User scoping
IS the authorisation: ``get_conversation(id, user_id)`` returns ``None`` for somebody else's conversation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import case, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .db import utcnow
from .models import Conversation, Message, Usage

log = logging.getLogger(__name__)

TITLE_MAX = 80


class UsageRepo:
    """``rag_users.UsageStore`` on the ``usage(user_id, day, count)`` table (SPEC §10.2)."""

    def __init__(self, session_factory: sessionmaker[Session], *, clock: Callable[[], datetime] = utcnow) -> None:
        self._sf = session_factory
        self._clock = clock

    def count(self, user_id: str, day: date) -> int:
        with self._sf() as s:
            return s.scalar(select(Usage.count).where(Usage.user_id == user_id, Usage.day == day)) or 0

    def increment(self, user_id: str, day: date, by: int = 1) -> int:
        with self._sf() as s, s.begin():
            return self.increment_in(s, user_id, day, by)

    def increment_in(self, s: Session, user_id: str, day: date, by: int = 1) -> int:
        """Portable upsert inside an open session: UPDATE; rowcount 0 -> INSERT; IntegrityError (a concurrent
        INSERT won) -> UPDATE again. The count never goes below zero (refunds after errors)."""
        now = self._clock()
        new_count = Usage.count + by
        upd = (  # CASE, not max(a, b): that is an aggregate on Postgres and a scalar only on SQLite
            update(Usage)
            .where(Usage.user_id == user_id, Usage.day == day)
            .values(count=case((new_count < 0, 0), else_=new_count), updated_at=now)
        )
        if s.execute(upd).rowcount == 0:
            try:
                with s.begin_nested():
                    s.execute(insert(Usage).values(user_id=user_id, day=day, count=max(by, 0), updated_at=now))
            except IntegrityError:
                s.execute(upd)
        return s.scalar(select(Usage.count).where(Usage.user_id == user_id, Usage.day == day)) or 0


class Repository:
    def __init__(self, session_factory: sessionmaker[Session], *, clock: Callable[[], datetime] = utcnow) -> None:
        self._sf = session_factory
        self._clock = clock
        self._usage = UsageRepo(session_factory, clock=clock)

    def usage(self) -> UsageRepo:
        return self._usage

    # ---------------------------------------------------------------- conversations

    def create_conversation(self, user_id: str, *, use_graph: bool, doc_ids: Sequence[str] | None) -> Conversation:
        now = self._clock()
        conv = Conversation(
            user_id=user_id,
            use_graph_default=use_graph,
            doc_ids=list(doc_ids) if doc_ids else None,
            turn_count=0,
            status="open",
            created_at=now,
            updated_at=now,
        )
        with self._sf() as s, s.begin():
            s.add(conv)
        return conv

    def get_conversation(self, conversation_id: str, user_id: str) -> Conversation | None:
        with self._sf() as s:
            return s.scalar(
                select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            )

    def list_conversations(self, user_id: str, *, limit: int = 20) -> list[Conversation]:
        with self._sf() as s:
            rows = s.scalars(
                select(Conversation)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
                .limit(limit)
            )
            return list(rows)

    def mark_capped(self, conversation_id: str) -> None:
        with self._sf() as s, s.begin():
            s.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(status="capped", updated_at=self._clock())
            )

    # -------------------------------------------------------------------- messages

    def list_messages(self, conversation_id: str) -> list[Message]:
        with self._sf() as s:
            rows = s.scalars(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
            )
            return list(rows)

    def add_user_message(self, conversation_id: str, content: str) -> Message:
        with self._sf() as s, s.begin():
            return self._add_user_message(s, conversation_id, content)

    def begin_turn(self, conversation_id: str, content: str, *, user_id: str, day: date) -> tuple[Message, int]:
        """One transaction: reserve the usage slot AND store the user's message (SPEC §10.2 — the cap lives in the
        backend; a second browser tab sees the same counter). Returns the message and the new daily count."""
        with self._sf() as s, s.begin():
            used = self._usage.increment_in(s, user_id, day, 1)
            msg = self._add_user_message(s, conversation_id, content)
        return msg, used

    def _add_user_message(self, s: Session, conversation_id: str, content: str) -> Message:
        conv = s.get(Conversation, conversation_id)
        if conv is None:
            raise LookupError(f"conversation {conversation_id} not found")
        seq = self._next_seq(s, conversation_id)
        now = self._clock()
        msg = Message(conversation_id=conversation_id, seq=seq, role="user", content=content, created_at=now)
        s.add(msg)
        conv.turn_count = (conv.turn_count or 0) + 1
        conv.updated_at = now
        if not conv.title:
            conv.title = _title_from(content)
        s.flush()
        return msg

    def add_assistant_message(
        self,
        conversation_id: str,
        content: str,
        *,
        question_rewritten: str | None,
        use_graph: bool | None,
        citations: list[dict[str, Any]] | None,
        diagnostics: dict[str, Any] | None,
        guardrail: bool,
        finish_reason: str | None,
        model: str | None,
        latency_ms: int | None,
    ) -> Message:
        with self._sf() as s, s.begin():
            now = self._clock()
            msg = Message(
                conversation_id=conversation_id,
                seq=self._next_seq(s, conversation_id),
                role="assistant",
                content=content,
                question_rewritten=question_rewritten,
                use_graph=use_graph,
                citations=citations,
                diagnostics=diagnostics,
                guardrail=guardrail,
                finish_reason=finish_reason,
                model=model,
                latency_ms=latency_ms,
                created_at=now,
            )
            s.add(msg)
            s.execute(update(Conversation).where(Conversation.id == conversation_id).values(updated_at=now))
            s.flush()
        return msg

    @staticmethod
    def _next_seq(s: Session, conversation_id: str) -> int:
        return (s.scalar(select(func.max(Message.seq)).where(Message.conversation_id == conversation_id)) or 0) + 1


def _title_from(content: str) -> str:
    one_line = " ".join(content.split())
    return one_line if len(one_line) <= TITLE_MAX else one_line[: TITLE_MAX - 1] + "…"
