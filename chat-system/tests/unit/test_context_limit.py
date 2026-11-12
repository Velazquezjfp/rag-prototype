"""The model refuses a prompt that does not fit its context window: no crash, a clear German message, the message is
not counted and the conversation is closed (the user starts a new one)."""

import httpx
import pytest
from rag_retrieval.llm_http import LLMHTTPError
from rag_users import get_policy

from chat_system.service import CONTEXT_LIMIT_TEXT_DE, TurnRefused, is_context_limit_error
from conftest import TODAY, FakeLLM, FakeRetriever, make_service

VLLM = LLMHTTPError("/chat/completions: HTTP 400: b'{\"message\":\"This model\'s maximum context length is 8192 tokens. However, you requested 9000 tokens\"}'", 400)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (VLLM, True),
        (LLMHTTPError("/chat/completions: HTTP 400: litellm.ContextWindowExceededError: prompt is too long", 400), True),
        (LLMHTTPError("/chat/completions: HTTP 400: {\"error\":{\"code\":\"context_length_exceeded\"}}", 400), True),
        (LLMHTTPError("/embeddings: HTTP 413", 413), True),
        (RuntimeError("the input length exceeds the available context size, please reduce the length"), True),
        (LLMHTTPError("/chat/completions: HTTP 400: unknown model", 400), False),
        (LLMHTTPError("/chat/completions: HTTP 429: rate limit", 429), False),
        (httpx.ConnectError("boom"), False),
    ],
)
def test_context_limit_errors_are_recognised(exc, expected):
    assert is_context_limit_error(exc) is expected


def test_context_limit_in_the_stream_becomes_the_answer_refunds_and_caps(repo, otto):
    svc = make_service(repo, llm=FakeLLM(fail=VLLM), policy=get_policy())
    conv = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    turn = svc.ask(otto, conv.id, "Frage?")
    assert list(turn.tokens()) == [CONTEXT_LIMIT_TEXT_DE]  # no exception reaches the caller
    assert turn.done and turn.finish_reason == "context_limit" and turn.answer == CONTEXT_LIMIT_TEXT_DE
    row = repo.list_messages(conv.id)[-1]
    assert row.finish_reason == "context_limit" and row.content == CONTEXT_LIMIT_TEXT_DE
    assert "maximum context length" in row.diagnostics["error"]
    assert repo.usage().count(otto.user_id, TODAY) == 0  # not counted
    assert repo.get_conversation(conv.id, otto.user_id).status == "capped"
    with pytest.raises(TurnRefused) as e:
        svc.ask(otto, conv.id, "nochmal?")
    assert e.value.reason == "turn_cap" and "neues Gespräch" in e.value.message_de
    conv2 = svc.start_conversation(otto, use_graph=False, doc_ids=None)  # a new conversation works, the slot is free
    svc.llm = FakeLLM()
    assert svc.ask(otto, conv2.id, "geht wieder?").collect().finish_reason == "stop"


def test_context_limit_before_the_stream_is_a_refusal_not_a_crash(repo, otto):
    svc = make_service(repo, retriever=FakeRetriever(fail=LLMHTTPError("/embeddings: HTTP 400: input is too long for the context window", 400)))
    conv = svc.start_conversation(otto, use_graph=True, doc_ids=None)
    with pytest.raises(TurnRefused) as e:
        svc.ask(otto, conv.id, "sehr langer Text")
    assert e.value.reason == "context_limit" and e.value.message_de == CONTEXT_LIMIT_TEXT_DE
    rows = repo.list_messages(conv.id)
    assert [r.role for r in rows] == ["user", "assistant"] and rows[-1].finish_reason == "context_limit"
    assert repo.usage().count(otto.user_id, TODAY) == 0
    assert repo.get_conversation(conv.id, otto.user_id).status == "capped"


def test_other_model_errors_still_raise_and_do_not_cap(repo, otto):
    svc = make_service(repo, llm=FakeLLM(fail=LLMHTTPError("/chat/completions: HTTP 400: unknown model", 400)))
    conv = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    turn = svc.ask(otto, conv.id, "Frage?")
    with pytest.raises(LLMHTTPError):
        list(turn.tokens())
    assert turn.finish_reason == "error" and repo.get_conversation(conv.id, otto.user_id).status == "open"


def test_app_policy_has_no_daily_limit_and_ignores_groups(repo, rita):
    """rag_users.get_policy(): every user, whatever the groups, may ask about every manual, without a daily limit."""
    svc = make_service(repo, policy=get_policy())
    assert [d["doc_id"] for d in svc.documents(rita)] == ["BHB-PLT-0001", "BHB-PLT-0007"]
    q = svc.quota(rita)
    assert q.daily_cap is None and q.remaining_today is None and q.max_turns == 10
    conv = svc.start_conversation(rita, use_graph=False, doc_ids=["BHB-PLT-0001"])
    res = svc.ask(rita, conv.id, "Frage?").collect()
    assert res.finish_reason == "stop" and res.remaining_today is None and res.turns_left == 9
