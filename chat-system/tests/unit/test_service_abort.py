from conftest import TODAY, FakeLLM, make_service


def test_consumer_stops_early_partial_text_is_persisted_as_aborted(repo, otto):
    llm = FakeLLM(reply="eins zwei drei vier fünf")
    svc = make_service(repo, llm=llm)
    conv = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    turn = svc.ask(otto, conv.id, "Frage?")
    gen = turn.tokens()
    assert next(gen) == "eins " and next(gen) == "zwei "
    gen.close()  # what st.write_stream does when the browser tab is closed / the script is interrupted
    assert turn.done and turn.finish_reason == "aborted" and turn.answer == "eins zwei "
    row = repo.list_messages(conv.id)[-1]
    assert row.role == "assistant" and row.content == "eins zwei " and row.finish_reason == "aborted"
    assert repo.usage().count(otto.user_id, TODAY) == 1  # an aborted answer still counts (the model was called)


def test_abort_is_idempotent_and_releases_the_slot(repo, otto):
    from chat_system.settings import Settings

    svc = make_service(repo, settings=Settings(_env_file=None, db={"url": "sqlite://"}, limits={"max_concurrent_answers": 1}))
    conv = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    turn = svc.ask(otto, conv.id, "Frage?")
    turn.abort()
    turn.abort()
    assert turn.done and turn.finish_reason == "aborted" and turn.answer == ""
    assert len(repo.list_messages(conv.id)) == 2
    assert svc.ask(otto, conv.id, "nochmal?").collect().finish_reason == "stop"  # one release only, slot free again


def test_tokens_after_done_replays_the_answer(repo, otto):
    svc = make_service(repo)
    conv = svc.start_conversation(otto, use_graph=False, doc_ids=None)
    turn = svc.ask(otto, conv.id, "Frage?")
    first = "".join(turn.tokens())
    assert "".join(turn.tokens()) == first and len(repo.list_messages(conv.id)) == 2
