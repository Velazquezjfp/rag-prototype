import json

import pytest
from fake_search_client import FakeEmbedder, FakeLLM
from typer.testing import CliRunner

from rag_retrieval import cli
from rag_retrieval.retriever import Retriever

runner = CliRunner()
CHUNK_TABLE1 = "2bb722f565a0-0009"


@pytest.fixture
def wired(monkeypatch, settings, fake_client, graph_small, ontology, small_batch):
    vec = next(c["embedding"] for c in small_batch.chunks if c["chunk_id"] == CHUNK_TABLE1)
    r = Retriever(settings, client=fake_client, embedder=FakeEmbedder(vec), graph=graph_small, ontology=ontology, relation_labels={"RELATED_DOCUMENT": "verwandtes Dokument"})
    llm = FakeLLM("Die Änderungshistorie steht in Tabelle 1 [BHB-PLT-0007 S. 4].")
    monkeypatch.setattr(cli, "_retriever", lambda: r)
    monkeypatch.setattr(cli, "_llm", lambda settings: llm)
    return r, llm


def test_help():
    res = runner.invoke(cli.app, ["--help"])
    assert res.exit_code == 0 and "ask" in res.output and "graph-stats" in res.output


def test_ask_fast_prints_hits_and_channels(wired):
    res = runner.invoke(cli.app, ["ask", "Änderungshistorie Version 2.3", "--no-graph"])
    assert res.exit_code == 0, res.output
    assert "Modus: fast" in res.output and "Guardrail: ok" in res.output
    assert "BHB-PLT-0007 S. 4" in res.output and "knn#1" in res.output and "Tabelle 1: Änderungshistorie" in res.output


def test_ask_json(wired):
    res = runner.invoke(cli.app, ["ask", "Was war bei ZSDSUP-0247?", "--no-graph", "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["mode"] == "fast" and data["diagnostics"]["identifiers"] == ["ZSDSUP-0247"] and data["chunks"]


def test_ask_slow_with_context_and_answer(wired):
    _, llm = wired
    res = runner.invoke(cli.app, ["ask", "Welche Dokumente sind verwandt?", "--show-context", "--answer"])
    assert res.exit_code == 0, res.output
    assert "Fakten (" in res.output and "----- Kontext" in res.output and "## Quellen" in res.output
    assert "Antwort (fake-llm):" in res.output and "Tabelle 1" in res.output
    assert llm.calls and llm.calls[0][0]["role"] == "system"


def test_ask_answer_streaming_and_history(wired, tmp_path):
    _, llm = wired
    hist = tmp_path / "h.json"
    hist.write_text(json.dumps([{"role": "user", "content": "Wer ist zuständig?"}, {"role": "assistant", "content": "X."}]), encoding="utf-8")
    llm.reply = "Änderungshistorie Version 2.3"  # the rewrite result (first call) doubles as the canned answer
    res = runner.invoke(cli.app, ["ask", "und die Historie?", "--no-graph", "--answer", "--stream", "--history-file", str(hist)])
    assert res.exit_code == 0, res.output
    assert "Umformuliert: Änderungshistorie Version 2.3" in res.output
    assert len(llm.calls) == 2  # rewrite + answer


def test_ask_guardrail_exit_code_2(wired):
    _, llm = wired
    res = runner.invoke(cli.app, ["ask", "Wie backe ich einen Apfelkuchen?", "--answer"])
    assert res.exit_code == 2, res.output
    assert "SCHWACHE EVIDENZ" in res.output and "Dazu steht nichts in den Handbüchern." in res.output
    assert llm.calls == []
    forced = runner.invoke(cli.app, ["ask", "Wie backe ich einen Apfelkuchen?", "--answer", "--force"])
    assert forced.exit_code == 0 and llm.calls


def test_graph_stats_and_entities(wired):
    res = runner.invoke(cli.app, ["graph-stats"])
    assert res.exit_code == 0 and "node ids: 59" in res.output
    res = runner.invoke(cli.app, ["graph-stats", "--json"])
    assert json.loads(res.output)["edge_ids"] == 11
    res = runner.invoke(cli.app, ["entities", "Keycloak"])
    assert res.exit_code == 0 and "Component_9ac69fd304962fd3" in res.output
    res = runner.invoke(cli.app, ["entities", "Nichtsdergleichen"])
    assert res.exit_code == 1


def test_check_command(wired, monkeypatch):
    import rag_retrieval.chat as chat_mod

    monkeypatch.setattr(chat_mod, "ChatClient", lambda settings: FakeLLM())
    res = runner.invoke(cli.app, ["check"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["ok"] is True


def test_callback_sets_env(monkeypatch, wired):
    import os

    monkeypatch.setattr(os, "environ", dict(os.environ))  # the callback writes os.environ; restore it afterwards
    res = runner.invoke(cli.app, ["--prefix", "zzz", "--url", "http://x:9200", "graph-stats"])
    assert res.exit_code == 0
    assert os.environ["RAG__INDEX__PREFIX"] == "zzz" and os.environ["RAG__OPENSEARCH__URL"] == "http://x:9200"
