import json

import pytest
from conftest import FIXTURE
from fake_client import FakeClient, fake_bulk
from typer.testing import CliRunner

from opensearch_index import cli
from opensearch_index import indexer as ix_mod
from opensearch_index.indexer import Indexer

runner = CliRunner()


@pytest.fixture
def wired(monkeypatch, settings, ontology):
    client = FakeClient()
    monkeypatch.setattr(ix_mod.helpers, "bulk", fake_bulk)
    ix = Indexer(client, settings, ontology, owner="cli:1")
    monkeypatch.setattr(cli, "_ctx", lambda: (settings, client, ix))
    return client, ix


def test_help():
    res = runner.invoke(cli.app, ["--help"])
    assert res.exit_code == 0 and "ingest" in res.output


def test_dry_run_then_ingest_then_status(wired):
    client, ix = wired
    res = runner.invoke(cli.app, ["bootstrap"])
    assert res.exit_code == 0, res.output
    res = runner.invoke(cli.app, ["ingest", str(FIXTURE), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "dry-run" in res.output and "would sweep" in res.output
    assert client.count(ix.names.chunks)["count"] == 0
    res = runner.invoke(cli.app, ["ingest", str(FIXTURE), "--json"])
    assert res.exit_code == 0, res.output
    report = json.loads(res.output[res.output.index("{") :])
    assert report["status"] == "active" and report["counts"]["chunks"] == 12
    res = runner.invoke(cli.app, ["ingest", str(FIXTURE)])
    assert res.exit_code == 0 and "noop" in res.output
    res = runner.invoke(cli.app, ["status"])
    assert res.exit_code == 0 and "BHB-PLT-0007" in res.output
    res = runner.invoke(cli.app, ["search", "--node-id", "Document_ddfceb8b3907ff3e"])
    assert res.exit_code == 0 and "DOCUMENTS" in res.output
    res = runner.invoke(cli.app, ["delete", "--doc-id", "BHB-PLT-0007", "--yes"])
    assert res.exit_code == 0 and '"chunks": 12' in res.output


def test_missing_path_is_an_error(wired):
    runner.invoke(cli.app, ["bootstrap"])
    res = runner.invoke(cli.app, ["ingest", "/nonexistent/run"])
    assert res.exit_code == 1 and "error" in res.output
