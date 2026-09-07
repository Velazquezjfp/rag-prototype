"""Configuration: ``config.yaml`` defaults, overridable per key via ``RAG__SECTION__KEY`` env vars.

Precedence (highest first): environment, ``.env`` file, ``config.yaml``, model defaults. The YAML path comes from
``RAG_CONFIG`` (default: the ``config.yaml`` shipped in this module folder). Unlike ``osi``, ``./config.yaml`` in the
working directory is deliberately NOT consulted: chat-system runs from its own folder with its own ``config.yaml``
and feeds this module through ``RAG__*`` keys in its ``.env``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from opensearch_index.settings import OpenSearchSettings
from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _PACKAGE_DIR.parent.parent / "config.yaml"

__all__ = [
    "EmbeddingSettings",
    "GuardrailSettings",
    "IndexSettings",
    "LLMSettings",
    "OntologySettings",
    "OpenSearchSettings",
    "RetrievalSettings",
    "Settings",
    "config_path",
    "get_settings",
]


class IndexSettings(BaseModel):
    prefix: str = "bhb"


class EmbeddingSettings(BaseModel):
    """Query-side embeddings; model and prefix must match what produced ``chunk.embedding``."""

    base_url: str = "http://localhost:4000/v1"
    api_key: str | None = None
    model: str = "bge-m3"
    dim: int = 1024
    query_prefix: str = ""
    timeout_s: float = 30.0
    max_attempts: int = 3


class LLMSettings(BaseModel):
    """The answering model (OpenAI-compatible chat completions); also used for question rewriting."""

    base_url: str = "http://localhost:4000/v1"
    api_key: str | None = None
    model: str = "gemini-dev"
    temperature: float = 0.0
    max_tokens: int = 4000  # reasoning models count their thinking against this (gemini: ~1300 tokens)
    timeout_s: float = 120.0
    max_attempts: int = 2
    context_limit_tokens: int = 32000


class RetrievalSettings(BaseModel):
    k_per_channel: int = 20
    final_k: int = 10
    rrf_rank_constant: int = 60
    graph_seed_hits: int = 5
    graph_seed_per_channel: int = 2
    graph_max_start_nodes: int = 30
    graph_max_facts: int = 40
    graph_max_chunks: int = 15
    graph_min_sources: int = 2
    graph_max_entities: int = 15
    label_max_ngram: int = 4
    label_min_chars: int = 3
    partial_label_min_tokens: int = 2
    partial_label_max_nodes: int = 8
    context_token_budget: int = 6000
    max_facts_in_prompt: int = 25


class GuardrailSettings(BaseModel):
    enabled: bool = True
    min_agreeing_channels: int = 2
    top_n: int = 3


class OntologySettings(BaseModel):
    path: str = "../user-manual-books/handbuch_daten/Ontologie/ontology.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAG__",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    opensearch: OpenSearchSettings = Field(default_factory=OpenSearchSettings)
    index: IndexSettings = Field(default_factory=IndexSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    guardrail: GuardrailSettings = Field(default_factory=GuardrailSettings)
    ontology: OntologySettings = Field(default_factory=OntologySettings)

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
    """Resolve the YAML config file: ``RAG_CONFIG`` > the copy shipped in the module folder (never ``./config.yaml``)."""
    explicit = os.environ.get("RAG_CONFIG")
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise FileNotFoundError(f"RAG_CONFIG points to a missing file: {p}")
        return p
    return _DEFAULT_CONFIG if _DEFAULT_CONFIG.is_file() else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def redact_url(base_url: str, api_key: str | None) -> dict[str, str]:
    return {"base_url": base_url, "api_key": "***" if api_key else "(none)"}
