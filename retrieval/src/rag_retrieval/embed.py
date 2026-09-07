"""The question embedding: one ``POST /embeddings`` with the configured model and query prefix, dimension-checked.

The model must be the one that produced ``chunk.embedding`` (``bhb-documents.embedding_model``): bge-m3 locally with
no prefix, ``intfloat/multilingual-e5-large`` with ``query: `` on the server (its passages carry ``passage: ``)."""

from __future__ import annotations

from typing import Any

import httpx

from .llm_http import LLMClient, LLMHTTPError
from .settings import EmbeddingSettings


class EmbeddingError(RuntimeError):
    pass


class QuestionEmbedder:
    def __init__(self, client: LLMClient, *, model: str, dim: int, query_prefix: str = ""):
        self.client = client
        self.model = model
        self.dim = dim
        self.query_prefix = query_prefix

    @classmethod
    def from_settings(cls, s: EmbeddingSettings, *, transport: httpx.BaseTransport | None = None) -> QuestionEmbedder:
        client = LLMClient(s.base_url, s.api_key, s.timeout_s, max_attempts=s.max_attempts, transport=transport)
        return cls(client, model=s.model, dim=s.dim, query_prefix=s.query_prefix)

    def embed(self, text: str) -> list[float]:
        resp = self.client.post_json("/embeddings", {"model": self.model, "input": [self.query_prefix + text]})
        data = resp.get("data") or []
        if len(data) != 1:
            raise EmbeddingError(f"expected 1 embedding, got {len(data)}")
        vec = data[0].get("embedding")
        if not isinstance(vec, list):
            raise EmbeddingError("embedding response without a vector")
        if len(vec) != self.dim:
            raise EmbeddingError(f"embedding dim {len(vec)} != configured {self.dim} (RAG__EMBEDDING__DIM)")
        return [float(x) for x in vec]

    def probe(self) -> dict[str, Any]:
        """Embed one short string; reports reachability, dimension and the error text if any."""
        try:
            vec = self.embed("Test")
            return {"ok": True, "model": self.model, "dim": len(vec)}
        except (EmbeddingError, LLMHTTPError) as exc:
            return {"ok": False, "model": self.model, "error": str(exc)[:300]}
