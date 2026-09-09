from rag_retrieval import (
    NO_EVIDENCE_ANSWER,  # noqa: F401 - documents the contract
    SYSTEM_PROMPT_DE,
)

from chat_system.service import Quota, TurnResult
from conftest import CAAS, TODAY, ZSD


def test_first_turn_streams_persists_and_counts(service, otto, retriever, llm, repo):
    conv = service.start_conversation(otto, use_graph=True, doc_ids=None)
    turn = service.ask(otto, conv.id, "Was passiert, wenn Vault versiegelt ist?")
    assert turn.guardrail is False and turn.question_rewritten is None and turn.use_graph is True
    assert turn.citations and turn.citations[0]["doc_id"] == ZSD and turn.citations[0]["channels"] == ["knn", "bm25"]
    assert turn.citations[0]["breadcrumb"] == "5 Betrieb › 5.4 Vault" and "Unseal" in turn.citations[0]["snippet"]
    tokens = list(turn.tokens())
    assert "".join(tokens).strip() == llm.reply and turn.done and turn.finish_reason == "stop"
    # rewrite skipped on the first turn, the model streamed once
    assert llm.complete_calls == [] and len(llm.stream_calls) == 1
    # the raw question reaches the prompt; the system prompt is rag-retrieval's
    prompt = llm.stream_calls[0]
    assert prompt[0]["content"] == SYSTEM_PROMPT_DE and prompt[-1]["content"].endswith("Frage: Was passiert, wenn Vault versiegelt ist?")
    # persisted rows
    rows = repo.list_messages(conv.id)
    assert [r.role for r in rows] == ["user", "assistant"]
    a = rows[1]
    assert a.content.strip() == llm.reply and a.finish_reason == "stop" and a.model == "fake-llm" and a.guardrail is False
    assert a.citations[0]["key"] == f"{ZSD} S. 19" and a.diagnostics["llm_called"] is True and a.diagnostics["mode"] == "slow"
    assert a.diagnostics["facts"][0]["polarity"] == "negative" and a.diagnostics["timings_ms"]["total"] >= 0
    assert a.latency_ms is not None and a.use_graph is True
    # quota
    assert service.quota(otto) == Quota(used_today=1, daily_cap=10, max_turns=10)
    res = turn.to_result()
    assert isinstance(res, TurnResult) and res.remaining_today == 9 and res.turns_left == 9 and res.message_id == a.id
    # retriever got the right call
    assert retriever.calls == [{"question": "Was passiert, wenn Vault versiegelt ist?", "use_graph": True, "k": 12, "doc_ids": None}]


def test_follow_up_is_rewritten_from_the_last_turns_and_history_reaches_the_prompt(service, otto, retriever, llm):
    conv = service.start_conversation(otto, use_graph=False, doc_ids=None)
    service.ask(otto, conv.id, "Wer ist für Vault zuständig?").collect()
    turn = service.ask(otto, conv.id, "und bei Keycloak?")
    assert turn.question_rewritten == "Wer ist für Keycloak zuständig?"
    assert len(llm.complete_calls) == 1
    rewrite_prompt = llm.complete_calls[0][1]["content"]
    assert "Nutzer: Wer ist für Vault zuständig?" in rewrite_prompt and "Letzte Frage: und bei Keycloak?" in rewrite_prompt
    # the rewritten form is what retrieval sees, the raw form what the model is asked
    assert retriever.calls[-1]["question"] == "Wer ist für Keycloak zuständig?" and retriever.calls[-1]["use_graph"] is False and retriever.calls[-1]["k"] == 8
    res = turn.collect()
    prompt = llm.stream_calls[-1]
    assert prompt[-1]["content"].endswith("Frage: und bei Keycloak?")
    assert [m["role"] for m in prompt] == ["system", "user", "assistant", "user"]
    assert res.question_rewritten == "Wer ist für Keycloak zuständig?" and res.question_raw == "und bei Keycloak?"
    rows = service.repo.list_messages(conv.id)
    assert rows[-1].question_rewritten == "Wer ist für Keycloak zuständig?" and rows[-1].content.strip() == llm.reply


