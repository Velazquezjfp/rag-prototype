"""The ingest API with fakes: the key, the ontology rule, the target index, the embedding check, the service call."""

from __future__ import annotations

import threading

import pytest
from conftest import AUTH, KEY, ONTOLOGY, PDF, FakeDgs, FakeOpenSearch, make_client

from ingest_service.api import create_app
from ingest_service.settings import Settings


def post(client, *, files=None, headers=AUTH, **data):
    return client.post("/v1/ingest", files={"pdf": PDF, **(files or {})}, data={k: str(v) for k, v in data.items()}, headers=headers)


# ------------------------------------------------------------------------------------------------- key


def test_service_does_not_start_without_an_api_key():
    with pytest.raises(RuntimeError, match="INGEST__API_KEY"):
        create_app(Settings(_env_file=None, api_key="  "))


def test_healthz_is_open_everything_else_needs_the_key(client):
    assert client.get("/healthz").json() == {"status": "ok", "busy": False}
    for call in (lambda h: client.get("/v1/info", headers=h), lambda h: client.get("/v1/jobs", headers=h),
                 lambda h: post(client, headers=h, ontology="bhb")):
        assert call({}).status_code == 401
        assert call({"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/v1/jobs", headers=AUTH).json() == []
    assert client.get("/v1/jobs", headers={"Authorization": f"Bearer {KEY}"}).status_code == 200


# -------------------------------------------------------------------------------------------- ontology


def test_no_ontology_is_refused_with_the_available_names(client, dgs):
    r = post(client)
    assert r.status_code == 400 and "no ontology" in r.json()["detail"] and "available: bhb" in r.json()["detail"]
    assert dgs.calls == [] and client.get("/v1/jobs", headers=AUTH).json() == []  # refused before any job


def test_named_and_uploaded_ontology_together_or_unknown_or_broken_are_refused(client, dgs):
    both = post(client, ontology="bhb", files={"ontology_file": ("o.yaml", ONTOLOGY.read_bytes(), "application/yaml")})
    assert both.status_code == 400 and "not both" in both.json()["detail"]
    unknown = post(client, ontology="vrf")
    assert unknown.status_code == 400 and "unknown ontology 'vrf'" in unknown.json()["detail"]
    broken = post(client, files={"ontology_file": ("o.yaml", b"classes: [unclosed", "application/yaml")})
    assert broken.status_code == 400 and "not usable" in broken.json()["detail"]
    empty = post(client, files={"ontology_file": ("o.yaml", b"meta: {name: x}\n", "application/yaml")})
    assert empty.status_code == 400 and "no classes" in empty.json()["detail"]
    assert dgs.calls == []


# ---------------------------------------------------------------------------------------- happy paths


def test_named_ontology_processes_and_indexes_and_echoes_the_parameters(client, dgs, indexed):
    r = post(client, ontology="bhb", ocr="true", doc_id="BHB-PLT-0007")
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["state"] == "done" and job["status"] == "active" and job["doc_id"] == "BHB-PLT-0007" and job["error"] is None
    p = job["parameters"]
    assert p["prefix"] == "bhb" and p["index"] == "bhb-chunks-v1"
    assert p["embedding"] == {"model": "bge-m3", "dim": 1024, "text_prefix": ""}
    assert p["ontology"]["source"] == "bhb" and len(p["ontology"]["fingerprint"]) == 12
    assert p["pipeline_config"] == {"ocr_enabled": True} and p["dry_run"] is False
    assert job["dgs"]["chunks"] == 112 and job["dgs"]["embedded"] == 112 and job["dgs"]["pages"] == 29
    sent = dgs.calls[0]  # the contract of docling-graph-service: document + pipeline_config + ontology_graph
    assert sent["document"]["name"] == "Betriebshandbuch_ZSD.pdf" and sent["document"]["format"] == "pdf"
    assert sent["pipeline_config"] == {"ocr_enabled": True} and "classes" in sent["ontology_graph"]
    assert indexed[0]["prefix"] == "bhb" and indexed[0]["doc_id"] == "BHB-PLT-0007" and indexed[0]["chunks"] == 112
    assert indexed[0]["embedding"]["model"] == "bge-m3" and indexed[0]["ontology"].documents  # the bhb document list
    assert client.get(f"/v1/jobs/{job['job_id']}", headers=AUTH).json() == job
    assert [j["job_id"] for j in client.get("/v1/jobs", headers=AUTH).json()] == [job["job_id"]]


def test_uploaded_ontology_and_defaults(client, dgs, indexed):
    r = post(client, files={"ontology_file": ("mine.yaml", ONTOLOGY.read_bytes(), "application/yaml")}, dry_run="true")
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "dry-run" and job["parameters"]["ontology"]["source"] == "upload"
    assert job["parameters"]["pipeline_config"] == "service defaults" and dgs.calls[0]["pipeline_config"] == {}
    assert indexed[0]["dry_run"] is True and indexed[0]["doc_id"] is None


# ------------------------------------------------------------------------------- index and embeddings


def test_unknown_prefix_is_refused_before_the_service_is_called(client, dgs, indexed):
    r = post(client, ontology="bhb", prefix="vrf")
    assert r.status_code == 404 and r.json()["state"] == "failed"
    assert "unknown index prefix 'vrf'" in r.json()["error"] and "osi bootstrap" in r.json()["error"]
    assert dgs.calls == [] and indexed == []
    bad = post(client, ontology="bhb", prefix="BHB;drop")
    assert bad.status_code == 400 and "invalid index prefix" in bad.json()["error"]


@pytest.mark.parametrize("kw,expected", [
    ({"model": "embeddinggemma:latest", "dim": 768}, "docling-graph-service produces embeddinggemma:latest (768 dimensions)"),
    ({"model": "other-1024", "dim": 1024}, "bhb-chunks holds bge-m3 (1024 dimensions)"),
    ({"enabled": False}, "embeddings are switched off"),
])
def test_embedding_mismatch_is_refused_before_any_processing(saved_response, indexed, kw, expected):
    dgs = FakeDgs(saved_response, **kw)
    r = post(make_client(dgs), ontology="bhb")
    assert r.status_code == 409 and expected in r.json()["error"] and "nothing was processed" in r.json()["error"]
    assert dgs.calls == [] and indexed == []


def test_an_index_without_a_model_label_is_checked_by_dimension_only(saved_response, indexed):
    dgs = FakeDgs(saved_response, model="whatever", dim=1024)
    assert post(make_client(dgs, os_client=FakeOpenSearch({"bhb": (None, 1024)})), ontology="bhb").status_code == 200


# ------------------------------------------------------------------------------ docling-graph-service


def test_busy_service_is_retried_with_its_retry_after(saved_response, indexed):
    dgs = FakeDgs(saved_response)
    dgs.process = [(503, {"detail": "busy"}), (503, {"detail": "busy"}), (200, saved_response)]
    sleeps: list[float] = []
    r = post(make_client(dgs, sleeps=sleeps), ontology="bhb")
    assert r.status_code == 200 and len(dgs.calls) == 3 and sleeps == [7.0, 7.0]


def test_service_errors_are_reported_and_recorded(saved_response, indexed):
    dgs = FakeDgs(saved_response)
    dgs.process = [(422, {"detail": "ontology_graph: classes missing"})]
    c = make_client(dgs)
    r = post(c, ontology="bhb")
    assert r.status_code == 422 and "classes missing" in r.json()["error"]  # the caller's input: status handed on
    dgs.process = [(500, {"detail": "docling conversion failure"})]
    r = post(c, ontology="bhb")
    assert r.status_code == 502 and "HTTP 500" in r.json()["error"] and indexed == []
    states = [(j["state"], j["finished_at"] is not None) for j in c.get("/v1/jobs", headers=AUTH).json()]
    assert states == [("failed", True), ("failed", True)]
    assert c.get("/healthz").json()["busy"] is False  # the slot is free again


def test_one_document_at_a_time(saved_response, indexed):
    dgs = FakeDgs(saved_response)
    entered, release = threading.Event(), threading.Event()
    dgs.hook = lambda: (entered.set(), release.wait(10))
    c = make_client(dgs)
    first: dict = {}
    t = threading.Thread(target=lambda: first.update(r=post(c, ontology="bhb")))
    t.start()
    assert entered.wait(10)
    second = post(c, ontology="bhb")
    assert second.status_code == 503 and second.headers["Retry-After"] == "30"
    assert c.get("/healthz").json()["busy"] is True
    running = c.get("/v1/jobs", headers=AUTH).json()
    assert len(running) == 1 and running[0]["state"] == "running" and running[0]["parameters"]["prefix"] == "bhb"
    release.set()
    t.join(10)
    assert first["r"].status_code == 200 and c.get("/healthz").json()["busy"] is False


# ------------------------------------------------------------------------------------------- uploads


def test_empty_and_oversized_documents_are_refused(dgs, indexed):
    c = make_client(dgs, max_upload_mb=1)
    empty = c.post("/v1/ingest", files={"pdf": ("a.pdf", b"", "application/pdf")}, data={"ontology": "bhb"}, headers=AUTH)
    assert empty.status_code == 400 and "empty" in empty.json()["detail"]
    big = c.post("/v1/ingest", files={"pdf": ("a.pdf", b"x" * (1024 * 1024 + 1), "application/pdf")}, data={"ontology": "bhb"}, headers=AUTH)
    assert big.status_code == 413 and dgs.calls == []


def test_info_shows_the_defaults_and_both_backends(client):
    info = client.get("/v1/info", headers=AUTH).json()
    assert info["defaults"]["prefix"] == "bhb" and info["defaults"]["ontologies"]["bhb"]["available"] is True
    assert info["opensearch"]["index"]["embedding_model"] == "bge-m3" and info["opensearch"]["index"]["embedding_dim"] == 1024
    assert info["dgs"]["embedding"] == {"model": "bge-m3", "dim": 1024, "text_prefix": "", "enabled": True}
    assert "base_url" not in str(info["dgs"]["models"])  # only model names and switches


def test_openapi_documents_the_call(client):
    spec = client.get("/openapi.json").json()
    props = spec["components"]["schemas"]["Body_ingest_v1_ingest_post"]["properties"]
    assert {"pdf", "ontology", "ontology_file", "prefix", "doc_id", "ocr", "vlm", "force", "replace", "dry_run"} <= set(props)
    assert client.get("/docs").status_code == 200
