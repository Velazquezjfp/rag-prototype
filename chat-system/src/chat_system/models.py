"""SQLAlchemy 2.x models: conversations, messages, usage (SPEC §10.2 ``usage(user_id, day, count)``).

Portable across SQLite and Postgres (ADR-0007's leak list avoided): app-generated uuid4 ids, JSON columns (JSONB on
Postgres), timezone-aware datetimes through ``TZDateTime``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .db import TZDateTime, utcnow

JSONType = JSON().with_variant(postgresql.JSONB(), "postgresql")


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    use_graph_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    doc_ids: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open | capped
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, default=utcnow)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,  # ON DELETE CASCADE does the work (SQLite: PRAGMA foreign_keys=ON in make_engine)
        order_by="Message.seq",
        lazy="noload",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"Conversation({self.id!r}, user={self.user_id!r}, turns={self.turn_count}, status={self.status!r})"


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    question_rewritten: Mapped[str | None] = mapped_column(Text)  # assistant rows: the standalone form (ADR-0011)
    use_graph: Mapped[bool | None] = mapped_column(Boolean)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType, nullable=True)
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    guardrail: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    finish_reason: Mapped[str | None] = mapped_column(String(16))  # stop | length | aborted | error | guardrail
    model: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages", lazy="noload")

    def __repr__(self) -> str:  # pragma: no cover
        return f"Message({self.id}, conv={self.conversation_id!r}, seq={self.seq}, role={self.role!r})"


class Usage(Base):
    __tablename__ = "usage"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, default=utcnow)
