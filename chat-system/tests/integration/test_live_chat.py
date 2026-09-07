"""Real wiring (OpenSearch with both manuals, LiteLLM for bge-m3 + gemini-dev) on a temporary SQLite database.
Gated by CHAT_INTEGRATION=1; RAG__*/USERS__* come from chat-system/.env (the test runs from that folder)."""

from __future__ import annotations

import os

import pytest
from rag_retrieval import NO_EVIDENCE_ANSWER
from rag_users import USERS

from chat_system.settings import Settings
from chat_system.wiring import build_service

pytestmark = pytest.mark.integration

if not os.environ.get("CHAT_INTEGRATION"):
    pytest.skip("set CHAT_INTEGRATION=1 to run against the live stack", allow_module_level=True)

BOOKS = {"BHB-PLT-0001", "BHB-PLT-0007"}


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    db = tmp_path_factory.mktemp("chatdb") / "chat.db"
    return build_service(Settings(db={"url": f"sqlite:///{db}"}))


@pytest.mark.parametrize(
    "question,use_graph,expect_doc",
    [
        ("Auf welchen Servern läuft ZSD?", False, "BHB-PLT-0007"),
        ("Was war bei ZSDSUP-0247?", True, None),
        ("Was passiert, wenn Vault versiegelt ist?", True, None),
    ],
)
def test_smoke_questions_answer_with_citations(svc, question, use_graph, expect_doc):
    ctx = USERS["otto.ops"]
    conv = svc.start_conversation(ctx, use_graph=use_graph, doc_ids=None)
    res = svc.ask(ctx, conv.id, question, use_graph=use_graph).collect()
    print(f"\n[{question}] {res.finish_reason} {res.latency_ms} ms -> {res.answer[:160]!r}")
    assert res.finish_reason == "stop" and len(res.answer) > 40 and not res.guardrail
    assert res.citations and {c["doc_id"] for c in res.citations} <= BOOKS
    if expect_doc:
        assert any(c["doc_id"] == expect_doc for c in res.citations)
    assert "BHB-PLT-" in res.answer  # the model cites
    _, rows = svc.resume(ctx, conv.id)
    assert [r.role for r in rows] == ["user", "assistant"] and rows[1].diagnostics["llm_called"] is True
    assert rows[1].question_rewritten is None  # first turn: not rewritten


def test_follow_up_is_rewritten_and_both_forms_are_stored(svc):
    ctx = USERS["anna.admin"]
    conv = svc.start_conversation(ctx, use_graph=False, doc_ids=None)
    svc.ask(ctx, conv.id, "Wer ist für Vault zuständig?").collect()
    res = svc.ask(ctx, conv.id, "und bei Keycloak?").collect()
    print(f"\n[rewrite] {res.question_rewritten!r} -> {res.answer[:120]!r}")
    assert res.question_rewritten and "Keycloak" in res.question_rewritten
    rows = svc.resume(ctx, conv.id)[1]
    assert rows[-1].question_rewritten == res.question_rewritten and rows[-2].content == "und bei Keycloak?"


def test_off_topic_question_hits_the_guardrail_without_a_model_call(svc):
    ctx = USERS["otto.ops"]
    conv = svc.start_conversation(ctx, use_graph=True, doc_ids=None)
    res = svc.ask(ctx, conv.id, "Wie backe ich einen Apfelkuchen?").collect()
    assert res.guardrail and res.answer == NO_EVIDENCE_ANSWER and res.finish_reason == "guardrail"
    assert res.diagnostics["llm_called"] is False and res.citations == []


def test_readonly_user_only_gets_zsd_sources(svc):
    ctx = USERS["rita.read"]
    conv = svc.start_conversation(ctx, use_graph=True, doc_ids=None)
    res = svc.ask(ctx, conv.id, "Was war bei ZSDSUP-0247?").collect()
    assert res.citations and {c["doc_id"] for c in res.citations} == {"BHB-PLT-0007"}
    assert res.diagnostics["doc_ids"] == ["BHB-PLT-0007"]
    assert [d["doc_id"] for d in svc.documents(ctx)] == ["BHB-PLT-0007"]
