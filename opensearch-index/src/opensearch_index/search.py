"""Smoke queries for verification (not the retrieval module): k-NN with a stored vector, BM25, identifier terms,
node lookup across documents, and the four-clause hybrid query through the RRF pipeline."""

from __future__ import annotations

from typing import Any

from opensearchpy import OpenSearch

from .mappings import IndexNames

_EXCLUDE = {"excludes": ["embedding", "bboxes"]}


def _hits(res: dict[str, Any], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for h in res["hits"]["hits"]:
        src = h.get("_source", {})
        row = {"_id": h["_id"], "score": h.get("_score")}
        for f in fields:
            if f in src:
                row[f] = src[f]
        out.append(row)
    return out


_CHUNK_FIELDS = ("chunk_id", "doc_id", "kind", "page_numbers", "caption", "heading_breadcrumb", "identifiers", "node_labels")


def stored_vector(client: OpenSearch, names: IndexNames, chunk_id: str) -> list[float]:
    doc = client.get(index=names.chunks, id=chunk_id, _source_includes=["embedding"])["_source"]
    if not doc.get("embedding"):
        raise ValueError(f"chunk {chunk_id} has no stored embedding")
    return doc["embedding"]


def knn(client: OpenSearch, names: IndexNames, vector: list[float], k: int = 10) -> list[dict[str, Any]]:
    res = client.search(
        index=names.chunks,
        body={"size": k, "_source": _EXCLUDE, "query": {"knn": {"embedding": {"vector": vector, "k": k}}}},
    )
    return _hits(res, _CHUNK_FIELDS)


def bm25(client: OpenSearch, names: IndexNames, text: str, k: int = 10) -> list[dict[str, Any]]:
    res = client.search(
        index=names.chunks,
        body={
            "size": k,
            "_source": _EXCLUDE,
            "query": {"multi_match": {"query": text, "fields": ["text^2", "body_text", "caption"]}},
        },
    )
    return _hits(res, _CHUNK_FIELDS)


def by_identifiers(client: OpenSearch, names: IndexNames, identifiers: list[str], k: int = 10) -> list[dict[str, Any]]:
    res = client.search(
        index=names.chunks,
        body={"size": k, "_source": _EXCLUDE, "query": {"terms": {"identifiers": identifiers}}},
    )
    return _hits(res, _CHUNK_FIELDS)


def node_lookup(client: OpenSearch, names: IndexNames, node_id: str) -> dict[str, Any]:
    """The node in every document that mentions it, plus its edges (from the stored graph blobs)."""
    res = client.search(
        index=names.nodes,
        body={"size": 50, "_source": {"excludes": ["provenance"]}, "query": {"term": {"node_id": node_id}}},
    )
    nodes = [h["_source"] for h in res["hits"]["hits"]]
    doc_ids = sorted({n["doc_id"] for n in nodes})
    edges: list[dict[str, Any]] = []
    for doc_id in doc_ids:
        doc = client.get(index=names.documents, id=doc_id, _source_includes=["graph"])["_source"]
        graph = doc.get("graph") or {}
        labels = {n["id"]: n["label"] for n in graph.get("nodes", [])}
        for e in graph.get("edges", []):
            if node_id in (e["source"], e["target"]):
                edges.append(
                    {
                        "doc_id": doc_id,
                        "id": e.get("id"),
                        "source": labels.get(e["source"], e["source"]),
                        "type": e["type"],
                        "target": labels.get(e["target"], e["target"]),
                        "polarity": e.get("polarity"),
                        "quote": e.get("quote"),
                    }
                )
    return {"node_id": node_id, "documents": doc_ids, "nodes": nodes, "edges": edges}


def hybrid_rrf(
    client: OpenSearch,
    names: IndexNames,
    *,
    text: str | None = None,
    vector: list[float] | None = None,
    identifiers: list[str] | None = None,
    labels: list[str] | None = None,
    k: int = 10,
) -> list[dict[str, Any]]:
    """SPEC §7.2: dense kNN + BM25 + identifier terms + node-label terms, fused with RRF by the search pipeline."""
    queries: list[dict[str, Any]] = []
    if vector is not None:
        queries.append({"knn": {"embedding": {"vector": vector, "k": k}}})
    if text:
        queries.append({"multi_match": {"query": text, "fields": ["text^2", "body_text", "caption"]}})
    if identifiers:
        queries.append({"terms": {"identifiers": identifiers}})
    if labels:
        queries.append({"terms": {"node_labels": labels}})
    if not queries:
        raise ValueError("hybrid query needs at least one clause")
    res = client.search(
        index=names.chunks,
        body={"size": k, "_source": _EXCLUDE, "query": {"hybrid": {"queries": queries}}},
        params={"search_pipeline": names.rrf_pipeline},
    )
    return _hits(res, _CHUNK_FIELDS)
