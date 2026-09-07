"""OpenSearch request bodies for the four search channels and the two fetches, plus the thin calls that run them.

Every body excludes ``embedding`` and ``bboxes`` from ``_source`` (REPORT §7) and returns the full chunk record
otherwise (``text``, ``body_text``, ``node_ids``, ``edge_ids`` — which the ``osi`` smoke queries omit). Lucene kNN:
``k`` and ``size`` are both set; a document filter goes INSIDE the knn clause (filter-during-search)."""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .models import Channel

log = logging.getLogger(__name__)

EXCLUDE_FIELDS = ["embedding", "bboxes"]
BM25_FIELDS = ["text^2", "body_text", "caption"]
DOCUMENT_FIELDS = [
    "doc_id",
    "title",
    "version",
    "root_system",
    "embedding_model",
    "embedding_dim",
    "embedding_text_prefix",
    "counts",
    "name",
    "indexed_at",
]


def _doc_filter(doc_ids: Collection[str] | None) -> dict[str, Any] | None:
    if not doc_ids:
        return None
    return {"terms": {"doc_id": sorted(set(doc_ids))}}


def _wrap(query: dict[str, Any], k: int, doc_ids: Collection[str] | None) -> dict[str, Any]:
    flt = _doc_filter(doc_ids)
    if flt is not None:
        query = {"bool": {"must": [query], "filter": [flt]}}
    return {"size": k, "_source": {"excludes": EXCLUDE_FIELDS}, "query": query}


def knn_body(vector: Sequence[float], k: int, doc_ids: Collection[str] | None = None) -> dict[str, Any]:
    clause: dict[str, Any] = {"vector": list(vector), "k": k}
    flt = _doc_filter(doc_ids)
    if flt is not None:
        clause["filter"] = flt
    return {"size": k, "_source": {"excludes": EXCLUDE_FIELDS}, "query": {"knn": {"embedding": clause}}}


def bm25_body(text: str, k: int, doc_ids: Collection[str] | None = None) -> dict[str, Any]:
    return _wrap({"multi_match": {"query": text, "fields": BM25_FIELDS}}, k, doc_ids)


def identifier_body(identifiers: Sequence[str], k: int, doc_ids: Collection[str] | None = None) -> dict[str, Any]:
    should = [{"term": {"identifiers": i}} for i in identifiers]
    return _wrap({"bool": {"should": should, "minimum_should_match": 1}}, k, doc_ids)


def label_body(labels: Sequence[str], k: int, doc_ids: Collection[str] | None = None) -> dict[str, Any]:
    should = [{"term": {"node_labels": lbl}} for lbl in labels]
    return _wrap({"bool": {"should": should, "minimum_should_match": 1}}, k, doc_ids)


@dataclass
class ChannelResponse:
    channel: Channel
    hits: list[dict[str, Any]] = field(default_factory=list)  # raw hits: _id, _score, _source
    took_ms: int | None = None
    error: str | None = None


def run_channels(client: Any, index: str, bodies: Mapping[Channel, dict[str, Any]]) -> dict[Channel, ChannelResponse]:
    """All channels in one ``msearch``; a failing clause becomes an empty channel with ``error`` set."""
    if not bodies:
        return {}
    channels = list(bodies)
    body: list[dict[str, Any]] = []
    for ch in channels:
        body.append({"index": index})
        body.append(bodies[ch])
    res = client.msearch(body=body)
    out: dict[Channel, ChannelResponse] = {}
    for ch, item in zip(channels, res.get("responses", []), strict=True):
        if "error" in item:
            err = item["error"]
            reason = err.get("reason") if isinstance(err, dict) else str(err)
            log.warning("channel %s failed: %s", ch, reason)
            out[ch] = ChannelResponse(channel=ch, error=str(reason)[:300])
            continue
        out[ch] = ChannelResponse(channel=ch, hits=list(item.get("hits", {}).get("hits", [])), took_ms=item.get("took"))
    return out


def fetch_chunks(client: Any, index: str, chunk_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """``mget`` by chunk id (``_id == chunk_id``); missing ids are skipped."""
    if not chunk_ids:
        return {}
    res = client.mget(body={"ids": list(chunk_ids)}, index=index, _source_excludes=",".join(EXCLUDE_FIELDS))
    out: dict[str, dict[str, Any]] = {}
    for d in res.get("docs", []):
        if d.get("found") and "_source" in d:
            out[d["_id"]] = d["_source"]
    return out


def fetch_documents(client: Any, index: str, *, include_graph: bool) -> list[dict[str, Any]]:
    """The ``bhb-documents`` records: metadata (title, embedding model/prefix) and, on request, the graph blobs."""
    source: dict[str, Any] = {"includes": DOCUMENT_FIELDS + (["graph"] if include_graph else [])}
    res = client.search(index=index, body={"size": 200, "_source": source, "query": {"match_all": {}}})
    return [h["_source"] for h in res["hits"]["hits"]]
