"""Engine, sessions, schema: SQLite for one process, Postgres for the enterprise profile — same code path.

SQLite gets WAL + a busy timeout (Streamlit calls from several threads) and ``check_same_thread=False``; datetimes
are stored as UTC and come back timezone-aware on both dialects (``TZDateTime``). ``ensure_schema`` runs the Alembic
migrations shipped inside the package (``chat_system/migrations``) against the given engine.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

__all__ = [
    "MIGRATIONS_DIR",
    "TZDateTime",
    "alembic_config",
    "current_revision",
    "ensure_schema",
    "head_revision",
    "make_engine",
    "make_session_factory",
    "utcnow",
]


def utcnow() -> datetime:
    return datetime.now(UTC)


class TZDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetimes on every dialect: bound as UTC, returned with ``tzinfo=UTC``.

    SQLite has no timestamp type and drops offsets, so the value is stored naive-in-UTC and re-tagged on the way out;
    Postgres ``timestamptz`` round-trips the offset and is normalised to UTC for equality across dialects.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; use chat_system.db.utcnow()")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def make_engine(url: str, *, echo: bool = False) -> Engine:
    """SQLite: parent directory created, WAL, busy_timeout 5 s, foreign keys on, shared across threads."""
    u = make_url(url)
    kwargs: dict[str, Any] = {"echo": echo, "future": True}
    if u.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
        if u.database in (None, "", ":memory:"):
            kwargs["poolclass"] = StaticPool
        else:
            Path(u.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    else:
        kwargs["pool_pre_ping"] = True
    engine = create_engine(url, **kwargs)
    if u.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA foreign_keys=ON")
            if u.database not in (None, "", ":memory:"):
                cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Sessions whose objects stay readable after commit (the UI renders detached rows)."""
    return sessionmaker(engine, expire_on_commit=False)


def alembic_config(url: str | None = None) -> Any:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def head_revision() -> str | None:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    from alembic.runtime.migration import MigrationContext

    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def ensure_schema(engine: Engine) -> str | None:
    """``alembic upgrade head`` on this engine (shares the connection, so in-memory SQLite works too)."""
    from alembic import command

    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    rev = current_revision(engine)
    log.info("schema at revision %s", rev)
    return rev
