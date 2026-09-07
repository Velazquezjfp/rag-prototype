"""Essential tests for process_and_index.py, written before the script (next session makes them green).
No services needed: docling-graph is a httpx MockTransport, the indexer is a stub."""

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
FIXTURE = HERE.parent / "opensearch-index" / "tests" / "data" / "response_small.json"

pai = pytest.importorskip("process_and_index", reason="integration/process_and_index.py not implemented yet")


@pytest.fixture
def response_small():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_process_one_retries_on_503_then_returns_json(tmp_path, response_small):
    pdf = tmp_path / "Betriebshandbuch_ZSD.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": "0"}, json={"detail": "busy"})
        body = json.loads(request.content)
        assert body["document"]["name"] == "Betriebshandbuch_ZSD.pdf"
        assert base64.b64decode(body["document"]["base64_content"]) == b"%PDF-1.4 fake"
        assert body["pipeline_config"] == {"vlm_enabled": False}
        return httpx.Response(200, json=response_small)

    async def go():
        async with httpx.AsyncClient(base_url="http://dgs", transport=httpx.MockTransport(handler)) as client:
            return await pai.process_one(client, pdf, {"vlm_enabled": False}, None, deadline_s=30)

    resp = asyncio.run(go())
    assert resp["document"]["sha256"] == response_small["document"]["sha256"]
    assert len(calls) == 2


def test_process_one_fails_on_other_errors(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"x")

    async def go():
        transport = httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))
        async with httpx.AsyncClient(base_url="http://dgs", transport=transport) as client:
            await pai.process_one(client, pdf, {}, None, deadline_s=30)

    with pytest.raises(pai.ProcessError):
        asyncio.run(go())


def test_write_run_dir_has_the_process_via_api_layout(tmp_path, response_small):
    out = pai.write_run_dir(response_small, tmp_path / "run")
    assert sorted(p.name for p in out.iterdir()) == ["chunks.json", "graph.json", "markdown.md", "response.json", "summary.json"]
    summary = json.loads((out / "summary.json").read_text())
    assert summary["chunks"] == 12 and summary["nodes"] == 59 and summary["edges"] == 11
    assert json.loads((out / "response.json").read_text())["document"]["sha256"] == response_small["document"]["sha256"]


def test_run_pipelines_books_and_never_overlaps_dgs_calls(tmp_path, response_small, monkeypatch):
    pdfs = []
    for i in range(2):
        p = tmp_path / f"book{i}.pdf"
        p.write_bytes(f"%PDF fake {i}".encode())
        pdfs.append(p)
    in_flight = {"now": 0, "max": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        in_flight["now"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["now"])
        await asyncio.sleep(0.05)
        in_flight["now"] -= 1
        return httpx.Response(200, json=response_small)

    indexed = []
    monkeypatch.setattr(pai, "index_run", lambda out_dir, flags: indexed.append(out_dir) or {"status": "active"})

    cfg = pai.RunConfig(
        dgs_url="http://dgs", out_root=tmp_path / "out", run_suffix="test", options={}, ontology=None,
        concurrency=1, timeout_s=30, skip_existing=False, index=pai.IndexFlags(),
    )
    results = asyncio.run(pai.run(pdfs, cfg, transport=httpx.MockTransport(handler)))
    assert in_flight["max"] == 1
    assert [r.status for r in results] == ["active", "active"]
    assert sorted(p.name for p in indexed) == ["book0-test", "book1-test"]
    assert (tmp_path / "out" / "book0-test" / "response.json").is_file()
