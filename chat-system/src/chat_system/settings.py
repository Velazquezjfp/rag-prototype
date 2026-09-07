"""Configuration: ``config.yaml`` defaults, overridable per key via ``CHAT__SECTION__KEY`` env vars.

Precedence (highest first): environment, ``.env`` file, ``config.yaml``, model defaults. The YAML path comes from
``CHAT_CONFIG`` (default: ``./config.yaml`` in the working directory, falling back to the copy shipped in this module
folder) — the full osi chain, unlike ``rag_retrieval`` which deliberately skips ``./config.yaml``. The LLM is NOT
configured here: it lives once, in ``RAG__LLM__*`` (rag-retrieval's settings), and the user policy in ``USERS__*``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _PACKAGE_DIR.parent.parent / "config.yaml"

__all__ = ["DbSettings", "LimitsSettings", "RetrievalSettings", "Settings", "UiSettings", "config_path", "get_settings"]


class DbSettings(BaseModel):
    """SQLAlchemy URL. SQLite file by default; ``postgresql+psycopg://…`` for the Postgres profile (ADR-0007)."""

    url: str = "sqlite:///./data/chat.db"
    echo: bool = False
    auto_upgrade: bool = True  # alembic upgrade head at startup


class RetrievalSettings(BaseModel):
    """How the chat calls rag-retrieval; the retrieval internals stay in RAG__RETRIEVAL__*."""

    k: int = 8  # chunks in fast mode
    k_graph: int = 12  # chunks in slow (graph) mode
    history_turns_for_rewrite: int = 2  # SPEC §8
    use_graph_default: bool = True


class LimitsSettings(BaseModel):
    max_concurrent_answers: int = 10  # in-process semaphore; per-user caps come from rag_users.Policy


class UiSettings(BaseModel):
    title: str = "Betriebshandbuch-Assistent"
    allow_user_switch: bool = False  # the sidebar user selectbox ("simulated ingress"); true on the dev box only
    show_diagnostics_default: bool = False
    conversation_list_limit: int = 20


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHAT__",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db: DbSettings = Field(default_factory=DbSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)
    ui: UiSettings = Field(default_factory=UiSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_path = config_path()
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings, dotenv_settings]
        if yaml_path is not None:
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=yaml_path))
        return tuple(sources)


def config_path() -> Path | None:
    """Resolve the YAML config file: ``CHAT_CONFIG`` > ``./config.yaml`` > packaged default."""
    explicit = os.environ.get("CHAT_CONFIG")
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise FileNotFoundError(f"CHAT_CONFIG points to a missing file: {p}")
        return p
    for candidate in (Path.cwd() / "config.yaml", _DEFAULT_CONFIG):
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def redact_db_url(url: str) -> str:
    """``postgresql+psycopg://chat:secret@host/db`` -> ``postgresql+psycopg://chat:***@host/db``."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        creds, host = rest.rsplit("@", 1)
        if ":" in creds:
            creds = creds.split(":", 1)[0] + ":***"
        return f"{scheme}://{creds}@{host}"
    return url
