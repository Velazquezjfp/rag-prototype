"""Streamlit AppTest over app.py with a fake-backed service: a question yields an assistant message with a Quellen
expander, the quota metric moves, the turn cap disables the input."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from chat_system.settings import Settings
from chat_system.ui import app as ui_app
from conftest import ROOT, FakeRetriever, make_service, tiny_policy

pytestmark = pytest.mark.ui

APP = str(ROOT / "app.py")


@pytest.fixture
def ui(repo, monkeypatch):
    def _make(**kw):
        svc = make_service(repo, **kw)
        monkeypatch.setattr(ui_app, "SERVICE_FACTORY", lambda settings: svc)
        monkeypatch.setattr(ui_app, "get_settings", lambda: Settings(_env_file=None, ui={"allow_user_switch": True}))
        ui_app.get_service.clear()
        at = AppTest.from_file(APP, default_timeout=30)
        return at, svc

    yield _make
    ui_app.get_service.clear()


def test_question_produces_answer_with_sources_and_quota_moves(ui):
    at, svc = ui()
    at.run()
    assert not at.exception, at.exception
    assert at.title[0].value == "Betriebshandbuch-Assistent"
    assert at.sidebar.selectbox[0].label.startswith("Benutzer") and at.sidebar.selectbox[0].value == "dev"
    assert at.metric[0].value == "0/10"
    at.chat_input[0].set_value("Was passiert, wenn Vault versiegelt ist?").run()
    assert not at.exception, at.exception
    roles = [m.avatar for m in at.chat_message]
    assert roles == ["user", "assistant"]
    assert "Vault ist versiegelt" in at.chat_message[1].markdown[0].value
    labels = [e.label for e in at.expander]
    assert any(lbl.startswith("Quellen (") for lbl in labels), labels
    assert at.metric[0].value == "1/10"
    assert len(svc.repo.list_conversations(svc.repo.get_conversation.__self__ and "dev")) == 1  # persisted


def test_turn_cap_disables_the_input(ui):
    at, svc = ui(policy=tiny_policy(daily=10, turns=1))
    at.run()
    at.chat_input[0].set_value("erste Frage?").run()
    assert not at.exception, at.exception
    assert any("maximale Länge" in i.value for i in at.info), [i.value for i in at.info]
    assert at.chat_input[0].disabled is True


def test_guardrail_answer_is_shown_with_note(ui):
    at, svc = ui(retriever=FakeRetriever(weak=True))
    at.run()
    at.chat_input[0].set_value("Wie backe ich einen Apfelkuchen?").run()
    assert not at.exception, at.exception
    assert "Dazu steht nichts in den Handbüchern." in at.chat_message[1].markdown[0].value
    assert any("Schutzmechanismus" in c.value for c in at.caption)


def test_user_switch_changes_identity_and_quota(ui):
    at, svc = ui()
    at.run()
    at.sidebar.selectbox[0].select("rita.read").run()
    assert not at.exception, at.exception
    assert at.metric[0].value == "0/5"
    assert "rita.read" in at.sidebar.caption[0].value
