import json

import pytest

from opensearch_index.loader import LoadError, load_run


def _write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_response_file(tmp_path, response_small):
    p = tmp_path / "response.json"
    _write(p, response_small.model_dump())
    assert load_run(p).document.sha256 == response_small.document.sha256


def test_directory_with_response(tmp_path, response_small):
    _write(tmp_path / "response.json", response_small.model_dump())
    (tmp_path / "document.json").write_text("{}")  # must be ignored
    assert len(load_run(tmp_path).chunks) == 12


def test_dgs_cli_layout(tmp_path, response_small):
    data = response_small.model_dump()
    meta = {k: data[k] for k in ("document", "degraded", "errors", "warnings", "timings_s", "versions", "cached")}
    meta["chunk_count"] = len(data["chunks"])
    _write(tmp_path / "meta.json", meta)
    _write(tmp_path / "chunks.json", data["chunks"])
    _write(tmp_path / "graph.json", data["graph"])
    (tmp_path / "markdown.md").write_text(data["markdown"], encoding="utf-8")
    resp = load_run(tmp_path)
    assert resp.document.sha256 == response_small.document.sha256
    assert len(resp.chunks) == 12
    assert len(resp.graph.edges) == len(response_small.graph.edges)
    assert resp.markdown == response_small.markdown


def test_dgs_cli_layout_without_graph(tmp_path, response_small):
    data = response_small.model_dump()
    _write(tmp_path / "meta.json", {"document": data["document"]})
    _write(tmp_path / "chunks.json", data["chunks"])
    resp = load_run(tmp_path)
    assert resp.graph is None and resp.markdown == ""


def test_unknown_layout(tmp_path):
    (tmp_path / "document.json").write_text("{}")
    with pytest.raises(LoadError, match="response.json"):
        load_run(tmp_path)
    with pytest.raises(LoadError):
        load_run(tmp_path / "missing")
