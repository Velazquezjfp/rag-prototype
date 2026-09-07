"""The indexed manuals (``bhb-documents``): id, title, version, root system — what the sidebar's multiselect shows.

Cached for a few minutes: the list changes only when a manual is (re-)indexed.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

FIELDS = ["doc_id", "title", "version", "root_system", "pages", "counts", "indexed_at", "embedding_model"]


class Catalog:
    def __init__(self, client: Any, documents_index: str, *, ttl_s: float = 300.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._client = client
        self._index = documents_index
        self._ttl = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: list[dict[str, Any]] | None = None
        self._at = 0.0

    def list_documents(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._cached is not None and self._clock() - self._at < self._ttl:
                return list(self._cached)
        docs = self._fetch()
        with self._lock:
            self._cached, self._at = docs, self._clock()
        return list(docs)

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None

    def _fetch(self) -> list[dict[str, Any]]:
        resp = self._client.search(
            index=self._index,
            body={"query": {"match_all": {}}, "size": 500, "_source": {"includes": FIELDS}},
        )
        out: list[dict[str, Any]] = []
        for hit in (resp.get("hits") or {}).get("hits") or []:
            src = hit.get("_source") or {}
            if not src.get("doc_id"):
                continue
            out.append(
                {
                    "doc_id": src["doc_id"],
                    "title": src.get("title") or src["doc_id"],
                    "version": src.get("version"),
                    "root_system": src.get("root_system"),
                    "pages": src.get("pages"),
                    "counts": src.get("counts") or {},
                    "indexed_at": src.get("indexed_at"),
                    "embedding_model": src.get("embedding_model"),
                }
            )
        out.sort(key=lambda d: d["doc_id"])
        return out


def label(doc: dict[str, Any]) -> str:
    """``BHB-PLT-0007 · Betriebshandbuch ZSD (v2.3)``."""
    title = doc.get("title") or ""
    version = doc.get("version")
    base = f"{doc['doc_id']} · {title}" if title and title != doc["doc_id"] else doc["doc_id"]
    return f"{base} (v{version})" if version else base
