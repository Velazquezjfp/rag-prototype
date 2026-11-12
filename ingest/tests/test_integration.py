"""The real indexer against the OpenSearch on localhost:9200, with a throwaway index prefix. docling-graph-service
stays a fake that returns the saved ZSD response (bge-m3, 1024 dimensions). Gated by INGEST_INTEGRATION=1."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

if not os.environ.get("INGEST_INTEGRATION"):
    pytest.skip("set INGEST_INTEGRATION=1 (needs OpenSearch on localhost:9200)", allow_module_level=True)

import httpx  # noqa: E402
from conftest import AUTH, KEY, ONTOLOGY, PDF, FakeDgs  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from opensearch_index.client import make_client as make_os_client  # noqa: E402
from opensearch_index.indexer import Indexer  # noqa: E402
from opensearch_index.ontology import load_ontology  # noqa: E402
from opensearch_index.settings import Settings as OsiSettings  # noqa: E402

from ingest_service.api import create_app  # noqa: E402
from ingest_service.settings import Settings  # noqa: E402

PREFIX = "ingtest"


@pytest.fixture(scope="module")
def osi() -> OsiSettings:
    return OsiSettings(_env_file=None, opensearch={"url": os.environ.get("INGEST_TEST_OPENSEARCH", "http://localhost:9200")},
                       index={"prefix": PREFIX, "rrf_pipeline": False}, embedding={"model": "bge-m3", "dim": 1024})


@pytest.fixture(scope="module")
def os_client(osi):
    client = make_os_client(osi.opensearch)
    client.indices.delete(index=f"{PREFIX}-*", ignore_unavailable=True)
    Indexer(client, osi, load_ontology(ONTOLOGY)).bootstrap()  # the deliberate admin step
    yield client
    client.indices.delete(index=f"{PREFIX}-*", ignore_unavailable=True)


@pytest.fixture
def api(osi, os_client, saved_response):
    dgs = FakeDgs(saved_response)
    # the service's own default prefix stays bhb: the call names the test prefix
    app = create_app(Settings(_env_file=None, api_key=KEY, ontologies={"bhb": str(ONTOLOGY)}),
                     osi_settings=osi.model_copy(update={"index": osi.index.model_copy(update={"prefix": "bhb"})}),
                     os_client=os_client, dgs_transport=httpx.MockTransport(dgs))
    return TestClient(app), dgs


def ingest(client, **data):
    return client.post("/v1/ingest", files={"pdf": PDF}, data={"ontology": "bhb", "prefix": PREFIX, **data}, headers=AUTH)


def test_dry_run_writes_nothing_then_ingest_indexes_then_the_same_book_is_a_noop(api, os_client):
    client, dgs = api
    dry = ingest(client, dry_run="true")
    assert dry.status_code == 200 and dry.json()["status"] == "dry-run", dry.text
    assert os_client.count(index=f"{PREFIX}-chunks")["count"] == 0

    r = ingest(client)
    job = r.json()
    assert r.status_code == 200 and job["status"] == "active", r.text
    assert job["doc_id"] == "BHB-PLT-0007" and job["index"]["plan"]["doc_id_source"]  # found from the ontology's file list
    assert job["index"]["counts"]["chunks"] == 112 and job["index"]["counts"]["nodes"] == 250
    os_client.indices.refresh(index=f"{PREFIX}-*")
    assert os_client.count(index=f"{PREFIX}-chunks")["count"] == 112
    doc = os_client.search(index=f"{PREFIX}-documents", body={"query": {"match_all": {}}})["hits"]["hits"][0]["_source"]
    assert doc["doc_id"] == "BHB-PLT-0007" and doc["embedding_model"] == "bge-m3"  # labelled from what the service produced

    again = ingest(client)
    assert again.status_code == 200 and again.json()["status"] == "noop" and len(dgs.calls) == 3
    assert os_client.count(index=f"{PREFIX}-chunks")["count"] == 112


def test_a_prefix_without_indices_is_refused_and_nothing_is_created(api, os_client):
    client, dgs = api
    r = ingest(client, prefix="ingtest-missing")
    assert r.status_code == 404 and "does not exist" in r.json()["error"] and dgs.calls == []
    assert not os_client.indices.exists(index="ingtest-missing-chunks")


def test_the_index_refuses_vectors_of_another_model(osi, os_client, saved_response):
    dgs = FakeDgs(saved_response, model="embeddinggemma:latest", dim=768)
    app = create_app(Settings(_env_file=None, api_key=KEY, ontologies={"bhb": str(ONTOLOGY)}), osi_settings=osi,
                     os_client=os_client, dgs_transport=httpx.MockTransport(dgs))
    r = ingest(TestClient(app))
    assert r.status_code == 409 and "ingtest-chunks holds bge-m3 (1024 dimensions)" in r.json()["error"] and dgs.calls == []


def test_info_reads_the_real_index(api):
    client, _ = api
    info = client.get("/v1/info", headers=AUTH).json()
    assert info["opensearch"]["index"]["embedding_dim"] == 1024  # the local bhb-* indices
