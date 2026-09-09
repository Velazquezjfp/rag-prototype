from rag_retrieval import NO_EVIDENCE_ANSWER, WEAK_FOLLOW_UP_NOTE_DE

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


def test_weak_follow_up_is_answered_from_the_conversation(repo, otto):
    """REQ-001 R6: the guardrail refuses only on a first turn; a follow-up without new evidence goes to the model
    with the history and the weak note, cites nothing and is persisted as a normal answer."""
    llm = FakeLLM("#!/bin/sh\nvault operator unseal")
    retriever = FakeRetriever(weak=False)
    svc = make_service(repo, retriever=retriever, llm=llm)
    conv = svc.start_conversation(otto, use_graph=True, doc_ids=None)
    svc.ask(otto, conv.id, "Wie entsiegle ich den Vault?").collect()
    retriever.weak = True
    turn = svc.ask(otto, conv.id, "Mach ein Script mit diesen Befehlen")
    assert turn.guardrail is False and turn.weak_follow_up is True and turn.citations == []
    assert "".join(turn.tokens()).startswith("#!/bin/sh") and turn.finish_reason == "stop"
    prompt = llm.stream_calls[-1]
    assert [m["role"] for m in prompt] == ["system", "user", "assistant", "user"]
    assert WEAK_FOLLOW_UP_NOTE_DE in prompt[-1]["content"] and "## Quellen" not in prompt[-1]["content"]
    row = repo.list_messages(conv.id)[-1]
    assert row.guardrail is False and row.finish_reason == "stop" and row.citations == []
    assert row.diagnostics["weak_evidence"] is True and row.diagnostics["weak_follow_up"] is True and row.diagnostics["llm_called"] is True
    assert repo.usage().count(otto.user_id, TODAY) == 2
    # a first turn with weak evidence is still refused without a model call
    conv2 = svc.start_conversation(otto, use_graph=True, doc_ids=None)
    first = svc.ask(otto, conv2.id, "Wie backe ich einen Apfelkuchen?")
    assert first.guardrail is True and first.weak_follow_up is False and list(first.tokens()) == [NO_EVIDENCE_ANSWER]


def test_off_topic_analysis_blanks_the_citations(repo, otto):
    """REQ-002 R2 rule 1 / R6: the model's own scope verdict ("Bereich: außerhalb") is honoured — no sources, flagged."""
    from rag_retrieval import OUT_OF_SCOPE_ANSWER_DE

    llm = FakeLLM("<einordnung>\nAufgabe: Sonstiges\nBereich: außerhalb\nSystem: unklar\nGrundlage: Fachwissen\n</einordnung>\n" + OUT_OF_SCOPE_ANSWER_DE)
    svc = make_service(repo, retriever=FakeRetriever(weak=False), llm=llm, profile="assistant")
    conv = svc.start_conversation(otto, use_graph=True, doc_ids=None)
    turn = svc.ask(otto, conv.id, "Wie backe ich einen Apfelkuchen?")
    assert "".join(turn.tokens()).strip() == OUT_OF_SCOPE_ANSWER_DE
    assert turn.off_topic is True and turn.citations == [] and turn.guardrail is False and turn.finish_reason == "stop"
    row = repo.list_messages(conv.id)[-1]
    assert row.citations == [] and row.diagnostics["off_topic"] is True and row.diagnostics["analysis"]["in_scope"] is False
    assert row.content.strip() == OUT_OF_SCOPE_ANSWER_DE and repo.usage().count(otto.user_id, TODAY) == 1
