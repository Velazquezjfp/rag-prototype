"""Configuration: ``config.yaml`` defaults, overridable per key via ``OSI__SECTION__KEY`` env vars.

Precedence (highest first): environment, ``.env`` file, ``config.yaml``, model defaults.
The YAML path comes from ``OSI_CONFIG`` (default: ``config.yaml`` in the working directory,
falling back to the copy shipped next to this package). Same pattern as docling-graph-service.
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


class OpenSearchSettings(BaseModel):
    """Cluster endpoint. ``https://`` in the URL enables TLS; a username enables basic auth."""

    url: str = "http://localhost:9200"
    username: str | None = None
    password: str | None = None
    verify_certs: bool = True
    ca_certs: str | None = None
    timeout_s: float = 60.0
    max_retries: int = 3


class IndexSettings(BaseModel):
    prefix: str = "bhb"
    shards: int = 1
    replicas: int = 0
    knn_m: int = 16
    knn_ef_construction: int = 128
    rrf_pipeline: bool = True
    rrf_rank_constant: int = 60


class EmbeddingSettings(BaseModel):
    """What produced ``chunk.embedding`` in the ingested runs (the response does not name its model)."""

    model: str = "bge-m3"
    dim: int = 1024
    text_prefix: str = ""


class OntologySettings(BaseModel):
    path: str = "../user-manual-books/handbuch_daten/Ontologie/ontology.yaml"


class IngestSettings(BaseModel):
    bulk_size: int = 200
    lock_ttl_s: int = 3600
    request_timeout_s: float = 120.0
    history_keep: int = 20


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OSI__",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    opensearch: OpenSearchSettings = Field(default_factory=OpenSearchSettings)
    index: IndexSettings = Field(default_factory=IndexSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    ontology: OntologySettings = Field(default_factory=OntologySettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)

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
    """Resolve the YAML config file: ``OSI_CONFIG`` > ``./config.yaml`` > packaged default."""
    explicit = os.environ.get("OSI_CONFIG")
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise FileNotFoundError(f"OSI_CONFIG points to a missing file: {p}")
        return p
    for candidate in (Path.cwd() / "config.yaml", _DEFAULT_CONFIG):
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def redact(s: OpenSearchSettings) -> dict[str, str]:
    """Endpoint description safe for logs and ``osi status``."""
    return {"url": s.url, "username": s.username or "(none)", "password": "***" if s.password else "(none)"}