def test_use_graph_and_effective_doc_ids_reach_retrieve(service, rita, anna, retriever):
    conv = service.start_conversation(rita, use_graph=True, doc_ids=[CAAS, ZSD])
    service.ask(rita, conv.id, "Frage?", use_graph=False).collect()
    assert retriever.calls[-1] == {"question": "Frage?", "use_graph": False, "k": 8, "doc_ids": [ZSD]}  # read-only: ZSD only
    conv2 = service.start_conversation(anna, use_graph=True, doc_ids=None)
    service.ask(anna, conv2.id, "Frage?", doc_ids=[CAAS]).collect()
    assert retriever.calls[-1]["doc_ids"] == [CAAS] and retriever.calls[-1]["use_graph"] is True
    service.ask(anna, conv2.id, "Frage?").collect()
    assert retriever.calls[-1]["doc_ids"] is None


def test_conversation_defaults_apply_when_ask_does_not_override(service, otto, retriever):
    conv = service.start_conversation(otto, use_graph=False, doc_ids=[CAAS])
    service.ask(otto, conv.id, "Frage?").collect()
    assert retriever.calls[-1]["use_graph"] is False and retriever.calls[-1]["doc_ids"] == [CAAS]


def test_documents_is_catalog_intersected_with_the_policy(service, otto, rita):
    assert [d["doc_id"] for d in service.documents(otto)] == [CAAS, ZSD]
    assert [d["doc_id"] for d in service.documents(rita)] == [ZSD]


def test_resume_and_list_are_scoped(service, otto, rita):
    conv = service.start_conversation(otto, use_graph=True, doc_ids=None)
    service.ask(otto, conv.id, "Frage eins?").collect()
    got, rows = service.resume(otto, conv.id)
    assert got.id == conv.id and got.title == "Frage eins?" and [r.role for r in rows] == ["user", "assistant"]
    assert [c.id for c in service.list_conversations(otto)] == [conv.id]
    assert service.list_conversations(rita) == []
    from chat_system.service import TurnRefused

    try:
        service.resume(rita, conv.id)
    except TurnRefused as exc:
        assert exc.reason == "forbidden"
    else:
        raise AssertionError("rita must not resume otto's conversation")


def test_ask_rejects_empty_question_before_touching_anything(service, otto, repo):
    conv = service.start_conversation(otto, use_graph=True, doc_ids=None)
    import pytest

    with pytest.raises(ValueError):
        service.ask(otto, conv.id, "   ")
    assert repo.usage().count(otto.user_id, TODAY) == 0 and repo.list_messages(conv.id) == []


def test_history_window_comes_from_the_retrieval_settings(repo, otto):
    from types import SimpleNamespace

    from conftest import FakeLLM, make_service

    llm = FakeLLM()
    rag = SimpleNamespace(
        llm=SimpleNamespace(context_limit_tokens=32000, model="fake-llm"),
        retrieval=SimpleNamespace(context_token_budget=6000, max_facts_in_prompt=25, history_turns=1),
    )
    svc = make_service(repo, llm=llm)
    svc.rag_settings = rag
    conv = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    for q in ("eins?", "zwei?", "drei?"):
        svc.ask(otto, conv.id, q).collect()
    prompt = llm.stream_calls[-1]
    # one pair of history (history_turns=1) + the new question; the default would carry both earlier pairs
    assert [m["role"] for m in prompt] == ["system", "user", "assistant", "user"]
    assert prompt[1]["content"] == "zwei?"


def test_truncated_stream_is_persisted_as_length(repo, otto):
    """REQ-001 R8: a stream that reports finish_reason=length ends the turn as ``length`` (text kept, counted)."""
    from conftest import FakeLLM, make_service

    class TruncatingStream:
        def __init__(self, tokens):
            self.tokens = tokens
            self.finish_reason = None

        def __iter__(self):
            yield from self.tokens
            self.finish_reason = "length"

    class TruncatingLLM(FakeLLM):
        def stream(self, messages, *, model=None, max_tokens=None, temperature=None):
            self.stream_calls.append([dict(m) for m in messages])
            return TruncatingStream(["Erster ", "Teil"])

    llm = TruncatingLLM()
    svc = make_service(repo, llm=llm)
    conv = svc.start_conversation(otto, use_graph=True, doc_ids=None)
    turn = svc.ask(otto, conv.id, "Welche Firewall-Regeln sind konfiguriert?")
    assert "".join(turn.tokens()) == "Erster Teil" and turn.finish_reason == "length"
    row = repo.list_messages(conv.id)[-1]
    assert row.finish_reason == "length" and row.content == "Erster Teil" and row.diagnostics["finish_reason"] == "length"
    assert turn.to_result().finish_reason == "length" and repo.usage().count(otto.user_id, TODAY) == 1
