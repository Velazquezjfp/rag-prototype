import json

import pytest
from typer.testing import CliRunner

from chat_system import cli, wiring
from chat_system.settings import Settings
from conftest import FakeRetriever, make_service

runner = CliRunner()


@pytest.fixture
def fake_wiring(repo, monkeypatch):
    svc = make_service(repo)
    monkeypatch.setattr(wiring, "build_service", lambda settings=None, **kw: svc)
    return svc


def test_chat_ask_streams_answer_and_sources(fake_wiring):
    res = runner.invoke(cli.ask_app, ["Was passiert, wenn Vault versiegelt ist?", "--user", "otto.ops"])
    assert res.exit_code == 0, res.output
    assert "Vault ist versiegelt" in res.output and "Quellen:" in res.output and "[BHB-PLT-0007 S. 19]" in res.output
    assert "heute noch 9 Nachricht" in res.output


def test_chat_ask_json(fake_wiring):
    res = runner.invoke(cli.ask_app, ["Frage?", "--no-graph", "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["finish_reason"] == "stop" and data["use_graph"] is False and data["citations"][0]["doc_id"] == "BHB-PLT-0007"
    assert data["remaining_today"] == 9 and data["question_raw"] == "Frage?"


def test_chat_ask_continues_a_conversation_and_rewrites(fake_wiring):
    first = runner.invoke(cli.ask_app, ["Wer ist für Vault zuständig?", "--json"])
    conv_id = json.loads(first.output)["conversation_id"]
    second = runner.invoke(cli.ask_app, ["und bei Keycloak?", "--conversation", conv_id])
    assert second.exit_code == 0 and "umformulierte Frage: Wer ist für Keycloak zuständig?" in second.output


def test_chat_ask_refusal_exits_2_and_unknown_user_exits_1(fake_wiring):
    res = runner.invoke(cli.ask_app, ["Frage?", "--user", "rita.read", "--doc-id", "BHB-PLT-0001"])
    assert res.exit_code == 2 and "abgelehnt (forbidden)" in res.output
    res = runner.invoke(cli.ask_app, ["Frage?", "--user", "ghost"])
    assert res.exit_code == 1 and "unknown dev user" in res.output


def test_chat_ask_guardrail_prints_the_canned_answer(repo, monkeypatch):
    svc = make_service(repo, retriever=FakeRetriever(weak=True))
    monkeypatch.setattr(wiring, "build_service", lambda settings=None, **kw: svc)
    res = runner.invoke(cli.ask_app, ["Apfelkuchen?"])
    assert res.exit_code == 0 and "Dazu steht nichts in den Handbüchern." in res.output and "guardrail=True" in res.output


def test_chat_db_upgrade_and_current(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("CHAT__DB__URL", url)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
    res = runner.invoke(cli.db_app, ["current"])
    assert res.exit_code == 1 and "UPGRADE NEEDED" in res.output
    res = runner.invoke(cli.db_app, ["upgrade"])
    assert res.exit_code == 0 and "upgraded" in res.output
    res = runner.invoke(cli.db_app, ["current"])
    assert res.exit_code == 0 and "current=0001 head=0001 ok" in res.output


def test_chat_doctor_reports_and_exit_code(monkeypatch):
    monkeypatch.setattr(
        cli, "run_doctor", lambda: {"ok": False, "checks": [{"name": "db", "status": "ok", "detail": "fine"}, {"name": "llm", "status": "fail", "detail": "down"}]}
    )
    res = runner.invoke(cli.doctor_app, [])
    assert res.exit_code == 1 and "FAIL llm" in res.output and "OK   db" in res.output
    monkeypatch.setattr(cli, "run_doctor", lambda: {"ok": True, "checks": []})
    res = runner.invoke(cli.doctor_app, ["--json"])
    assert res.exit_code == 0 and json.loads(res.output)["ok"] is True


def test_run_doctor_db_check_on_tmp_sqlite(tmp_path, monkeypatch):
    """The DB part of the real doctor without OpenSearch/LLM: rag settings import fails -> those checks fail, db passes."""
    url = f"sqlite:///{tmp_path / 'doc.db'}"
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, db={"url": url}))
    monkeypatch.setattr(wiring, "rag_settings", lambda: (_ for _ in ()).throw(RuntimeError("no rag here")))
    report = cli.run_doctor()
    by = {c["name"]: c for c in report["checks"]}
    assert by["db"]["status"] == "warn" and "no schema yet" in by["db"]["detail"]
    assert by["opensearch"]["status"] == "fail" and "no rag here" in by["opensearch"]["detail"]
    assert by["users"]["status"] == "ok" and "dev" in by["users"]["detail"]
    assert report["ok"] is False
