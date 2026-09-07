from datetime import UTC, date, timedelta

import pytest
from sqlalchemy import select

from chat_system.models import Conversation, Message, Usage
from conftest import TODAY, ZSD

USER = "otto.ops"


def test_create_and_get_conversation_is_scoped_by_user(repo):
    conv = repo.create_conversation(USER, use_graph=True, doc_ids=[ZSD])
    assert len(conv.id) == 36 and conv.turn_count == 0 and conv.status == "open" and conv.doc_ids == [ZSD]
    assert repo.get_conversation(conv.id, USER).id == conv.id
    assert repo.get_conversation(conv.id, "rita.read") is None  # somebody else's conversation does not exist for her
    assert repo.get_conversation("nope", USER) is None


def test_messages_get_sequential_seq_and_first_user_message_becomes_the_title(repo):
    conv = repo.create_conversation(USER, use_graph=False, doc_ids=None)
    long_q = "Was passiert, wenn Vault versiegelt ist und die Raft-Mehrheit verloren geht, obwohl drei Pods laufen?"
    m1 = repo.add_user_message(conv.id, long_q)
    m2 = repo.add_assistant_message(
        conv.id, "Antwort.", question_rewritten=None, use_graph=False, citations=[{"key": f"{ZSD} S. 19"}],
        diagnostics={"timings_ms": {"total": 12}, "facts": []}, guardrail=False, finish_reason="stop", model="m", latency_ms=12,
    )
    m3 = repo.add_user_message(conv.id, "Und Keycloak?")
    assert (m1.seq, m2.seq, m3.seq) == (1, 2, 3) and m1.role == "user" and m2.role == "assistant"
    got = repo.get_conversation(conv.id, USER)
    assert got.turn_count == 2  # user messages only
    assert got.title.startswith("Was passiert, wenn Vault") and len(got.title) <= 80 and got.title.endswith("…")
    rows = repo.list_messages(conv.id)
    assert [r.seq for r in rows] == [1, 2, 3]
    assert rows[1].citations == [{"key": f"{ZSD} S. 19"}] and rows[1].diagnostics["timings_ms"]["total"] == 12  # JSON round trip


def test_datetimes_are_utc_aware_on_read(repo, clock):
    conv = repo.create_conversation(USER, use_graph=True, doc_ids=None)
    got = repo.get_conversation(conv.id, USER)
    assert got.created_at.tzinfo is not None and got.created_at.utcoffset() == timedelta(0)
    assert got.created_at == clock.now
    rows = repo.list_messages(conv.id)
    assert rows == []
    repo.add_user_message(conv.id, "x")
    assert repo.list_messages(conv.id)[0].created_at.tzinfo is not None


def test_list_conversations_orders_by_activity_and_limits(repo, clock):
    ids = []
    for _ in range(3):
        clock.now = clock.now + timedelta(minutes=1)
        ids.append(repo.create_conversation(USER, use_graph=True, doc_ids=None).id)
    repo.create_conversation("anna.admin", use_graph=True, doc_ids=None)
    clock.now = clock.now + timedelta(minutes=5)
    repo.add_user_message(ids[0], "activity on the oldest")  # bumps updated_at
    got = [c.id for c in repo.list_conversations(USER)]
    assert got == [ids[0], ids[2], ids[1]]
    assert len(repo.list_conversations(USER, limit=2)) == 2


def test_mark_capped(repo):
    conv = repo.create_conversation(USER, use_graph=True, doc_ids=None)
    repo.mark_capped(conv.id)
    assert repo.get_conversation(conv.id, USER).status == "capped"


def test_usage_increment_update_insert_and_refund(repo):
    u = repo.usage()
    assert u.count(USER, TODAY) == 0
    assert u.increment(USER, TODAY) == 1  # INSERT path
    assert u.increment(USER, TODAY) == 2  # UPDATE path
    assert u.increment(USER, TODAY, by=-1) == 1  # refund
    assert u.increment(USER, TODAY, by=-5) == 0  # never negative
    assert u.count(USER, TODAY + timedelta(days=1)) == 0 and u.count("rita.read", TODAY) == 0
    assert u.increment("rita.read", TODAY, by=-1) == 0  # refund without a row: no negative row


def test_begin_turn_reserves_and_stores_in_one_transaction(repo, engine):
    conv = repo.create_conversation(USER, use_graph=True, doc_ids=None)
    msg, used = repo.begin_turn(conv.id, "Frage 1", user_id=USER, day=TODAY)
    assert msg.seq == 1 and used == 1
    msg, used = repo.begin_turn(conv.id, "Frage 2", user_id=USER, day=TODAY)
    assert msg.seq == 2 and used == 2
    assert repo.usage().count(USER, TODAY) == 2 and repo.get_conversation(conv.id, USER).turn_count == 2
    with pytest.raises(LookupError):
        repo.begin_turn("missing", "x", user_id=USER, day=TODAY)
    assert repo.usage().count(USER, TODAY) == 2  # the failed turn did not reserve a slot (rolled back)


def test_cascade_delete_removes_messages(repo, engine):
    conv = repo.create_conversation(USER, use_graph=True, doc_ids=None)
    repo.add_user_message(conv.id, "x")
    from sqlalchemy.orm import Session

    with Session(engine) as s, s.begin():
        s.delete(s.get(Conversation, conv.id))
    with Session(engine) as s:
        assert s.scalars(select(Message).where(Message.conversation_id == conv.id)).all() == []
        assert s.scalars(select(Usage)).all() == []


def test_day_type_round_trip(repo):
    d = date(2026, 12, 31)
    repo.usage().increment(USER, d)
    assert repo.usage().count(USER, d) == 1
    assert repo.usage().count(USER, date(2027, 1, 1)) == 0
    assert TODAY.tzinfo if hasattr(TODAY, "tzinfo") else UTC  # noqa: B018 - keeps UTC import meaningful
