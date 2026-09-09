"""Fixtures: in-memory SQLite (or CHAT_TEST_DB_URL, e.g. Postgres) with the Alembic schema, a Repository, fakes for
the retriever and the LLM, the mock users and a ChatService wired from them. No services are contacted."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from rag_retrieval import (
    ChannelEvidence,
    ChannelStats,
    ChunkGroup,
    ChunkHit,
    Citation,
    Diagnostics,
    EntityCard,
    EntityOccurrence,
    GraphFact,
    RetrievalResult,
)
from rag_users import USERS, AuthContext, GroupLimits, Policy
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from chat_system.db import ensure_schema, make_engine, make_session_factory  # noqa: E402
from chat_system.models import Base  # noqa: E402
from chat_system.repository import Repository  # noqa: E402
from chat_system.service import ChatService  # noqa: E402
from chat_system.settings import Settings  # noqa: E402

ZSD = "BHB-PLT-0007"
CAAS = "BHB-PLT-0001"
TODAY = date(2026, 9, 4)
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("CHAT__", "USERS__")) or key in ("CHAT_CONFIG",):
            monkeypatch.delenv(key)


# ---------------------------------------------------------------------------------------------------- db


@pytest.fixture(scope="session")
def engine():
    url = os.environ.get("CHAT_TEST_DB_URL")
    if url:
        eng = make_engine(url)
        with eng.begin() as conn:
            Base.metadata.drop_all(conn)
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    else:
        eng = make_engine("sqlite://")  # StaticPool + the pragmas (foreign keys on)
    ensure_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def clean_tables(engine):
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def repo(engine, clean_tables, clock) -> Repository:
    return Repository(make_session_factory(engine), clock=clock)


# ------------------------------------------------------------------------------------------------- fakes


def make_result(question: str, *, weak: bool = False, mode: str = "slow", doc_ids: list[str] | None = None) -> RetrievalResult:
    docs = doc_ids or [ZSD, CAAS]
    chunks: list[ChunkHit] = []
    if ZSD in docs:
        chunks.append(
            ChunkHit(
                chunk_id="zsd-0019", doc_id=ZSD, doc_title="Betriebshandbuch ZSD", kind="text", page_numbers=[19],
                heading_breadcrumb=["5 Betrieb", "5.4 Vault"], body_text="Vault hängt nicht von PKI oder Keycloak ab (Unseal).",
                text="Vault hängt nicht von PKI oder Keycloak ab (Unseal).", token_count=40, node_ids=["n-vault"],
                rank=1, fused_score=0.05, group_key="zsd-0019",
                channels=[ChannelEvidence(channel="knn", rank=1), ChannelEvidence(channel="bm25", rank=2)],
            )
        )
    if CAAS in docs:
        chunks.append(
            ChunkHit(
                chunk_id="caas-0015", doc_id=CAAS, doc_title="Betriebshandbuch CaaS", kind="table", page_numbers=[15],
                caption="Tabelle 12: Auswirkungen", body_text="| System | Auswirkung |\n| VPP | keine |",
                text="| System | Auswirkung |\n| VPP | keine |", token_count=30, rank=2, fused_score=0.03, group_key=f"{CAAS}|Tabelle 12",
                channels=[ChannelEvidence(channel="bm25", rank=1)],
            )
        )
    groups = [
        ChunkGroup(key=c.group_key, doc_id=c.doc_id, doc_title=c.doc_title, kind=c.kind, caption=c.caption,
                   heading_breadcrumb=c.heading_breadcrumb, pages=c.page_numbers, chunk_ids=[c.chunk_id], parts=[c],
                   rank=c.rank, fused_score=c.fused_score)
        for c in chunks
    ]
    facts = []
    entities = []
    if mode == "slow" and not weak and ZSD in docs:
        facts.append(
            GraphFact(edge_id="e-vault-pki", doc_ids=[ZSD], source_id="n-vault", source_label="Vault", source_type="System",
                      relation="DEPENDS_ON", relation_de="hängt ab von", target_id="n-pki", target_label="PKI", target_type="System",
                      polarity="negative", qualifier="für Vault-Unseal", quote="Vault hängt nicht von PKI ab.", pages=[19],
                      chunk_ids=["zsd-0019"], via_start_node="n-vault", rendered="Vault —DEPENDS_ON (hängt ab von)→ PKI: NICHT (für Vault-Unseal)")
        )
        entities.append(
            EntityCard(node_ids=["n-vpp-impact"], type="ImpactStatement", label="Vault versiegelt | VPP", matched_by="label",
                       occurrences=[EntityOccurrence(doc_id=CAAS, label="Vault versiegelt | VPP", attributes={"severity": "keine"}, pages=[19])],
                       rendered="Vault versiegelt | VPP (ImpactStatement) — severity: keine [BHB-PLT-0001 S. 19]")
        )
    citations = [Citation(key=f"{g.doc_id} S. {g.pages[0]}", doc_id=g.doc_id, doc_title=g.doc_title, pages=g.pages, chunk_ids=g.chunk_ids) for g in groups]
    for f in facts:
        citations.append(Citation(key=f"{ZSD} S. 19", doc_id=ZSD, doc_title="Betriebshandbuch ZSD", pages=[19], chunk_ids=f.chunk_ids, edge_ids=[f.edge_id]))
    diag = Diagnostics(
        question=question, mode=mode, identifiers=[], resolved_labels=["Vault"] if not weak else [],
        channels=[ChannelStats(channel="knn", requested_k=20, returned=20, took_ms=5), ChannelStats(channel="bm25", requested_k=20, returned=0 if weak else 7, took_ms=3)],
        timings_ms={"analyze": 0, "embed": 200, "search": 8, "fuse": 0, "total": 210}, embedding_model="bge-m3",
    )
    # like the real retriever, a weak result still carries the kNN chunks and their citations (kNN always returns k)
    return RetrievalResult(
        question=question, mode=mode, chunks=chunks, groups=groups, facts=facts, entities=entities,
        citations=citations, weak_evidence=weak, weak_evidence_reason="no lexical overlap with the corpus" if weak else None,
        diagnostics=diag,
    )


class FakeRetriever:
    def __init__(self, *, weak: bool = False, fail: Exception | None = None) -> None:
        self.weak = weak
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def retrieve(self, question: str, *, use_graph: bool = True, k: int | None = None, doc_ids=None, **kwargs: Any) -> RetrievalResult:
        call: dict[str, Any] = {"question": question, "use_graph": use_graph, "k": k, "doc_ids": list(doc_ids) if doc_ids else None}
        if "material" in kwargs:  # REQ-002 R4: recorded only when the service passed it (existing exact-call asserts stay)
            call["material"] = kwargs["material"]
        self.calls.append(call)
        if self.fail is not None:
            raise self.fail
        return make_result(question, weak=self.weak, mode="slow" if use_graph else "fast", doc_ids=list(doc_ids) if doc_ids else None)

    def ecosystem_summary(self, doc_ids=None) -> str:
        docs = [d for d in (ZSD, CAAS) if not doc_ids or d in doc_ids]
        titles = {ZSD: "Betriebshandbuch ZSD", CAAS: "Betriebshandbuch CaaS-Plattform"}
        return "\n".join(f"- {d} „{titles[d]}“: Systeme: Vault" for d in docs)


class FakeLLMSettings:
    model = "fake-llm"


class FakeLLM:
    """Duck-typed rag_retrieval.ChatClient: ``complete`` answers the rewrite prompt, ``stream`` yields the answer."""

    def __init__(self, reply: str = "Vault ist versiegelt: Secrets sind nicht lesbar [BHB-PLT-0007 S. 19].", *, rewrite_reply: str = "Wer ist für Keycloak zuständig?", fail: Exception | None = None, fail_after: int | None = None) -> None:
        self.reply = reply
        self.rewrite_reply = rewrite_reply
        self.fail = fail
        self.fail_after = fail_after
        self.settings = FakeLLMSettings()
        self.complete_calls: list[list[dict[str, str]]] = []
        self.stream_calls: list[list[dict[str, str]]] = []

    def complete(self, messages, *, model=None, max_tokens=None, temperature=None) -> str:
        self.complete_calls.append([dict(m) for m in messages])
        return self.rewrite_reply

    def stream(self, messages, *, model=None, max_tokens=None, temperature=None) -> Iterator[str]:
        self.stream_calls.append([dict(m) for m in messages])
        if self.fail is not None and self.fail_after is None:
            raise self.fail
        for i, tok in enumerate(self.reply.split(" ")):
            if self.fail is not None and self.fail_after is not None and i >= self.fail_after:
                raise self.fail
            yield tok + " "

    def probe(self) -> str:
        return "ok"

    def close(self) -> None:
        pass


CATALOG = [
    {"doc_id": CAAS, "title": "Betriebshandbuch CaaS-Plattform", "version": "1.4", "root_system": "CaaS", "pages": 30, "counts": {}},
    {"doc_id": ZSD, "title": "Betriebshandbuch ZSD", "version": "2.3", "root_system": "ZSD", "pages": 31, "counts": {}},
]


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, db={"url": "sqlite://"}, limits={"max_concurrent_answers": 10})


@pytest.fixture
def retriever() -> FakeRetriever:
    return FakeRetriever()


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def policy() -> Policy:
    return Policy()


@pytest.fixture
def service(repo, policy, retriever, llm, settings, clock) -> ChatService:
    return ChatService(repo, policy, retriever, llm, settings, catalog=lambda: list(CATALOG), clock=clock)


def make_service(repo, *, retriever=None, llm=None, settings=None, policy=None, clock=None, catalog=None, profile=None) -> ChatService:
    return ChatService(
        repo,
        policy or Policy(),
        retriever or FakeRetriever(),
        llm or FakeLLM(),
        settings or Settings(_env_file=None, db={"url": "sqlite://"}),
        catalog=catalog or (lambda: list(CATALOG)),
        clock=clock or Clock(),
        profile=profile,
    )


@pytest.fixture
def dev() -> AuthContext:
    return USERS["dev"]


@pytest.fixture
def otto() -> AuthContext:
    return USERS["otto.ops"]


@pytest.fixture
def rita() -> AuthContext:
    return USERS["rita.read"]


@pytest.fixture
def anna() -> AuthContext:
    return USERS["anna.admin"]


def tiny_policy(daily: int = 3, turns: int = 2) -> Policy:
    return Policy({"bavd-ops": GroupLimits(daily_messages=daily, max_turns_per_conversation=turns, allowed_doc_ids=None)})
