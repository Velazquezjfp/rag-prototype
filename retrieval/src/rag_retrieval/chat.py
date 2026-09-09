"""The answering side: OpenAI-compatible chat client (complete / stream), question rewriting from the last turns
(SPEC §8) and ``answer()``, which applies the guardrail before any model call (ADR-0011)."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from .llm_http import LLMClient, LLMHTTPError
from .models import Message, RetrievalResult, RewriteResult
from .prompt import NO_EVIDENCE_ANSWER, build_messages
from .settings import LLMSettings, PromptProfile

log = logging.getLogger(__name__)

__all__ = ["NO_EVIDENCE_ANSWER", "ChatClient", "Completion", "TokenStream", "answer", "rewrite_question"]


@dataclass
class Completion:
    text: str
    finish_reason: str | None = None  # "stop" | "length" (truncated: raise RAG__LLM__MAX_TOKENS) | ...
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"


class TokenStream:
    """The content deltas of one streamed completion; ``finish_reason`` is known once the iteration has ended.

    Consumers must stay duck-typed (``getattr(stream, "finish_reason", None)``): test fakes yield plain strings."""

    def __init__(self, events: Iterator[dict[str, Any]], *, max_tokens: int | None) -> None:
        self._events = events
        self._max_tokens = max_tokens
        self.finish_reason: str | None = None
        self.model: str | None = None

    def __iter__(self) -> Iterator[str]:
        for event in self._events:
            if event.get("model") and not self.model:
                self.model = event["model"]
            for choice in event.get("choices") or []:
                delta = (choice.get("delta") or {}).get("content")
                if delta:
                    yield delta
                reason = choice.get("finish_reason")
                if reason:
                    self.finish_reason = reason
                    if reason == "length":
                        log.warning("streamed answer truncated (finish_reason=length, max_tokens=%s)", self._max_tokens)

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"

    def close(self) -> None:
        close = getattr(self._events, "close", None)
        if close is not None:
            close()


REWRITE_SYSTEM_DE = (
    "Du formulierst die letzte Frage eines Gesprächs so um, dass sie ohne den Gesprächsverlauf verständlich ist. "
    "Ersetze Pronomen, Rückbezüge und Auslassungen durch die gemeinten Begriffe aus dem Verlauf; ändere sonst nichts "
    "und erfinde nichts. Ist die Frage bereits eigenständig verständlich, gib sie unverändert zurück. "
    "Antworte nur mit der Frage auf Deutsch, ohne Anführungszeichen, Einleitung oder Erklärung."
)
_HISTORY_MESSAGE_MAX_CHARS = 600


class ChatClient:
    def __init__(self, settings: LLMSettings, *, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.client = LLMClient(
            settings.base_url,
            settings.api_key,
            settings.timeout_s,
            max_attempts=settings.max_attempts,
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def _payload(
        self, messages: Sequence[Mapping[str, str]], *, model: str | None, max_tokens: int | None, temperature: float | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.settings.model,
            "messages": [dict(m) for m in messages],
            "temperature": self.settings.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.settings.max_tokens,
        }
        extra = getattr(self.settings, "extra_body", None)
        if extra:  # deployment knob (REQ-002 R9): e.g. {"think": false} switches Gemma's thinking off on Ollama
            payload.update({k: v for k, v in dict(extra).items() if k not in payload})
        return payload

    def complete_full(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Completion:
        """The answer with ``finish_reason`` and usage; ``length`` means the model ran out of ``max_tokens``
        (reasoning models spend part of that budget thinking before the first visible token)."""
        payload = self._payload(messages, model=model, max_tokens=max_tokens, temperature=temperature)
        resp = self.client.post_json("/chat/completions", payload)
        choices = resp.get("choices") or []
        if not choices:
            raise LLMHTTPError("chat completion without choices")
        content = (choices[0].get("message") or {}).get("content")
        out = Completion(
            text=(content or "").strip(),
            finish_reason=choices[0].get("finish_reason"),
            model=resp.get("model"),
            usage=dict(resp.get("usage") or {}),
        )
        if out.truncated:
            log.warning("answer truncated (finish_reason=length, max_tokens=%s); raise RAG__LLM__MAX_TOKENS", payload["max_tokens"])
        return out

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        return self.complete_full(messages, model=model, max_tokens=max_tokens, temperature=temperature).text

    def stream(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> TokenStream:
        """Content deltas as they arrive (SSE ``data:`` events); ``.finish_reason`` after the iteration
        (``length`` = truncated by ``max_tokens``)."""
        payload = self._payload(messages, model=model, max_tokens=max_tokens, temperature=temperature)
        payload["stream"] = True
        return TokenStream(self.client.post_sse("/chat/completions", payload), max_tokens=payload["max_tokens"])

    def probe(self) -> str:
        return self.client.probe()


def _as_message(m: Message | Mapping[str, Any]) -> Message:
    return m if isinstance(m, Message) else Message.model_validate(dict(m))


def rewrite_question(
    history: Sequence[Message | Mapping[str, Any]] | None,
    question: str,
    llm: ChatClient,
    *,
    max_turns: int = 2,
) -> RewriteResult:
    """Standalone form of a follow-up question from the last ``max_turns`` user/assistant pairs.

    No history → unchanged without a model call. Any model error or an implausible answer → the original."""
    turns = [_as_message(m) for m in (history or []) if _as_message(m).role in ("user", "assistant")]
    turns = turns[-2 * max_turns :]
    if not turns:
        return RewriteResult(original=question, rewritten=question, used_llm=False)
    lines = []
    for m in turns:
        who = "Nutzer" if m.role == "user" else "Assistent"
        content = " ".join(m.content.split())
        if len(content) > _HISTORY_MESSAGE_MAX_CHARS:
            content = content[: _HISTORY_MESSAGE_MAX_CHARS - 1] + "…"
        lines.append(f"{who}: {content}")
    user = "Gesprächsverlauf:\n" + "\n".join(lines) + f"\n\nLetzte Frage: {question}\n\nEigenständige Frage:"
    messages = [{"role": "system", "content": REWRITE_SYSTEM_DE}, {"role": "user", "content": user}]
    try:
        raw = llm.complete(messages, max_tokens=200, temperature=0.0)
    except (LLMHTTPError, httpx.HTTPError) as exc:
        log.warning("question rewrite failed, using the original: %s", exc)
        return RewriteResult(original=question, rewritten=question, used_llm=True, error=str(exc)[:300])
    rewritten = " ".join(raw.split())
    if "?" in rewritten:
        rewritten = rewritten[: rewritten.index("?") + 1]
    rewritten = rewritten.strip().strip('"„“\'').strip()
    if not rewritten or len(rewritten) > 3 * len(question) + 200:
        return RewriteResult(original=question, rewritten=question, used_llm=True, error="implausible rewrite")
    return RewriteResult(original=question, rewritten=rewritten, used_llm=True)


def answer(
    result: RetrievalResult,
    question: str,
    llm: ChatClient,
    history: Sequence[Message | Mapping[str, Any]] | None = None,
    *,
    stream: bool = False,
    force: bool = False,
    model: str | None = None,
    system_prompt: str | None = None,
    token_budget: int | None = None,
    max_facts: int | None = None,
    context_limit_tokens: int | None = None,
    max_history_turns: int = 3,
    doc_ids: Sequence[str] | None = None,
    profile: PromptProfile = "strict",
    material: str | None = None,
    ecosystem: str | None = None,
) -> str | Iterable[str]:
    """Guardrail first (ADR-0011, amended by REQ-001 R6): weak evidence on a *first* turn answers
    ``NO_EVIDENCE_ANSWER`` without a model call unless ``force``; on a follow-up (``history`` given) the model is
    called with the conversation and ``WEAK_FOLLOW_UP_NOTE_DE`` instead of the context. In the ``assistant`` profile
    (REQ-002 R5) the verdict never blocks: the model is always called and sees the ``Evidenzlage`` instead. The raw
    model output is returned — callers take the ``<einordnung>`` block off with ``analysis.AnalysisSplitter``."""
    weak_note = False
    if profile == "strict" and result.weak_evidence and not force:
        if not history:
            return iter([NO_EVIDENCE_ANSWER]) if stream else NO_EVIDENCE_ANSWER
        weak_note = True
    messages = build_messages(
        result,
        question,
        history,
        system_prompt=system_prompt,
        token_budget=token_budget,
        max_facts=max_facts,
        max_history_turns=max_history_turns,
        context_limit_tokens=context_limit_tokens,
        weak_note=weak_note,
        doc_ids=doc_ids,
        profile=profile,
        material=material,
        ecosystem=ecosystem,
    )
    if stream:
        return llm.stream(messages, model=model)
    return llm.complete(messages, model=model)
