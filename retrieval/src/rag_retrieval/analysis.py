"""The prompt-level chain of thought of the assistant profile (REQ-002 R2/R6): the model opens every answer with a
short ``<einordnung>…</einordnung>`` block (task, scope, systems, basis). ``AnalysisSplitter`` takes that block off a
token stream — buffering only while the text can still be the block — parses it into an ``Analysis`` and streams the
rest; ``split_analysis`` does the same for a complete text. Both are tolerant: no block, a malformed block or an
unclosed block yield the text unchanged with ``analysis=None``."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

__all__ = ["BASES", "CLOSE", "OPEN", "TASKS", "Analysis", "AnalysisSplitter", "parse_analysis", "split_analysis"]

OPEN = "<einordnung>"
CLOSE = "</einordnung>"
TASKS: tuple[str, ...] = ("Erklärung", "Loganalyse", "Skript", "Befehle", "Verfahren", "Kontakt", "Sonstiges")
BASES: tuple[str, ...] = ("Handbücher", "Verlauf", "Fachwissen")
_OUT_OF_SCOPE = ("außerhalb", "ausserhalb")
_LEADING_FENCE_RE = re.compile(r"^```[^\n]*\n")
_BARE_CLOSING_FENCE_RE = re.compile(r"^\s*```[ \t]*(?:\n|$)")
_PARTIAL_FENCE_RE = re.compile(r"\s*`{0,3}")  # what may still become a bare closing fence while streaming


@dataclass
class Analysis:
    raw: str
    fields: dict[str, str] = field(default_factory=dict)
    task: str = "Sonstiges"
    in_scope: bool = True
    systems: str | None = None
    basis: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"task": self.task, "in_scope": self.in_scope, "systems": self.systems, "basis": list(self.basis), "fields": dict(self.fields), "raw": self.raw}

    def summary_de(self) -> str:
        """One line for the UI caption and the CLI: ``Aufgabe: Skript · Bereich: innerhalb · System: ZSD · Grundlage: …``."""
        bits = [f"Aufgabe: {self.task}", f"Bereich: {'innerhalb' if self.in_scope else 'außerhalb'}"]
        if self.systems:
            bits.append(f"System: {self.systems}")
        if self.basis:
            bits.append("Grundlage: " + ", ".join(self.basis))
        return " · ".join(bits)


def parse_analysis(block: str) -> Analysis:
    """``Key: value`` lines (case-insensitive keys); unknown task words fall back to ``Sonstiges``, ``System: unklar``
    becomes ``None``, the basis is the subset of ``BASES`` named in ``Grundlage``."""
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().casefold(), value.strip()
        if key and value and key not in fields:
            fields[key] = value
    task_text = fields.get("aufgabe", "").casefold()
    task = next((t for t in TASKS if t.casefold() in task_text), "Sonstiges")
    scope_text = fields.get("bereich", "").casefold()
    in_scope = not any(word in scope_text for word in _OUT_OF_SCOPE)
    systems = fields.get("system") or None
    if systems and systems.strip("„“\"' .").casefold() in ("unklar", "-", "–", "keins", "keines", "none"):
        systems = None
    basis_text = fields.get("grundlage", "").casefold()
    basis = [b for b in BASES if b.casefold() in basis_text]
    return Analysis(raw=block.strip(), fields=fields, task=task, in_scope=in_scope, systems=systems, basis=basis)


def _strip_leading_fence(text: str) -> tuple[str, bool]:
    m = _LEADING_FENCE_RE.match(text)
    return (text[m.end() :], True) if m else (text, False)


def _cut(buffer: str, *, final: bool = True) -> tuple[Analysis, str, bool] | None:
    """``(analysis, remainder, undecided)`` when ``buffer`` starts with a complete block, else ``None``. While
    streaming (``final=False``) a fenced block whose closing fence may still be arriving is ``undecided``."""
    probe, fenced = _strip_leading_fence(buffer.lstrip())
    if not probe.startswith(OPEN):
        return None
    end = probe.find(CLOSE)
    if end < 0:
        return None
    rest = probe[end + len(CLOSE) :]
    undecided = False
    if fenced:
        undecided = not final and _PARTIAL_FENCE_RE.fullmatch(rest) is not None
        rest = _BARE_CLOSING_FENCE_RE.sub("", rest, count=1)
    return parse_analysis(probe[len(OPEN) : end]), rest.lstrip("\n"), undecided


def split_analysis(text: str) -> tuple[Analysis | None, str]:
    """Non-streaming twin of ``AnalysisSplitter``: ``(analysis, answer text)`` or ``(None, text)``."""
    cut = _cut(text)
    return (cut[0], cut[1]) if cut is not None else (None, text)


class AnalysisSplitter:
    """Wraps any token iterable (``TokenStream`` or a test generator). States: HEAD (the text so far may still be
    the block's opening), BLOCK (inside the block, waiting for the close tag), PASS (everything is answer text).
    Duck-typed like ``TokenStream``: ``finish_reason``/``model``/``truncated`` proxy the inner stream, ``close()``
    closes it. ``analysis`` is known once the block is complete (or stays ``None``)."""

    def __init__(self, inner: Iterable[str], *, head_chars: int = 40, max_block_chars: int = 1500) -> None:
        self._inner = inner
        self.head_chars = head_chars
        self.max_block_chars = max_block_chars
        self.analysis: Analysis | None = None

    @property
    def finish_reason(self) -> str | None:
        return getattr(self._inner, "finish_reason", None)

    @property
    def model(self) -> str | None:
        return getattr(self._inner, "model", None)

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if close is not None:
            close()

    def __iter__(self) -> Iterator[str]:
        buf = ""
        state = "head"
        for delta in self._inner:
            if state == "pass":
                yield delta
                continue
            if state == "after":  # the block is off; the blank lines that follow it may arrive in later deltas
                delta = delta.lstrip("\n")
                if delta:
                    state = "pass"
                    yield delta
                continue
            buf += delta
            if state == "head":
                probe, _ = _strip_leading_fence(buf.lstrip())
                if probe.startswith(OPEN):
                    state = "block"
                elif OPEN.startswith(probe) or (probe.startswith("`") and "\n" not in probe and len(probe) < 12):
                    if len(buf) < self.head_chars + len(OPEN):
                        continue  # still a possible opening (whitespace, a fence, a prefix of the tag)
                    state = "pass"
                    yield buf
                    continue
                else:
                    state = "pass"
                    yield buf
                    continue
            if state == "block":
                cut = _cut(buf, final=False)
                if cut is not None:
                    self.analysis, rest, undecided = cut
                    if undecided:
                        continue
                    state = "pass" if rest else "after"
                    if rest:
                        yield rest
                elif len(buf) > self.max_block_chars:
                    state = "pass"
                    yield buf
        if state == "block":
            cut = _cut(buf)
            if cut is not None:
                self.analysis, rest, _ = cut
                if rest:
                    yield rest
            elif buf:
                yield buf
        elif state == "head" and buf:
            yield buf
