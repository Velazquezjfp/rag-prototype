"""The chat backend: policy → reservation → rewrite → retrieve → guardrail → stream → persist.

Never imports streamlit (tests enforce it). ``retriever`` and ``llm`` are duck-typed (rag-retrieval's ``Retriever``
and ``ChatClient`` in production, fakes in tests); the result types come from ``rag_retrieval`` directly.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from rag_retrieval import NO_EVIDENCE_ANSWER, RetrievalResult, build_messages, rewrite_question
from rag_users import REASON_TEXT_DE, AuthContext, Decision, Policy

from .db import utcnow
from .models import Conversation, Message
from .repository import Repository
from .settings import Settings

log = logging.getLogger(__name__)

RefusalReason = Literal["daily_cap", "turn_cap", "forbidden", "busy"]

BUSY_TEXT_DE = "Gerade sind zu viele Anfragen gleichzeitig in Arbeit. Bitte in einem Moment noch einmal senden."
ERROR_TEXT_DE = "Die Antwort konnte nicht erzeugt werden (Fehler beim Sprachmodell). Die Nachricht wurde nicht gezählt."
FORBIDDEN_CONVERSATION_DE = "Dieses Gespräch gehört einem anderen Benutzer."


class TurnRefused(Exception):
    def __init__(self, reason: RefusalReason, message_de: str, remaining_today: int) -> None:
        super().__init__(f"{reason}: {message_de}")
        self.reason = reason
        self.message_de = message_de
        self.remaining_today = remaining_today


@dataclass(frozen=True)
class Quota:
    used_today: int
    daily_cap: int
    max_turns: int

    @property
    def remaining_today(self) -> int:
        return max(0, self.daily_cap - self.used_today)


@dataclass
class TurnResult:
    conversation_id: str
    message_id: int | None
    answer: str
    citations: list[dict[str, Any]]
    facts: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    guardrail: bool
    question_raw: str
    question_rewritten: str | None
    use_graph: bool
    finish_reason: str | None
    latency_ms: int | None
    remaining_today: int
    turns_left: int


@dataclass
class _Turn:
    """Everything ``ask()`` prepared before the model is called."""

    ctx: AuthContext
    conversation_id: str
    question_raw: str
    question_rewritten: str | None
    use_graph: bool
    doc_ids: list[str] | None
    decision: Decision
    result: RetrievalResult
    messages: list[dict[str, str]] | None  # None -> guardrail, model not called
    model: str | None
    timings_ms: dict[str, int] = field(default_factory=dict)
    prompt_chars: int = 0
    used_today: int = 0
    turns_in_conversation: int = 0


SNIPPET_CHARS = 240


def enrich_citations(result: RetrievalResult) -> list[dict[str, Any]]:
    """``Citation.model_dump()`` + what the UI shows next to it: breadcrumb/caption, channels and a snippet of the
    source group (or the rendered fact for edge citations). Persisted with the assistant row, so replay = live."""
    by_chunk: dict[str, Any] = {}
    for g in result.groups:
        for cid in g.chunk_ids:
            by_chunk.setdefault(cid, g)
    by_edge = {f.edge_id: f for f in result.facts}
    out: list[dict[str, Any]] = []
    for c in result.citations:
        d = c.model_dump()
        group = next((by_chunk[cid] for cid in c.chunk_ids if cid in by_chunk), None)
        if group is not None:
            d["breadcrumb"] = " › ".join(group.heading_breadcrumb) if group.heading_breadcrumb else (group.caption or "")
            d["kind"] = group.kind
            d["channels"] = group.channel_names
            text = " ".join((group.parts[0].body_text or group.parts[0].text or "").split()) if group.parts else ""
            d["snippet"] = text[:SNIPPET_CHARS] + ("…" if len(text) > SNIPPET_CHARS else "")
        facts = [by_edge[e] for e in c.edge_ids if e in by_edge]
        if facts:
            d["facts"] = [f.rendered for f in facts[:3]]
            d.setdefault("channels", ["graph"])
            d.setdefault("snippet", facts[0].quote or "")
        out.append(d)
    return out


class TurnStream:
    """The answer as it streams. ``tokens()`` is what ``st.write_stream`` consumes; ``collect()`` for CLI/tests.

    Persists the assistant row exactly once: ``finish_reason`` ``stop`` (complete), ``guardrail`` (canned sentence,
    model not called), ``aborted`` (the consumer stopped early — partial text kept), ``error`` (the model failed —
    usage refunded). ``abort()`` is idempotent; the UI calls it in ``finally``.
    """

    def __init__(self, svc: ChatService, turn: _Turn) -> None:
        self._svc = svc
        self._turn = turn
        self._text: list[str] = []
        self._first_token_ms: int | None = None
        self._t0 = time.perf_counter()
        self._lock = threading.Lock()
        self.done = False
        self.finish_reason: str | None = None
        self.message_id: int | None = None
        self.llm_called = False
        self._stream_ms: int | None = None

    # ---- what the UI may read before/while streaming
    @property
    def conversation_id(self) -> str:
        return self._turn.conversation_id

    @property
    def result(self) -> RetrievalResult:
        return self._turn.result

    @property
    def guardrail(self) -> bool:
        return self._turn.messages is None

    @property
    def question_rewritten(self) -> str | None:
        return self._turn.question_rewritten

    @property
    def use_graph(self) -> bool:
        return self._turn.use_graph

    @property
    def citations(self) -> list[dict[str, Any]]:
        # a guardrail answer cites nothing: the kNN channel always returns chunks, but none of them is evidence
        return [] if self.guardrail else enrich_citations(self._turn.result)

    @property
    def facts(self) -> list[dict[str, Any]]:
        return [f.model_dump() for f in self._turn.result.facts]

    @property
    def answer(self) -> str:
        return "".join(self._text)

    @property
    def diagnostics(self) -> dict[str, Any]:
        t = self._turn
        timings = dict(t.timings_ms)
        if self._first_token_ms is not None:
            timings["first_token"] = self._first_token_ms
        if self._stream_ms is not None:
            timings["stream"] = self._stream_ms
            timings["total"] = self._stream_ms + t.timings_ms.get("rewrite", 0) + t.timings_ms.get("retrieve", 0)
        return {
            **t.result.diagnostics.model_dump(),
            "rewritten_question": t.question_rewritten,
            "use_graph": t.use_graph,
            "doc_ids": t.doc_ids,
            "weak_evidence": t.result.weak_evidence,
            "weak_evidence_reason": t.result.weak_evidence_reason,
            "llm_called": self.llm_called,
            "model": t.model,
            "timings_ms": timings,
            "prompt_chars": t.prompt_chars,
            "facts": self.facts,
            "entities": [e.rendered for e in t.result.entities],
            "finish_reason": self.finish_reason,
        }

    # ---- streaming
    def tokens(self) -> Iterator[str]:
        if self.done:
            yield self.answer
            return
        t = self._turn
        if t.messages is None:
            self._text.append(NO_EVIDENCE_ANSWER)
            yield NO_EVIDENCE_ANSWER
            self._finish("guardrail")
            return
        self.llm_called = True
        try:
            for delta in self._svc.llm.stream(t.messages):
                if self._first_token_ms is None:
                    self._first_token_ms = int((time.perf_counter() - self._t0) * 1000)
                self._text.append(delta)
                yield delta
        except GeneratorExit:
            self._finish("aborted")
            raise
        except Exception as exc:  # noqa: BLE001 - the model failed: persist, refund, tell the caller
            log.warning("LLM stream failed for conversation %s: %s", t.conversation_id, exc)
            self._finish("error", error=exc)
            raise
        self._finish("stop")

    def abort(self) -> None:
        if not self.done:
            self._finish("aborted")

    def collect(self) -> TurnResult:
        for _ in self.tokens():
            pass
        return self.to_result()

    def to_result(self) -> TurnResult:
        t = self._turn
        limits = t.decision.limits
        return TurnResult(
            conversation_id=t.conversation_id,
            message_id=self.message_id,
            answer=self.answer,
            citations=self.citations,
            facts=self.facts,
            diagnostics=self.diagnostics,
            guardrail=self.guardrail,
            question_raw=t.question_raw,
            question_rewritten=t.question_rewritten,
            use_graph=t.use_graph,
            finish_reason=self.finish_reason,
            latency_ms=self.diagnostics["timings_ms"].get("total"),
            remaining_today=max(0, limits.daily_messages - t.used_today),
            turns_left=max(0, limits.max_turns_per_conversation - (t.turns_in_conversation + 1)),
        )

    # ---- persistence (once)
    def _finish(self, reason: str, *, error: Exception | None = None) -> None:
        with self._lock:
            if self.done:
                return
            self.done = True
            self.finish_reason = reason
            self._stream_ms = int((time.perf_counter() - self._t0) * 1000)
        t = self._turn
        svc = self._svc
        try:
            content = self.answer
            if reason == "error":
                content = content or ERROR_TEXT_DE
                svc.repo.usage().increment(t.ctx.user_id, svc.today(), by=-1)
                t.used_today = max(0, t.used_today - 1)
            diagnostics = self.diagnostics
            if error is not None:
                diagnostics["error"] = str(error)[:500]
            row = svc.repo.add_assistant_message(
                t.conversation_id,
                content,
                question_rewritten=t.question_rewritten,
                use_graph=t.use_graph,
                citations=self.citations,
                diagnostics=diagnostics,
                guardrail=self.guardrail,
                finish_reason=reason,
                model=t.model if self.llm_called else None,
                latency_ms=diagnostics["timings_ms"].get("total"),
            )
            self.message_id = row.id
            if t.turns_in_conversation + 1 >= t.decision.limits.max_turns_per_conversation:
                svc.repo.mark_capped(t.conversation_id)
        finally:
            svc.release()


class ChatService:
    def __init__(
        self,
        repo: Repository,
        policy: Policy,
        retriever: Any,
        llm: Any,
        settings: Settings,
        *,
        rag_settings: Any | None = None,
        catalog: Callable[[], list[dict[str, Any]]] | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.repo = repo
        self.policy = policy
        self.retriever = retriever
        self.llm = llm
        self.settings = settings
        self.rag_settings = rag_settings
        self._catalog = catalog
        self._clock = clock
        self._semaphore = threading.BoundedSemaphore(max(1, settings.limits.max_concurrent_answers))

    # ------------------------------------------------------------------ helpers
    def today(self):
        return self._clock().date()

    def release(self) -> None:
        try:
            self._semaphore.release()
        except ValueError:  # released more often than acquired: never happens, never fatal
            log.error("semaphore over-released")

    @property
    def model_name(self) -> str | None:
        if self.rag_settings is not None:
            return getattr(getattr(self.rag_settings, "llm", None), "model", None)
        return getattr(getattr(self.llm, "settings", None), "model", None)

    # -------------------------------------------------------------------- reads
    def documents(self, ctx: AuthContext) -> list[dict[str, Any]]:
        """Indexed manuals the user may read (catalog ∩ policy allowlist)."""
        docs = list(self._catalog()) if self._catalog is not None else []
        allowed = self.policy.limits_for(ctx).allowed_doc_ids
        if allowed is None:
            return docs
        return [d for d in docs if d["doc_id"] in allowed]

    def quota(self, ctx: AuthContext) -> Quota:
        limits = self.policy.limits_for(ctx)
        used = self.repo.usage().count(ctx.user_id, self.today())
        return Quota(used_today=used, daily_cap=limits.daily_messages, max_turns=limits.max_turns_per_conversation)

    def list_conversations(self, ctx: AuthContext) -> list[Conversation]:
        return self.repo.list_conversations(ctx.user_id, limit=self.settings.ui.conversation_list_limit)

    def resume(self, ctx: AuthContext, conversation_id: str) -> tuple[Conversation, list[Message]]:
        conv = self.repo.get_conversation(conversation_id, ctx.user_id)
        if conv is None:
            raise TurnRefused("forbidden", FORBIDDEN_CONVERSATION_DE, self.quota(ctx).remaining_today)
        return conv, self.repo.list_messages(conversation_id)

    def start_conversation(self, ctx: AuthContext, *, use_graph: bool, doc_ids: Sequence[str] | None) -> Conversation:
        return self.repo.create_conversation(ctx.user_id, use_graph=use_graph, doc_ids=doc_ids)

    # --------------------------------------------------------------------- ask
    def ask(
        self,
        ctx: AuthContext,
        conversation_id: str,
        question: str,
        *,
        use_graph: bool | None = None,
        doc_ids: Sequence[str] | None = None,
    ) -> TurnStream:
        question = " ".join(question.split())
        if not question:
            raise ValueError("empty question")
        conv = self.repo.get_conversation(conversation_id, ctx.user_id)
        if conv is None:
            raise TurnRefused("forbidden", FORBIDDEN_CONVERSATION_DE, self.quota(ctx).remaining_today)
        if use_graph is None:
            use_graph = bool(conv.use_graph_default)
        requested = list(doc_ids) if doc_ids else (list(conv.doc_ids) if conv.doc_ids else None)

        # (1) policy: nothing persisted, nothing counted on a refusal
        today = self.today()
        turns = int(conv.turn_count or 0)
        decision = self.policy.check_message(
            ctx, self.repo.usage(), today=today, turns_in_conversation=turns, requested_doc_ids=requested
        )
        if conv.status == "capped" and decision.allowed:
            decision = decision.model_copy(update={"allowed": False, "reason": "turn_cap"})
        if not decision.allowed:
            if decision.reason == "turn_cap" and conv.status != "capped":
                self.repo.mark_capped(conversation_id)
            raise TurnRefused(decision.reason, decision.message_de or REASON_TEXT_DE[decision.reason], decision.remaining_today)  # type: ignore[arg-type]

        # (2) concurrency
        if not self._semaphore.acquire(blocking=False):
            raise TurnRefused("busy", BUSY_TEXT_DE, decision.remaining_today)

        reserved = False
        try:
            # (3) reservation + user message in one transaction
            history_rows = self.repo.list_messages(conversation_id)
            _user_msg, used = self.repo.begin_turn(conversation_id, question, user_id=ctx.user_id, day=today)
            reserved = True
            history = [{"role": m.role, "content": m.content} for m in history_rows if m.role in ("user", "assistant")]

            # (4) rewrite from the last turns (SPEC §8)
            timings: dict[str, int] = {}
            rewritten: str | None = None
            if history:
                t0 = time.perf_counter()
                rw = rewrite_question(history, question, self.llm, max_turns=self.settings.retrieval.history_turns_for_rewrite)
                timings["rewrite"] = int((time.perf_counter() - t0) * 1000)
                if rw.rewritten and rw.rewritten != question:
                    rewritten = rw.rewritten
            effective_question = rewritten or question

            # (5) retrieve with the effective document filter
            k = self.settings.retrieval.k_graph if use_graph else self.settings.retrieval.k
            effective_doc_ids = list(decision.doc_ids) if decision.doc_ids else None
            t0 = time.perf_counter()
            result: RetrievalResult = self.retriever.retrieve(
                effective_question, use_graph=use_graph, k=k, doc_ids=effective_doc_ids
            )
            timings["retrieve"] = int((time.perf_counter() - t0) * 1000)

            # (6) guardrail or prompt
            messages: list[dict[str, str]] | None = None
            prompt_chars = 0
            if not result.weak_evidence:
                kwargs: dict[str, Any] = {}
                if self.rag_settings is not None:
                    kwargs["context_limit_tokens"] = self.rag_settings.llm.context_limit_tokens
                    kwargs["token_budget"] = self.rag_settings.retrieval.context_token_budget
                    kwargs["max_facts"] = self.rag_settings.retrieval.max_facts_in_prompt
                messages = build_messages(result, question, history, **kwargs)
                prompt_chars = sum(len(m["content"]) for m in messages)
        except BaseException as exc:
            self._fail_before_stream(ctx, conversation_id, use_graph, exc, today, reserved=reserved)
            raise

        turn = _Turn(
            ctx=ctx,
            conversation_id=conversation_id,
            question_raw=question,
            question_rewritten=rewritten,
            use_graph=use_graph,
            doc_ids=effective_doc_ids,
            decision=decision,
            result=result,
            messages=messages,
            model=self.model_name,
            timings_ms=timings,
            prompt_chars=prompt_chars,
            used_today=used,
            turns_in_conversation=turns,
        )
        return TurnStream(self, turn)

    def _fail_before_stream(
        self, ctx: AuthContext, conversation_id: str, use_graph: bool, exc: BaseException, today, *, reserved: bool
    ) -> None:
        """Retrieval/prompt failed: if the slot was reserved, keep the user's message, add an error row and refund."""
        log.warning("turn failed before streaming for %s: %s", conversation_id, exc)
        try:
            if reserved:
                self.repo.usage().increment(ctx.user_id, today, by=-1)
                self.repo.add_assistant_message(
                    conversation_id,
                    ERROR_TEXT_DE,
                    question_rewritten=None,
                    use_graph=use_graph,
                    citations=[],
                    diagnostics={"error": str(exc)[:500], "llm_called": False},
                    guardrail=False,
                    finish_reason="error",
                    model=None,
                    latency_ms=None,
                )
        finally:
            self.release()
