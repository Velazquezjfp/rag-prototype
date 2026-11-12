"""Streamlit AppTest over app.py with a fake-backed service: a question yields an assistant message with a Quellen
expander, there is no user selection, the turn cap and the context limit disable the input."""

from __future__ import annotations

import pytest
from rag_users import UsersSettings, get_policy
from streamlit.testing.v1 import AppTest

from chat_system.settings import Settings
from chat_system.ui import app as ui_app
from conftest import ROOT, USERS, FakeLLM, FakeRetriever, make_service

pytestmark = pytest.mark.ui

APP = str(ROOT / "app.py")


@pytest.fixture
def ui(repo, monkeypatch):
    def _make(*, adapter="env", **kw):
        kw.setdefault("policy", get_policy(UsersSettings(_env_file=None)))  # the app's policy: no rules, no daily limit
        svc = make_service(repo, **kw)
        monkeypatch.setattr(ui_app, "SERVICE_FACTORY", lambda settings: svc)
        monkeypatch.setattr(ui_app, "get_settings", lambda: Settings(_env_file=None))
        monkeypatch.setattr(ui_app, "users_settings", lambda: UsersSettings(_env_file=None, adapter=adapter))
        ui_app.get_service.clear()
        at = AppTest.from_file(APP, default_timeout=30)
        return at, svc

    yield _make
    ui_app.get_service.clear()


def test_question_produces_answer_with_sources_for_the_one_mock_user(ui):
    at, svc = ui()
    at.run()
    assert not at.exception, at.exception
    assert at.title[0].value == "Betriebshandbuch-Assistent"
    assert [sb.label for sb in at.sidebar.selectbox] == ["Gespräche"]  # no user selection
    assert at.sidebar.caption[0].value == "**dev** · dev@localhost"
    assert len(at.metric) == 0 and any(c.value == "max. 10 Runden pro Gespräch" for c in at.sidebar.caption)
    at.chat_input[0].set_value("Was passiert, wenn Vault versiegelt ist?").run()
    assert not at.exception, at.exception
    roles = [m.avatar for m in at.chat_message]
    assert roles == ["user", "assistant"]
    assert "Vault ist versiegelt" in at.chat_message[1].markdown[0].value
    labels = [e.label for e in at.expander]
    assert any(lbl.startswith("Quellen (") for lbl in labels), labels
    assert len(svc.repo.list_conversations("dev")) == 1  # persisted for the mock user


def test_turn_cap_disables_the_input(ui):
    at, svc = ui(policy=get_policy(UsersSettings(_env_file=None, max_turns=1)))
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
    # the st.status element does not survive the rerun that follows a turn; its label is tested in test_ui_labels.py


def test_header_adapter_without_the_proxy_header_stops_the_page(ui):
    """Remote profile: no X-Forwarded-User (the request did not come through the proxy) -> no fallback user."""
    at, svc = ui(adapter="header")
    at.run()
    assert not at.exception, at.exception
    assert any("Nicht angemeldet" in e.value and "X-Forwarded-User" in e.value for e in at.error), [e.value for e in at.error]
    assert len(at.chat_input) == 0 and len(at.sidebar.selectbox) == 0


def test_context_limit_shows_the_message_and_closes_the_conversation(ui):
    err = RuntimeError("/chat/completions: HTTP 400: This model's maximum context length is 8192 tokens. However, you requested 9100 tokens")
    at, svc = ui(llm=FakeLLM(fail=err))
    at.run()
    at.chat_input[0].set_value("eine sehr lange Frage").run()
    assert not at.exception, at.exception
    assert at.chat_message[1].markdown[0].value.startswith("Kontextlimit erreicht")
    assert len(at.error) == 0 and at.chat_input[0].disabled is True
    assert any("neues Gespräch" in i.value for i in at.info)


def test_a_daily_limit_is_shown_only_when_configured(ui):
    at, svc = ui(policy=get_policy(UsersSettings(_env_file=None, daily_messages=3)))
    at.run()
    assert any(c.value == "max. 10 Runden pro Gespräch · heute 0/3 Nachrichten" for c in at.sidebar.caption)


def test_picking_a_past_conversation_loads_it(ui):
    """Regression: the sidebar used to reset the pick to the current conversation before the widget rendered, so
    selecting a past conversation did nothing."""
    at, svc = ui()
    at.run()
    at.chat_input[0].set_value("Erste Frage zu Vault?").run()
    first_id = svc.list_conversations(USERS["dev"])[0].id
    at.sidebar.button[0].click().run()                     # "Neues Gespräch"
    assert at.chat_message == [] or len(at.chat_message) == 0
    at.chat_input[0].set_value("Zweite Frage zu Keycloak?").run()
    assert len(svc.list_conversations(USERS["dev"])) == 2
    picker = next(sb for sb in at.sidebar.selectbox if sb.label == "Gespräche")
    picker.select(first_id).run()
    assert not at.exception, at.exception
    shown = [m.markdown[0].value for m in at.chat_message]
    assert shown and shown[0] == "Erste Frage zu Vault?" and "Vault ist versiegelt" in shown[1], shown
    assert picker.value == first_id or next(sb for sb in at.sidebar.selectbox if sb.label == "Gespräche").value == first_id


def test_assistant_mode_shows_the_mode_line_and_the_einordnung(ui):
    """REQ-002 R10: the sidebar names the active behaviour; an assistant answer is shown without the block, with the
    Einordnung caption."""
    at, svc = ui(profile="assistant", llm=FakeLLM("<einordnung>\nAufgabe: Skript\nBereich: innerhalb\nSystem: ZSD\nGrundlage: Handbücher\n</einordnung>\n#!/bin/sh\necho ok"))
    at.run()
    assert any("Technik-Assistent" in c.value for c in at.sidebar.caption), [c.value for c in at.sidebar.caption]
    at.chat_input[0].set_value("Mach ein Skript daraus").run()
    assert not at.exception, at.exception
    answer = at.chat_message[1].markdown[0].value
    assert answer.startswith("#!/bin/sh") and "<einordnung>" not in answer
    assert any(c.value.startswith("Einordnung: Aufgabe: Skript") for c in at.caption), [c.value for c in at.caption]
