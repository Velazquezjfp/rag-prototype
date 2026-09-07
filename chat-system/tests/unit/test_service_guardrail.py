from rag_retrieval import NO_EVIDENCE_ANSWER

from conftest import TODAY, FakeLLM, FakeRetriever, make_service


def test_weak_evidence_yields_the_canned_sentence_without_calling_the_model(repo, otto):
    llm = FakeLLM()
    svc = make_service(repo, retriever=FakeRetriever(weak=True), llm=llm)
    conv = svc.start_conversation(otto, use_graph=True, doc_ids=None)
    turn = svc.ask(otto, conv.id, "Wie backe ich einen Apfelkuchen?")
    assert turn.guardrail is True and turn.citations == [] and turn.facts == []  # kNN chunks exist, but nothing is cited
    assert list(turn.tokens()) == [NO_EVIDENCE_ANSWER]
    assert llm.stream_calls == [] and llm.complete_calls == []
    assert turn.finish_reason == "guardrail" and turn.answer == NO_EVIDENCE_ANSWER
    row = repo.list_messages(conv.id)[-1]
    assert row.guardrail is True and row.finish_reason == "guardrail" and row.content == NO_EVIDENCE_ANSWER
    assert row.citations == [] and row.diagnostics["channels"][0]["returned"] == 20  # the retrieval ran, nothing is cited
    assert row.diagnostics["llm_called"] is False and row.diagnostics["weak_evidence"] is True and row.model is None
    assert "lexical" in row.diagnostics["weak_evidence_reason"]
    # the question still counts (retrieval ran), the conversation continues
    assert repo.usage().count(otto.user_id, TODAY) == 1
    res = turn.to_result()
    assert res.guardrail and res.answer == NO_EVIDENCE_ANSWER and res.finish_reason == "guardrail"


def test_guardrail_turn_does_not_prevent_a_normal_follow_up(repo, otto):
    llm = FakeLLM()
    retriever = FakeRetriever(weak=True)
    svc = make_service(repo, retriever=retriever, llm=llm)
    conv = svc.start_conversation(otto, use_graph=True, doc_ids=None)
    svc.ask(otto, conv.id, "Apfelkuchen?").collect()
    retriever.weak = False
    res = svc.ask(otto, conv.id, "Was passiert, wenn Vault versiegelt ist?").collect()
    assert res.finish_reason == "stop" and res.guardrail is False and len(llm.stream_calls) == 1
    # the guardrail answer is part of the history the model sees
    assert any(m["content"] == NO_EVIDENCE_ANSWER for m in llm.stream_calls[0])
