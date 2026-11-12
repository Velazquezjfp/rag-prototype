"""Fakes for the ingest API: docling-graph-service as an httpx.MockTransport, OpenSearch as a mapping-only stub.
The saved response of a real run (``out/remote-zsd``, bge-m3, 1024 dimensions) is what the fake service returns."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from opensearchpy.exceptions import NotFoundError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingest_service import core  # noqa: E402
from ingest_service.api import create_app  # noqa: E402
from ingest_service.settings import Settings  # noqa: E402

ONTOLOGY = ROOT / "user-manual-books" / "handbuch_daten" / "Ontologie" / "ontology.yaml"
RESPONSE = ROOT / "out" / "remote-zsd" / "response.json"
KEY = "test-key-0123456789"
AUTH = {"X-API-Key": KEY}
PDF = ("Betriebshandbuch_ZSD.pdf", b"%PDF-1.7 fake", "application/pdf")


@pytest.fixture(scope="session")
def saved_response() -> dict[str, Any]:
    return json.loads(RESPONSE.read_text(encoding="utf-8"))


class FakeIndices:
    def __init__(self, known: dict[str, tuple[str | None, int]]):
        self.known = known

    def get_mapping(self, index: str) -> dict[str, Any]:
        prefix = index.removesuffix("-chunks")
        if prefix not in self.known:
            raise NotFoundError(404, "index_not_found_exception", {"error": index})
        model, dim = self.known[prefix]
        meta = {"mapping_version": 1, "embedding_dim": dim, **({"embedding_model": model} if model else {})}
        return {f"{index}-v1": {"mappings": {"_meta": meta, "properties": {"embedding": {"type": "knn_vector", "dimension": dim}}}}}


class FakeOpenSearch:
    def __init__(self, known: dict[str, tuple[str | None, int]] | None = None):
        self.indices = FakeIndices(known if known is not None else {"bhb": ("bge-m3", 1024)})


class FakeDgs:
    """Answers /v1/capabilities and /v1/process; ``process`` is a list of (status, body) served in order (last repeats)."""

    def __init__(self, response: dict[str, Any], *, model: str = "bge-m3", dim: int = 1024, enabled: bool = True):
        self.embedding = {"model": model, "dim": dim, "text_prefix": "", "enabled": enabled, "base_url": "http://emb"}
        self.process: list[tuple[int, Any]] = [(200, response)]
        self.calls: list[dict[str, Any]] = []
        self.hook = None  # called inside /v1/process (e.g. to block until a test releases it)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json={"models": {"llm": {"model": "llm-x", "enabled": True}, "embedding": self.embedding},
                                             "features": {"ocr": False}, "limits": {"max_upload_mb": 50}})
        if request.url.path == "/v1/process":
            self.calls.append(json.loads(request.content))
            if self.hook is not None:
                self.hook()
            status, body = self.process[min(len(self.calls) - 1, len(self.process) - 1)]
            headers = {"Retry-After": "7"} if status == 503 else {}
            return httpx.Response(status, json=body, headers=headers)
        return httpx.Response(404, json={"detail": "not found"})


@pytest.fixture
def dgs(saved_response) -> FakeDgs:
    return FakeDgs(saved_response)


@pytest.fixture
def indexed(monkeypatch) -> list[dict[str, Any]]:
    """Replace the real indexer by a recorder (the real one runs in test_integration.py)."""
    calls: list[dict[str, Any]] = []

    def fake(client, osi, ontology, resp_json, **kw):
        calls.append({"ontology": ontology, "chunks": len(resp_json["chunks"]), **kw})
        return {"status": "dry-run" if kw.get("dry_run") else "active", "plan": {"doc_id": kw.get("doc_id") or "BHB-PLT-0007"},
                "counts": {"chunks": len(resp_json["chunks"])}, "swept": {}, "duration_s": 0.1, "error": None, "warnings": []}

    monkeypatch.setattr(core, "index_response", fake)
    return calls


def make_client(dgs: FakeDgs, *, os_client: Any | None = None, sleeps: list[float] | None = None, **settings: Any) -> TestClient:
    s = Settings(_env_file=None, api_key=KEY, ontologies={"bhb": str(ONTOLOGY)}, **settings)
    app = create_app(s, os_client=os_client or FakeOpenSearch(), dgs_transport=httpx.MockTransport(dgs),
                     sleep=(sleeps.append if sleeps is not None else (lambda _: None)))
    return TestClient(app)


@pytest.fixture
def client(dgs, indexed) -> TestClient:
    return make_client(dgs)
