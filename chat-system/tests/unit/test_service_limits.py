import httpx
import pytest

from chat_system.service import TurnRefused
from chat_system.settings import Settings
from conftest import CAAS, TODAY, FakeLLM, FakeRetriever, make_service, tiny_policy


def test_eleventh_message_is_refused_without_persisting(service, otto, repo):
    conv = service.start_conversation(otto, use_graph=False, doc_ids=None)
    for i in range(10):
        service.ask(otto, conv.id, f"Frage {i}?").collect() if i < 9 else None
        if i == 9:  # the 10th message in a fresh conversation (turn cap is also 10 -> use a new conversation)
            conv2 = service.start_conversation(otto, use_graph=False, doc_ids=None)
            service.ask(otto, conv2.id, "Frage 10?").collect()
    assert service.quota(otto).used_today == 10
    conv3 = service.start_conversation(otto, use_graph=False, doc_ids=None)
    with pytest.raises(TurnRefused) as e:
        service.ask(otto, conv3.id, "Frage 11?")
    assert e.value.reason == "daily_cap" and e.value.remaining_today == 0 and "Tageslimit" in e.value.message_de
    assert repo.list_messages(conv3.id) == [] and repo.usage().count(otto.user_id, TODAY) == 10


def test_second_conversation_shares_the_daily_counter(repo, otto):
    svc = make_service(repo, policy=tiny_policy(daily=2, turns=5))
    a = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    b = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    svc.ask(otto, a.id, "eins?").collect()
    svc.ask(otto, b.id, "zwei?").collect()
    with pytest.raises(TurnRefused) as e:
        svc.ask(otto, a.id, "drei?")
    assert e.value.reason == "daily_cap"


def test_turn_cap_marks_the_conversation_capped(repo, otto):
    svc = make_service(repo, policy=tiny_policy(daily=10, turns=2))
    conv = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    r1 = svc.ask(otto, conv.id, "eins?").collect()
    assert r1.turns_left == 1 and repo.get_conversation(conv.id, otto.user_id).status == "open"
    r2 = svc.ask(otto, conv.id, "zwei?").collect()
    assert r2.turns_left == 0 and repo.get_conversation(conv.id, otto.user_id).status == "capped"
    with pytest.raises(TurnRefused) as e:
        svc.ask(otto, conv.id, "drei?")
    assert e.value.reason == "turn_cap" and "neues Gespräch" in e.value.message_de
    assert svc.quota(otto).used_today == 2  # the refused message was not counted
    # a new conversation works
    conv2 = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    assert svc.ask(otto, conv2.id, "vier?").collect().finish_reason == "stop"


def test_readonly_user_asking_for_caas_only_is_forbidden(service, rita, repo):
    conv = service.start_conversation(rita, use_graph=True, doc_ids=[CAAS])
    with pytest.raises(TurnRefused) as e:
        service.ask(rita, conv.id, "Frage?")
    assert e.value.reason == "forbidden" and "Leseberechtigung" in e.value.message_de
    assert repo.list_messages(conv.id) == [] and repo.usage().count(rita.user_id, TODAY) == 0


def test_llm_error_persists_error_row_and_refunds(repo, otto):
    llm = FakeLLM(fail=httpx.ConnectError("boom"))
    svc = make_service(repo, llm=llm)
    conv = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    turn = svc.ask(otto, conv.id, "Frage?")
    assert repo.usage().count(otto.user_id, TODAY) == 1  # reserved
    with pytest.raises(httpx.ConnectError):
        list(turn.tokens())
    assert turn.done and turn.finish_reason == "error"
    rows = repo.list_messages(conv.id)
    assert rows[-1].role == "assistant" and rows[-1].finish_reason == "error" and "nicht gezählt" in rows[-1].content
    assert rows[-1].diagnostics["error"].startswith("boom") and rows[-1].diagnostics["llm_called"] is True
    assert repo.usage().count(otto.user_id, TODAY) == 0  # refunded
    assert svc.ask(otto, conv.id, "nochmal?") is not None  # semaphore released


def test_llm_error_mid_stream_keeps_partial_text(repo, otto):
    llm = FakeLLM(reply="eins zwei drei vier", fail=RuntimeError("cut"), fail_after=2)
    svc = make_service(repo, llm=llm)
    conv = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    turn = svc.ask(otto, conv.id, "Frage?")
    got = []
    with pytest.raises(RuntimeError):
        for t in turn.tokens():
            got.append(t)
    assert got == ["eins ", "zwei "] and turn.finish_reason == "error"
    assert repo.list_messages(conv.id)[-1].content == "eins zwei "
    assert repo.usage().count(otto.user_id, TODAY) == 0


def test_retrieval_error_persists_error_refunds_and_releases(repo, otto):
    svc = make_service(repo, retriever=FakeRetriever(fail=ConnectionError("opensearch down")))
    conv = svc.start_conversation(otto, use_graph=True, doc_ids=None)
    with pytest.raises(ConnectionError):
        svc.ask(otto, conv.id, "Frage?")
    rows = repo.list_messages(conv.id)
    assert [r.role for r in rows] == ["user", "assistant"] and rows[-1].finish_reason == "error"
    assert repo.usage().count(otto.user_id, TODAY) == 0
    svc.retriever = FakeRetriever()
    assert svc.ask(otto, conv.id, "geht wieder?").collect().finish_reason == "stop"  # semaphore was released


def test_semaphore_refuses_with_busy(repo, otto):
    svc = make_service(repo, settings=Settings(_env_file=None, db={"url": "sqlite://"}, limits={"max_concurrent_answers": 1}))
    conv = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    turn = svc.ask(otto, conv.id, "eins?")  # holds the only slot until consumed
    with pytest.raises(TurnRefused) as e:
        svc.ask(otto, conv.id, "zwei?")
    assert e.value.reason == "busy" and "gleichzeitig" in e.value.message_de
    assert repo.usage().count(otto.user_id, TODAY) == 1  # the busy refusal did not count
    turn.collect()
    assert svc.ask(otto, conv.id, "zwei?").collect().finish_reason == "stop"


def test_foreign_conversation_is_forbidden(service, otto, rita):
    conv = service.start_conversation(otto, use_graph=True, doc_ids=None)
    with pytest.raises(TurnRefused) as e:
        service.ask(rita, conv.id, "Frage?")
    assert e.value.reason == "forbidden"
