import os

import pytest

from chat_system import settings as settings_mod
from chat_system.settings import Settings, config_path, redact_db_url


def test_defaults_come_from_packaged_config_yaml():
    s = Settings(_env_file=None)
    assert s.db.url == "sqlite:///./data/chat.db" and s.db.auto_upgrade is True
    assert (s.retrieval.k, s.retrieval.k_graph, s.retrieval.history_turns_for_rewrite) == (8, 12, 2)
    assert s.limits.max_concurrent_answers == 10
    assert s.ui.title == "Betriebshandbuch-Assistent" and s.ui.allow_user_switch is False


def test_env_prefix_and_nested_delimiter(monkeypatch):
    monkeypatch.setenv("CHAT__DB__URL", "postgresql+psycopg://chat:pw@localhost:5432/chat")
    monkeypatch.setenv("CHAT__RETRIEVAL__K", "4")
    monkeypatch.setenv("CHAT__UI__ALLOW_USER_SWITCH", "true")
    monkeypatch.setenv("RAG__LLM__MODEL", "ignored-here")
    s = Settings(_env_file=None)
    assert s.db.url.startswith("postgresql+psycopg://") and s.retrieval.k == 4 and s.ui.allow_user_switch is True


def test_cwd_config_yaml_is_consulted_unlike_retrieval(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("ui:\n  title: Aus dem CWD\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert config_path() == tmp_path / "config.yaml"
    assert Settings(_env_file=None).ui.title == "Aus dem CWD"


def test_chat_config_env_selects_file(tmp_path, monkeypatch):
    p = tmp_path / "alt.yaml"
    p.write_text("retrieval:\n  k: 3\n", encoding="utf-8")
    monkeypatch.setenv("CHAT_CONFIG", str(p))
    assert Settings(_env_file=None).retrieval.k == 3
    monkeypatch.setenv("CHAT_CONFIG", str(tmp_path / "nope.yaml"))
    with pytest.raises(FileNotFoundError):
        config_path()


def test_packaged_default_exists():
    assert settings_mod._DEFAULT_CONFIG.is_file()
    assert "CHAT__" not in os.environ.get("NOPE", "")


def test_redact_db_url():
    assert redact_db_url("postgresql+psycopg://chat:secret@db:5432/chat") == "postgresql+psycopg://chat:***@db:5432/chat"
    assert redact_db_url("sqlite:///./data/chat.db") == "sqlite:///./data/chat.db"
