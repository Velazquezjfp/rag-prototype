"""End-to-end against a running OpenSearch (compose node): OSI_INTEGRATION=1 OSI_INTEGRATION_URL=http://localhost:9200.
Uses the prefix ``bhbtest`` with 8-dim fixture vectors and removes everything it created."""

import copy
import json
import os

import pytest
from conftest import FIXTURE, ONTOLOGY_PATH
from opensearchpy import NotFoundError

from opensearch_index import search as sq
from opensearch_index.client import cluster_info, make_client, verify_knn_roundtrip
from opensearch_index.indexer import Indexer
from opensearch_index.schemas import ProcessResponse
from opensearch_index.settings import Settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("OSI_INTEGRATION") != "1", reason="set OSI_INTEGRATION=1"),
]
URL = os.environ.get("OSI_INTEGRATION_URL", "http://localhost:9200")
PREFIX = "bhbtest"


def _cleanup(client, names):
    for row in client.cat.indices(index=f"{names.prefix}-*", format="json"):
        client.indices.delete(index=row["index"], ignore=[404])
    try:
        client.transport.perform_request("DELETE", f"/_search/pipeline/{names.rrf_pipeline}")
    except NotFoundError:
        pass


@pytest.fixture(scope="module")
def env(ontology):
    s = Settings(
        _env_file=None,
        opensearch={"url": URL},
        index={"prefix": PREFIX},
        embedding={"model": "test-8d", "dim": 8},
        ontology={"path": str(ONTOLOGY_PATH)},
    )
    client = make_client(s.opensearch)
    ix = Indexer(client, s, ontology, owner="pytest")
    _cleanup(client, ix.names)
    yield s, client, ix
    _cleanup(client, ix.names)


@pytest.fixture(scope="module")
def resp():
    return ProcessResponse.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_verify_gate(env):
    s, client, ix = env
    info = cluster_info(client)
    assert info.has_knn, info.plugins
    out = verify_knn_roundtrip(client, dim=8, names=ix.names)
    assert out["hit"] == "v0"


def test_bootstrap_idempotent(env):
    _, client, ix = env
    first = ix.bootstrap()
    assert len(first["created"]) == 4
    second = ix.bootstrap()
    assert second["created"] == [] and len(second["existing"]) == 4
    ix.check_indices()
    if cluster_info(client).supports_rrf:
        assert first["pipeline"] == f"{PREFIX}-rrf"


def test_ingest_then_noop(env, resp):
    _, client, ix = env
    plan = ix.plan(resp)
    report = ix.ingest(plan, resp)
    assert report.status == "active" and report.counts["chunks"] == 12
    assert client.count(index=ix.names.chunks)["count"] == 12
    assert client.count(index=ix.names.nodes)["count"] == report.counts["nodes"]
    again = ix.plan(resp)
    assert again.action == "noop"
    assert ix.ingest(again, resp).status == "noop"


def test_new_extraction_sweeps_stale(env, resp):
    _, client, ix = env
    other = copy.deepcopy(resp)
    dropped = other.chunks.pop()
    other.graph.nodes[0].label += " (neu)"
    report = ix.ingest(ix.plan(other), other)
    assert report.status == "active" and report.swept["chunks"] == 1
    assert client.count(index=ix.names.chunks)["count"] == 11
    with pytest.raises(NotFoundError):
        client.get(index=ix.names.chunks, id=dropped.chunk_id)
    m = client.get(index=ix.names.manifest, id="BHB-PLT-0007")["_source"]
    assert m["status"] == "active" and len(m["history"]) == 1
    # restore the full fixture for the query tests
    ix.ingest(ix.plan(resp), resp)
    assert client.count(index=ix.names.chunks)["count"] == 12


def test_knn_self_hit(env):
    _, client, ix = env
    vec = sq.stored_vector(client, ix.names, "2bb722f565a0-0002")
    assert len(vec) == 8
    hits = sq.knn(client, ix.names, vec, k=3)
    assert hits[0]["_id"] == "2bb722f565a0-0002"
    assert hits[0]["score"] > 0.99


def test_identifier_terms(env):
    _, client, ix = env
    hits = sq.by_identifiers(client, ix.names, ["BHB-PLT-0007"])
    assert "2bb722f565a0-0002" in {h["_id"] for h in hits}


def test_bm25_german(env):
    _, client, ix = env
    hits = sq.bm25(client, ix.names, "Sicherheitsdienste Vault")
    assert hits and hits[0]["doc_id"] == "BHB-PLT-0007"


def test_node_labels_case_insensitive(env):
    _, client, ix = env
    res = client.search(
        index=ix.names.chunks,
        body={"query": {"terms": {"node_labels": ["betriebshandbuch zsd - zentrale sicherheitsdienste"]}}, "_source": False},
    )
    assert "2bb722f565a0-0007" in {h["_id"] for h in res["hits"]["hits"]}


def test_flat_object_term_on_attributes(env):
    _, client, ix = env
    res = client.search(index=ix.names.nodes, body={"query": {"term": {"attributes.doc_id": "BHB-PLT-0007"}}})
    ids = {h["_source"]["node_id"] for h in res["hits"]["hits"]}
    assert "Document_ddfceb8b3907ff3e" in ids


def test_node_lookup_with_edges(env):
    _, client, ix = env
    out = sq.node_lookup(client, ix.names, "Document_ddfceb8b3907ff3e")
    assert out["documents"] == ["BHB-PLT-0007"]
    assert any(e["type"] == "DOCUMENTS" for e in out["edges"])


def test_hybrid_rrf(env):
    _, client, ix = env
    if not cluster_info(client).supports_rrf:
        pytest.skip("server < 2.19: no score-ranker-processor")
    vec = sq.stored_vector(client, ix.names, "2bb722f565a0-0002")
    hits = sq.hybrid_rrf(client, ix.names, text="Zentrale Sicherheitsdienste", vector=vec, identifiers=["BHB-PLT-0007"], k=5)
    assert hits and hits[0]["_id"] == "2bb722f565a0-0002"


def test_delete(env):
    _, client, ix = env
    out = ix.delete_document("BHB-PLT-0007")
    assert out["chunks"] == 12 and out["manifest"] == 1
    assert client.count(index=ix.names.chunks)["count"] == 0
    with pytest.raises(NotFoundError):
        client.get(index=ix.names.manifest, id="BHB-PLT-0007")
