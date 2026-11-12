"""OpenSearch client factory and cluster probes (the NEXT-STEPS Step-1 gate: k-NN really present)."""

from __future__ import annotations

import math
import random
import secrets
from dataclasses import dataclass
from typing import Any

from opensearchpy import OpenSearch

from .mappings import KNN_ENGINE, SPACE_TYPE, IndexNames
from .settings import OpenSearchSettings


def make_client(s: OpenSearchSettings) -> OpenSearch:
    """urllib3-based client: no proxy environment is consulted (a corporate proxy never sits between us and the node)."""
    kwargs: dict[str, Any] = {
        "hosts": [s.url],
        "timeout": s.timeout_s,
        "max_retries": s.max_retries,
        "retry_on_timeout": True,
    }
    if s.username:
        kwargs["http_auth"] = (s.username, s.password or "")
    if s.url.lower().startswith("https://"):
        kwargs.update(use_ssl=True, verify_certs=s.verify_certs, ssl_show_warn=s.verify_certs)
        if s.ca_certs:
            kwargs["ca_certs"] = s.ca_certs
    return OpenSearch(**kwargs)


@dataclass
class ClusterInfo:
    cluster_name: str
    version: str
    distribution: str
    plugins: list[str]

    @property
    def version_tuple(self) -> tuple[int, ...]:
        parts = []
        for p in self.version.split("."):
            digits = "".join(ch for ch in p if ch.isdigit())
            parts.append(int(digits) if digits else 0)
        return tuple(parts)

    @property
    def has_knn(self) -> bool:
        return "opensearch-knn" in self.plugins

    @property
    def has_neural_search(self) -> bool:
        return "opensearch-neural-search" in self.plugins

    @property
    def supports_rrf(self) -> bool:  # score-ranker-processor: 2.19+
        return self.version_tuple >= (2, 19)


def cluster_info(client: OpenSearch) -> ClusterInfo:
    root = client.info()
    plugins = client.cat.plugins(format="json")
    return ClusterInfo(
        cluster_name=root.get("cluster_name", "?"),
        version=root.get("version", {}).get("number", "?"),
        distribution=root.get("version", {}).get("distribution", "?"),
        plugins=sorted({p.get("component", "") for p in plugins}),
    )


def verify_knn_roundtrip(client: OpenSearch, *, dim: int, names: IndexNames, seed: int = 7) -> dict[str, Any]:
    """Create a temporary knn index with the production field definition, index 3 unit vectors, search for the
    first one with k=1 and expect it back. Always deletes the index."""
    index = names.verify_index(secrets.token_hex(4))
    rng = random.Random(seed)

    def unit() -> list[float]:
        v = [rng.uniform(-1, 1) for _ in range(dim)]
        n = math.sqrt(math.fsum(x * x for x in v))
        return [x / n for x in v]

    vectors = [unit() for _ in range(3)]
    body = {
        "settings": {"index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0}},
        "mappings": {
            "properties": {
                "embedding": {
                    "type": "knn_vector",
                    "dimension": dim,
                    "space_type": SPACE_TYPE,
                    "method": {"name": "hnsw", "engine": KNN_ENGINE, "parameters": {"m": 16, "ef_construction": 128}},
                }
            }
        },
    }
    client.indices.create(index=index, body=body)
    try:
        for i, v in enumerate(vectors):
            client.index(index=index, id=f"v{i}", body={"embedding": v})
        client.indices.refresh(index=index)
        res = client.search(
            index=index,
            body={"size": 1, "query": {"knn": {"embedding": {"vector": vectors[0], "k": 1}}}, "_source": False},
        )
        hits = res["hits"]["hits"]
        if not hits or hits[0]["_id"] != "v0":
            raise RuntimeError(f"knn round trip failed: expected v0, got {[h['_id'] for h in hits]}")
        return {"index": index, "dim": dim, "hit": hits[0]["_id"], "score": hits[0]["_score"]}
    finally:
        client.indices.delete(index=index, ignore=[404])
