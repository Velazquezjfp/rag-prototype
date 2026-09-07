from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from chat_system.db import (
    alembic_config,
    current_revision,
    ensure_schema,
    head_revision,
    make_engine,
)
from chat_system.models import Base


def test_upgrade_head_matches_the_models(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    assert current_revision(engine) is None
    rev = ensure_schema(engine)
    assert rev == head_revision() == "0001"
    assert set(inspect(engine).get_table_names()) >= {"conversations", "messages", "usage", "alembic_version"}
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "render_as_batch": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == [], diff
    assert ensure_schema(engine) == "0001"  # idempotent


def test_downgrade_to_base_drops_everything(tmp_path):
    url = f"sqlite:///{tmp_path / 'down.db'}"
    engine = make_engine(url)
    ensure_schema(engine)
    command.downgrade(alembic_config(url), "base")
    assert set(inspect(engine).get_table_names()) - {"alembic_version"} == set()


def test_sqlite_pragmas_and_wal(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'sub' / 'wal.db'}")  # parent dir is created
    with engine.connect() as conn:
        from sqlalchemy import text

        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000
