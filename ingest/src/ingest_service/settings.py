"""``INGEST__*`` settings of the API. The OpenSearch connection and the index defaults are the indexer's own
``OSI__*`` settings (``opensearch_index.settings.Settings``), so both services read one set of variables."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DgsSettings(BaseModel):
    """The docling-graph-service this API calls."""

    url: str = "http://localhost:8080"
    timeout_s: float = 3600.0  # HTTP read timeout and total wait while the service is busy (503); >= its deadline
    busy_retry_s: float = 30.0  # wait between retries when the 503 carries no Retry-After


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INGEST__",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = ""  # required: the service does not start without it
    dgs: DgsSettings = Field(default_factory=DgsSettings)
    # named ontologies a call may pick with ontology=<name>; JSON in the environment: {"bhb": "/ontology/ontology.yaml"}
    ontologies: dict[str, str] = Field(
        default_factory=lambda: {"bhb": "../user-manual-books/handbuch_daten/Ontologie/ontology.yaml"}
    )
    default_prefix: str = "bhb"
    max_upload_mb: int = 50  # the service's own limit; docling-graph-service also has one
    jobs_keep: int = 50  # finished jobs remembered in memory for GET /v1/jobs
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
