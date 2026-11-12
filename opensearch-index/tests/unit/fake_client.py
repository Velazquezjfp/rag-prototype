"""A small in-memory stand-in for the OpenSearch client: just enough of the API the Indexer uses
(indices, get/index with optimistic concurrency, term/match_all search with terms aggregations, count,
delete_by_query, cat.plugins, info, search pipelines) to test the ingest protocol without a cluster."""

from __future__ import annotations

import copy
from typing import Any

from opensearchpy import ConflictError, NotFoundError


def _not_found(index: str) -> NotFoundError:
    return NotFoundError(404, "index_not_found_exception", {"error": {"index": index}})


def _get_path(src: dict[str, Any], field: str) -> Any:
    cur: Any = src
    for part in field.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _matches(src: dict[str, Any], query: dict[str, Any]) -> bool:
    if "match_all" in query:
        return True
    if "term" in query:
        ((field, value),) = query["term"].items()
        if isinstance(value, dict):
            value = value["value"]
        got = _get_path(src, field)
        return value in got if isinstance(got, list) else got == value
    if "terms" in query:
        ((field, values),) = query["terms"].items()
        got = _get_path(src, field)
        gots = got if isinstance(got, list) else [got]
        return any(g in values for g in gots)
    if "bool" in query:
        b = query["bool"]
        for clause in b.get("filter", []) + b.get("must", []):
            if not _matches(src, clause):
                return False
        return all(not _matches(src, clause) for clause in b.get("must_not", []))
    raise NotImplementedError(f"fake client cannot evaluate {query}")


class _Indices:
    def __init__(self, store: FakeClient):
        self.s = store

    def exists(self, index: str) -> bool:
        return index in self.s._indices

    def exists_alias(self, name: str) -> bool:
        return name in self.s.aliases

    def put_alias(self, index: str, name: str) -> dict:
        self.s.aliases[name] = index
        return {"acknowledged": True}

    def create(self, index: str, body: dict) -> dict:
        self.s._indices[index] = copy.deepcopy(body)
        self.s.docs.setdefault(index, {})
        for alias in body.get("aliases", {}):
            self.s.aliases[alias] = index
        return {"acknowledged": True}

    def get_mapping(self, index: str) -> dict:
        phys = self.s.resolve(index)
        return {phys: {"mappings": self.s._indices[phys]["mappings"]}}

    def refresh(self, index: str) -> dict:
        for i in index.split(","):
            self.s.resolve(i)
        return {}

    def delete(self, index: str, ignore=None) -> dict:
        phys = self.s.aliases.pop(index, index)
        self.s._indices.pop(phys, None)
        self.s.docs.pop(phys, None)
        return {}


class _Cat:
    def plugins(self, format: str = "json"):
        return [{"component": "opensearch-knn"}, {"component": "opensearch-neural-search"}, {"component": "opensearch-security"}]


class _Transport:
    def __init__(self, store: FakeClient):
        self.s = store

    def perform_request(self, method: str, url: str, body=None, params=None):
        self.s.requests.append((method, url, body))
        if url.startswith("/_search/pipeline/"):
            self.s.pipelines[url.rsplit("/", 1)[1]] = body
        return {"acknowledged": True}


class FakeClient:
    def __init__(self, version: str = "3.8.0"):
        self.version = version
        self._indices: dict[str, dict] = {}  # physical name -> create body
        self.aliases: dict[str, str] = {}  # alias -> physical
        self.docs: dict[str, dict[str, dict]] = {}  # physical -> id -> {_source, _seq_no, _primary_term}
        self.pipelines: dict[str, dict] = {}
        self.requests: list = []
        self.seq = 0
        self.indices = _Indices(self)
        self.cat = _Cat()
        self.transport = _Transport(self)
        self.index_calls: list[tuple[str, str]] = []

    # ---- helpers
    def resolve(self, index: str) -> str:
        phys = self.aliases.get(index, index)
        if phys not in self._indices:
            raise _not_found(index)
        return phys

    def all_docs(self, index: str) -> list[dict]:
        return [d["_source"] for d in self.docs[self.resolve(index)].values()]

    # ---- document APIs
    def info(self) -> dict:
        return {"cluster_name": "fake", "version": {"number": self.version, "distribution": "opensearch"}}

    def get(self, index: str, id: str, **kw) -> dict:
        phys = self.resolve(index)
        doc = self.docs[phys].get(id)
        if doc is None:
            raise NotFoundError(404, "not_found", {"_index": phys, "_id": id, "found": False})
        return {"_index": phys, "_id": id, **copy.deepcopy(doc)}

    def index(self, index: str, id: str, body: dict, op_type: str | None = None, if_seq_no=None, if_primary_term=None, refresh=None) -> dict:
        phys = self.resolve(index)
        existing = self.docs[phys].get(id)
        if op_type == "create" and existing is not None:
            raise ConflictError(409, "version_conflict_engine_exception", {})
        if if_seq_no is not None and (existing is None or existing["_seq_no"] != if_seq_no):
            raise ConflictError(409, "version_conflict_engine_exception", {})
        self.seq += 1
        self.docs[phys][id] = {"_source": copy.deepcopy(body), "_seq_no": self.seq, "_primary_term": 1}
        self.index_calls.append((phys, id))
        return {"_index": phys, "_id": id, "_seq_no": self.seq, "_primary_term": 1, "result": "updated" if existing else "created"}

    def delete(self, index: str, id: str, refresh=None) -> dict:
        phys = self.resolve(index)
        if id not in self.docs[phys]:
            raise NotFoundError(404, "not_found", {})
        del self.docs[phys][id]
        return {"result": "deleted"}

    def search(self, index: str, body: dict, params=None) -> dict:
        phys = self.resolve(index)
        query = body.get("query", {"match_all": {}})
        hits = [{"_index": phys, "_id": i, "_score": 1.0, "_source": copy.deepcopy(d["_source"])} for i, d in self.docs[phys].items() if _matches(d["_source"], query)]
        out: dict[str, Any] = {"hits": {"total": {"value": len(hits)}, "hits": hits[: body.get("size", 10)]}}
        if "aggs" in body:
            out["aggregations"] = {}
            for name, spec in body["aggs"].items():
                terms = spec["terms"]
                counts: dict[Any, int] = {}
                for h in hits:
                    v = _get_path(h["_source"], terms["field"])
                    for x in v if isinstance(v, list) else [v]:
                        if x is not None:
                            counts[x] = counts.get(x, 0) + 1
                buckets = [{"key": k, "doc_count": n} for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]))) if n >= terms.get("min_doc_count", 1)]
                out["aggregations"][name] = {"buckets": buckets[: terms.get("size", 10)]}
        return out

    def count(self, index: str, body: dict | None = None) -> dict:
        phys = self.resolve(index)
        query = (body or {}).get("query", {"match_all": {}})
        return {"count": sum(1 for d in self.docs[phys].values() if _matches(d["_source"], query))}

    def delete_by_query(self, index: str, body: dict, conflicts=None, refresh=None) -> dict:
        phys = self.resolve(index)
        victims = [i for i, d in self.docs[phys].items() if _matches(d["_source"], body["query"])]
        for i in victims:
            del self.docs[phys][i]
        return {"deleted": len(victims), "version_conflicts": 0, "failures": []}


def fake_bulk(client: FakeClient, actions, **kwargs):
    """Stand-in for opensearchpy.helpers.bulk: index every action, report no errors."""
    n = 0
    for a in actions:
        client.index(index=a["_index"], id=a["_id"], body=a["_source"])
        n += 1
    return n, []
