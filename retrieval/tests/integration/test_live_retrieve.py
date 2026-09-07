"""Live, read-only checks against the local stack: OpenSearch with both manuals indexed, the embedding endpoint and
the chat model from .env. Gate: RAG_INTEGRATION=1. The ground truth is the table in REPORT.md."""

from __future__ import annotations

import os

import pytest

from rag_retrieval.chat import NO_EVIDENCE_ANSWER, ChatClient, answer, rewrite_question
from rag_retrieval.models import Message
from rag_retrieval.retriever import Retriever
from rag_retrieval.settings import Settings

pytestmark = pytest.mark.integration

if not os.environ.get("RAG_INTEGRATION"):
    pytest.skip("set RAG_INTEGRATION=1 to run against the live stack", allow_module_level=True)

ZSD, CAAS = "BHB-PLT-0007", "BHB-PLT-0001"


@pytest.fixture(scope="module")
def retriever() -> Retriever:
    s = Settings()
    if url := os.environ.get("RAG_INTEGRATION_URL"):
        s.opensearch.url = url
    return Retriever(s)


@pytest.fixture(scope="module")
def llm(retriever) -> ChatClient:
    return ChatClient(retriever.settings.llm)


def _pages(result, doc_id: str) -> set[int]:
    return {p for g in result.groups if g.doc_id == doc_id for p in g.pages}


def test_check_ok(retriever):
    report = retriever.check()
    assert report["ok"], report
    assert {d["doc_id"] for d in report["documents"]} >= {ZSD, CAAS}
    assert report["graph"]["shared_node_ids"] >= 60


def test_embedding_dimension(retriever):
    vec = retriever.embedder.embed("Was passiert, wenn Vault versiegelt ist?")
    assert len(vec) == retriever.settings.embedding.dim == 1024


def test_q1_iam_responsibility(retriever):
    res = retriever.retrieve("Wer ist für IAM/Keycloak zuständig und wie eskaliere ich?", use_graph=True)
    assert not res.weak_evidence
    assert _pages(res, ZSD) & {1, 2, 26, 6}
    assert any(f.source_label == "Kai Ostermann" and f.relation == "ESCALATES_TO" and "Reuß" in f.target_label for f in res.facts)
    assert any(c.label.endswith("Ostermann") or "Ostermann" in c.aliases for c in res.entities)


def test_q2_vault_sealed_negatives_and_vpp_unaffected(retriever):
    fast = retriever.retrieve("Was passiert, wenn Vault versiegelt ist?", use_graph=False)
    assert not fast.weak_evidence and fast.facts == []
    assert (_pages(fast, CAAS) | _pages(fast, ZSD)) & {12, 15, 19, 22}
    slow = retriever.retrieve("Was passiert, wenn Vault versiegelt ist?", use_graph=True)
    negatives = {(f.source_label, f.target_label) for f in slow.facts if f.polarity == "negative"}
    assert ("Vault", "PKI") in negatives and ("Vault", "Keycloak") in negatives
    assert slow.facts[0].polarity == "negative" and "NICHT" in slow.facts[0].rendered
    vpp = [c for c in slow.entities if c.type == "ImpactStatement" and "VPP" in c.label and "Vault versiegelt" in c.label]
    assert vpp and all("severity: keine" in c.rendered for c in vpp)
    assert 19 in _pages(slow, ZSD) or 19 in _pages(slow, CAAS)


def test_q3_ticket_identifier_channel(retriever):
    res = retriever.retrieve("Was war bei ZSDSUP-0247?", use_graph=False)
    chans = {c.channel: c for c in res.diagnostics.channels}
    assert chans["identifier"].returned >= 5 and res.diagnostics.identifiers == ["ZSDSUP-0247"]
    assert _pages(res, ZSD) & {22, 23} and _pages(res, CAAS) & {21, 23}
    slow = retriever.retrieve("Was war bei ZSDSUP-0247?", use_graph=True)
    partners = {f.target_label for f in slow.facts if f.relation == "PARTNER_TICKET" and f.source_label == "ZSDSUP-0247"}
    assert {"CAASUP-0351", "DDSUP-1201"} <= partners
    assert any(c.type == "Incident" and c.label == "ZSDSUP-0247" for c in slow.entities)


def test_q4_cold_start_order(retriever):
    res = retriever.retrieve("In welcher Reihenfolge fährt der Verbund nach einem Totalausfall an?", use_graph=True)
    precedes = [f for f in res.facts if f.relation == "PRECEDES"]
    assert len(precedes) >= 8 and res.facts[0].relation == "PRECEDES"
    assert 20 in _pages(res, CAAS)


def test_q5_tables_grouped(retriever):
    res = retriever.retrieve("Auf welchen Servern und Ports läuft ZSD?", use_graph=False)
    ports = next(g for g in res.groups if g.caption and g.caption.startswith("Tabelle 5"))
    assert len(ports.parts) == 3 and set(ports.pages) == {9, 10} and ports.doc_id == ZSD
    assert ports.rank == 1


def test_q6_unseal(retriever):
    res = retriever.retrieve("Wer darf Vault entsiegeln und wie?", use_graph=True)
    assert 15 in _pages(res, ZSD)
    assert res.facts[0].source_label == "Marcel Ebert" and res.facts[0].target_label == "SOP-ZSD-05"
    assert "Vault" in res.diagnostics.resolved_labels


def test_q7_dispatcher(retriever):
    res = retriever.retrieve("Ich will den Dispatcher neu starten – was hängt daran?", use_graph=True)
    assert "Dispatcher" in res.diagnostics.resolved_labels
    assert any("Neustart des Dispatchers scheitert" in f.rendered for f in res.facts)
    assert res.diagnostics.partial_labels == []  # "neu starten" alone must not pull in the API-Server statements
    assert _pages(res, ZSD) & {11, 12, 19}


def test_q8_tls_renewal(retriever):
    res = retriever.retrieve("Wie erneuere ich ein TLS-Zertifikat?", use_graph=True)
    assert not res.weak_evidence
    assert 16 in _pages(res, CAAS) and _pages(res, ZSD) & {15, 16, 17}


def test_guardrail_off_topic_never_calls_the_model(retriever, llm):
    res = retriever.retrieve("Wie backe ich einen Apfelkuchen?", use_graph=True)
    assert res.weak_evidence and res.facts == [] and res.entities == []
    assert answer(res, "Wie backe ich einen Apfelkuchen?", llm) == NO_EVIDENCE_ANSWER


def test_rewrite_follow_up(llm):
    history = [Message(role="user", content="Wer ist für Vault zuständig?"), Message(role="assistant", content="Marcel Ebert (ZSD) ist für Vault verantwortlich [BHB-PLT-0001 S. 18].")]
    rw = rewrite_question(history, "und bei Keycloak?", llm)
    assert rw.used_llm and rw.error is None, rw
    low = rw.rewritten.lower()
    assert "keycloak" in low and ("zuständig" in low or "verantwortlich" in low)


def test_answer_vault_with_citations(retriever, llm):
    res = retriever.retrieve("Was passiert, wenn Vault versiegelt ist?", use_graph=True)
    text = answer(res, "Was passiert, wenn Vault versiegelt ist?", llm, token_budget=retriever.settings.retrieval.context_token_budget, max_facts=retriever.settings.retrieval.max_facts_in_prompt)
    assert isinstance(text, str) and "[BHB-PLT-" in text and text != NO_EVIDENCE_ANSWER
    assert "VPP" in text or "Verfahrensportal" in text
