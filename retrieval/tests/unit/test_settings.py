import os

import pytest

from rag_retrieval import settings as settings_mod
from rag_retrieval.settings import Settings, config_path


@pytest.fixture(autouse=True)
def _clean_rag_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("RAG__") or key == "RAG_CONFIG":
            monkeypatch.delenv(key)


def test_defaults_come_from_packaged_config_yaml():
    s = Settings(_env_file=None)
    assert s.index.prefix == "bhb"
    assert s.retrieval.rrf_rank_constant == 60
    assert s.embedding.model == "bge-m3" and s.embedding.dim == 1024
    assert s.llm.model == "gemini-dev"
    assert s.guardrail.enabled is True
    assert s.retrieval.history_turns == 3


def test_env_prefix_and_nested_delimiter(monkeypatch):
    monkeypatch.setenv("RAG__LLM__MODEL", "granite4")
    monkeypatch.setenv("RAG__RETRIEVAL__FINAL_K", "4")
    monkeypatch.setenv("RAG__RETRIEVAL__HISTORY_TURNS", "10")
    monkeypatch.setenv("RAG__OPENSEARCH__URL", "https://search.internal:9200")
    s = Settings(_env_file=None)
    assert s.llm.model == "granite4"
    assert s.retrieval.final_k == 4 and s.retrieval.history_turns == 10
    assert s.opensearch.url == "https://search.internal:9200"


def test_osi_prefixed_env_is_ignored(monkeypatch):
    monkeypatch.setenv("OSI__INDEX__PREFIX", "other")
    assert Settings(_env_file=None).index.prefix == "bhb"


def test_cwd_config_yaml_is_not_consulted(tmp_path, monkeypatch):
    """chat-system runs from its own folder with its own config.yaml; ours must not pick it up."""
    (tmp_path / "config.yaml").write_text("index:\n  prefix: from-cwd\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RAG_CONFIG", raising=False)
    assert config_path() == settings_mod._DEFAULT_CONFIG
    assert Settings(_env_file=None).index.prefix == "bhb"


def test_rag_config_env_selects_file(tmp_path, monkeypatch):
    p = tmp_path / "alt.yaml"
    p.write_text("index:\n  prefix: alt\nllm:\n  model: m\n", encoding="utf-8")
    monkeypatch.setenv("RAG_CONFIG", str(p))
    assert config_path() == p
    assert Settings(_env_file=None).index.prefix == "alt"


def test_rag_config_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_CONFIG", str(tmp_path / "nope.yaml"))
    with pytest.raises(FileNotFoundError):
        config_path()


def test_redact_url():
    assert settings_mod.redact_url("http://x/v1", "secret") == {"base_url": "http://x/v1", "api_key": "***"}
    assert settings_mod.redact_url("http://x/v1", None)["api_key"] == "(none)"
    assert "RAG__" not in os.environ.get("NOPE", "")


def test_prompt_profile_follows_the_guardrail_switch_unless_explicit(monkeypatch):
    """REQ-002 R1: auto = assistant iff the guardrail is disabled; strict/assistant win over the switch."""
    from rag_retrieval.settings import resolve_profile

    assert Settings(_env_file=None).prompt.profile == "auto"
    assert resolve_profile(Settings(_env_file=None)) == "strict"
    assert resolve_profile(Settings(_env_file=None, guardrail={"enabled": False})) == "assistant"
    assert resolve_profile(Settings(_env_file=None, guardrail={"enabled": False}, prompt={"profile": "strict"})) == "strict"
    assert resolve_profile(Settings(_env_file=None, prompt={"profile": "assistant"})) == "assistant"
    monkeypatch.setenv("RAG__GUARDRAIL__ENABLED", "false")
    monkeypatch.setenv("RAG__LLM__EXTRA_BODY", '{"think": false}')
    s = Settings(_env_file=None)
    assert resolve_profile(s) == "assistant" and s.llm.extra_body == {"think": False}
    assert resolve_profile(object()) == "strict"  # duck-typed: no prompt/guardrail attributes -> strict
