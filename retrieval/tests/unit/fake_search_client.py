"""In-memory stand-in for the OpenSearch client: the subset the retriever uses — ``search`` (knn by cosine,
multi_match by token overlap, term/terms/bool/match_all/match_phrase), ``msearch``, ``mget``, ``get``, ``count``,
``indices.exists_alias`` — with ``_source`` includes/excludes and ``size``. Content comes from ``transform.build_batch``."""

from __future__ import annotations

import copy
import math
import re
from typing import Any

from opensearchpy import NotFoundError

_WORD = re.compile(r"\w+", re.UNICODE)


def _tokens(text: Any) -> set[str]:
    """Lowercase word tokens minus German stopwords (the real ``de_text`` analyzer drops them too)."""
    from rag_retrieval.query import STOPWORDS_DE

    if text is None:
        return set()
    if isinstance(text, list):
        return {t for x in text for t in _tokens(x)}
    return {t for t in _WORD.findall(str(text).lower()) if t not in STOPWORDS_DE}


def _get(src: dict[str, Any], field: str) -> Any:
    cur: Any = src
    for part in field.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _cosine(a: list[float], b: list[float]) -> float:
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(math.fsum(x * x for x in a))
    nb = math.sqrt(math.fsum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _score(src: dict[str, Any], query: dict[str, Any]) -> float | None:
    """Score of a document for a query clause, or ``None`` when it does not match."""
    if "match_all" in query:
        return 1.0
    if "knn" in query:
        ((field, spec),) = query["knn"].items()
        vec = _get(src, field)
        if not vec:
            return None
        flt = spec.get("filter")
        if flt is not None and _score(src, flt) is None:
            return None
        return (_cosine(vec, spec["vector"]) + 1) / 2
    if "multi_match" in query:
        q = _tokens(query["multi_match"]["query"])
        total = 0.0
        for f in query["multi_match"]["fields"]:
            name, _, boost = f.partition("^")
            overlap = len(q & _tokens(_get(src, name)))
            total += overlap * (float(boost) if boost else 1.0)
        return total if total > 0 else None
    if "match_phrase" in query:
        ((field, value),) = query["match_phrase"].items()
        text = _get(src, field)
        return 1.0 if text and str(value).lower() in str(text).lower() else None
    if "term" in query:
        ((field, value),) = query["term"].items()
        if isinstance(value, dict):
            value = value["value"]
        got = _get(src, field)
        if isinstance(got, list):
            return 1.0 if any(str(g).lower() == str(value).lower() for g in got) else None
        return 1.0 if got is not None and str(got).lower() == str(value).lower() else None
    if "terms" in query:
        ((field, values),) = query["terms"].items()
        got = _get(src, field)
        gots = got if isinstance(got, list) else [got]
        return 1.0 if any(g in values for g in gots) else None
    if "bool" in query:
        b = query["bool"]
        total = 0.0
        for clause in b.get("must", []):
            s = _score(src, clause)
            if s is None:
                return None
            total += s
        for clause in b.get("filter", []):
            if _score(src, clause) is None:
                return None
        for clause in b.get("must_not", []):
            if _score(src, clause) is not None:
                return None
        should = b.get("should", [])
        if should:
            matched = [s for s in (_score(src, c) for c in should) if s is not None]
            need = int(b.get("minimum_should_match", 1 if not b.get("must") and not b.get("filter") else 0))
            if len(matched) < need:
                return None
            total += sum(matched)
        return total if total > 0 else 1.0
    raise NotImplementedError(f"fake client cannot evaluate {query}")


def _project(src: dict[str, Any], spec: Any) -> dict[str, Any]:
    if spec is None or spec is True:
        return copy.deepcopy(src)
    if spec is False:
        return {}
    if isinstance(spec, list):
        return {k: copy.deepcopy(v) for k, v in src.items() if k in spec}
    includes = spec.get("includes")
    excludes = set(spec.get("excludes") or [])
    out = {k: copy.deepcopy(v) for k, v in src.items() if (includes is None or k in includes) and k not in excludes}
    return out


class _Indices:
    def __init__(self, store: FakeSearchClient):
        self.s = store

    def exists_alias(self, name: str, **kw) -> bool:
        return name in self.s.docs


class FakeSearchClient:
    def __init__(self, prefix: str = "bhb"):
        self.prefix = prefix
        self.docs: dict[str, dict[str, dict[str, Any]]] = {
            f"{prefix}-chunks": {},
            f"{prefix}-nodes": {},
            f"{prefix}-documents": {},
        }
        self.requests: list[tuple[str, str, Any]] = []
        self.indices = _Indices(self)
        self.fail_channels: set[str] = set()  # msearch bodies whose query contains this key fail

    # ---- loading
    def load_batch(self, batch) -> None:
        for c in batch.chunks:
            self.docs[f"{self.prefix}-chunks"][c["chunk_id"]] = copy.deepcopy(c)
        for n in batch.nodes:
            self.docs[f"{self.prefix}-nodes"][f"{batch.sha12}:{n['node_id']}"] = copy.deepcopy(n)
        self.docs[f"{self.prefix}-documents"][batch.doc_id] = copy.deepcopy(batch.document)

    def _index(self, index: str) -> dict[str, dict[str, Any]]:
        if index not in self.docs:
            raise NotFoundError(404, "index_not_found_exception", {"error": {"index": index}})
        return self.docs[index]

    # ---- APIs
    def search(self, index: str, body: dict[str, Any], params=None, **kw) -> dict[str, Any]:
        self.requests.append(("search", index, body))
        query = body.get("query", {"match_all": {}})
        scored = []
        for _id, src in self._index(index).items():
            s = _score(src, query)
            if s is not None:
                scored.append((s, _id, src))
        scored.sort(key=lambda t: (-t[0], t[1]))
        size = body.get("size", 10)
        hits = [
            {"_index": index, "_id": _id, "_score": s, "_source": _project(src, body.get("_source"))}
            for s, _id, src in scored[:size]
        ]
        return {"took": 1, "hits": {"total": {"value": len(scored)}, "hits": hits}}

    def msearch(self, body: list[dict[str, Any]], **kw) -> dict[str, Any]:
        self.requests.append(("msearch", "", body))
        responses = []
        for i in range(0, len(body), 2):
            header, q = body[i], body[i + 1]
            if any(key in str(q) for key in self.fail_channels):
                responses.append({"error": {"type": "search_phase_execution_exception", "reason": "boom"}, "status": 400})
                continue
            responses.append(self.search(header["index"], q))
        return {"took": 1, "responses": responses}

    def mget(self, body: dict[str, Any], index: str, _source_excludes: str | None = None, **kw) -> dict[str, Any]:
        self.requests.append(("mget", index, body))
        excludes = [x for x in (_source_excludes or "").split(",") if x]
        docs = []
        store = self._index(index)
        for _id in body.get("ids", []):
            src = store.get(_id)
            if src is None:
                docs.append({"_index": index, "_id": _id, "found": False})
            else:
                docs.append({"_index": index, "_id": _id, "found": True, "_source": _project(src, {"excludes": excludes})})
        return {"docs": docs}

    def get(self, index: str, id: str, _source_includes=None, **kw) -> dict[str, Any]:
        src = self._index(index).get(id)
        if src is None:
            raise NotFoundError(404, "not_found", {"_index": index, "_id": id, "found": False})
        spec = _source_includes.split(",") if isinstance(_source_includes, str) else _source_includes
        return {"_index": index, "_id": id, "found": True, "_source": _project(src, spec)}

    def count(self, index: str, body: dict[str, Any] | None = None, **kw) -> dict[str, Any]:
        query = (body or {}).get("query", {"match_all": {}})
        return {"count": sum(1 for src in self._index(index).values() if _score(src, query) is not None)}


class FakeEmbedder:
    """Returns one fixed vector (e.g. the stored vector of a fixture chunk, so kNN ranks that chunk first)."""

    def __init__(self, vector: list[float], *, model: str = "test-8d", fail: Exception | None = None):
        self.vector = vector
        self.model = model
        self.dim = len(vector)
        self.query_prefix = ""
        self.fail = fail
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if self.fail is not None:
            raise self.fail
        return list(self.vector)

    def probe(self) -> dict[str, Any]:
        return {"ok": self.fail is None, "model": self.model, "dim": self.dim}


class FakeLLM:
    """Duck-typed ChatClient: canned completions, streamed as tokens; records every call."""

    def __init__(self, reply: str = "Antwort [BHB-PLT-0007 S. 1].", *, fail: Exception | None = None):
        self.reply = reply
        self.fail = fail
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages, *, model=None, max_tokens=None, temperature=None) -> str:
        self.calls.append([dict(m) for m in messages])
        if self.fail is not None:
            raise self.fail
        return self.reply

    def stream(self, messages, *, model=None, max_tokens=None, temperature=None):
        self.calls.append([dict(m) for m in messages])
        if self.fail is not None:
            raise self.fail
        for tok in self.reply.split(" "):
            yield tok + " "

    def probe(self) -> str:
        return "ok" if self.fail is None else "unreachable: fake"

    def close(self) -> None:
        pass
