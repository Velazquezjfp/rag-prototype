"""Pasted material vs. the instruction (REQ-002 R4/R7): a chat message may carry a log excerpt, a command list or
a script next to the actual request. The material must reach the model verbatim, but never the question analysis
wholesale — n-gram label matching over a 3 000-character log seeds dozens of spurious nodes and the embedding
endpoint rejects over-length input. ``split_material`` separates the two, ``compose_query`` builds the bounded
retrieval query (instruction + identifiers + signature lines), ``injection_markers`` flags instruction-like phrases
inside user text so the prompt can treat them as data."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .query import extract_question_identifiers

__all__ = [
    "DEFAULT_INSTRUCTION_DE",
    "Split",
    "compose_query",
    "injection_markers",
    "is_truncated",
    "signature_lines",
    "split_material",
]

DEFAULT_INSTRUCTION_DE = "Analysiere das folgende Material."
TRUNCATION_RE = re.compile(r"\[… gekürzt: \d+ Zeichen ausgelassen …\]")

FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
    r"|\b(?:Jan|Feb|Mar|Mär|Apr|May|Mai|Jun|Jul|Aug|Sep|Oct|Okt|Nov|Dec|Dez)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\b"
    r"|\b\d{2}:\d{2}:\d{2}[.,]\d{3}\b"
)
LEVEL_RE = re.compile(r"\b(?:ERROR|WARN(?:ING)?|INFO|DEBUG|FATAL|CRIT(?:ICAL)?|TRACE|SEVERE)\b")
TRACE_RE = re.compile(r"\w*(?:Exception|Error)\b|\bTraceback\b|^\s*Caused by:|^\s+at \S+\(|\bORA-\d{3,5}\b|\bOOMKilled\b")
PROMPT_RE = re.compile(r"^\s*(?:\$|#|>)\s+\S")
COMMAND_RE = re.compile(
    r"^\s*(?:sudo|oc|kubectl|systemctl|journalctl|vault|curl|ssh|ansible(?:-playbook)?|tmsh|keytool|cmctl|kcadm\.sh|"
    r"openssl|grep|tail|cat|export|for|while|if|echo|podman|docker|rman|liquibase|chmod|chown|mkdir|cd|set -e)\b"
)
SHEBANG_RE = re.compile(r"^\s*#!/")
KV_RE = re.compile(r"\b[\w.-]+=[^\s=]+")
JSON_RE = re.compile(r'^\s*[{}\[\]]|^\s*"[^"]+"\s*:')

PREFERRED_RE = re.compile(
    r"ERROR|WARN|FATAL|CRIT|Exception|Traceback|Caused by|failed|denied|refused|timeout|sealed|unreachable|"
    r"not found|no such|ORA-\d+|OOMKilled|Unauthorized|forbidden",
    re.I,
)
_STRIP_RES = (TIMESTAMP_RE, re.compile(r"\b[0-9a-f]{8,}\b", re.I), re.compile(r"\b\d{5,}\b"))

INJECTION_RES = (
    re.compile(r"ignor(?:ier|e)\w*\s+(?:alle\s+|all\s+)?(?:vorherigen|bisherigen|previous|prior|above|obigen)\s+(?:anweisungen|instruktionen|instructions|regeln|rules)", re.I),
    re.compile(r"vergiss\s+(?:alle\s+)?(?:deine\s+|die\s+)?(?:regeln|anweisungen|instruktionen)", re.I),
    re.compile(r"forget\s+(?:all\s+)?(?:your\s+)?(?:rules|instructions)", re.I),
    re.compile(r"\bdu bist (?:jetzt|ab jetzt|nun)\b", re.I),
    re.compile(r"\byou are now\b", re.I),
    re.compile(r"\bsystem[\s-]*prompt\b", re.I),
    re.compile(r"\bneue (?:anweisung(?:en)?|regel(?:n)?)\s*:", re.I),
)


@dataclass(frozen=True)
class Split:
    instruction: str
    material: str | None
    truncated_chars: int = 0


def _norm(text: str) -> str:
    return " ".join(text.split())


def is_material_line(line: str) -> bool:
    """Does this line look like a log line, a command or code rather than prose?"""
    return bool(
        TIMESTAMP_RE.search(line)
        or LEVEL_RE.search(line)
        or TRACE_RE.search(line)
        or PROMPT_RE.match(line)
        or COMMAND_RE.match(line)
        or SHEBANG_RE.match(line)
        or JSON_RE.match(line)
        or len(KV_RE.findall(line)) >= 2
    )


def is_truncated(material: str | None) -> bool:
    return bool(material) and TRUNCATION_RE.search(material) is not None


def _cap(material: str, max_chars: int) -> tuple[str, int]:
    if len(material) <= max_chars:
        return material, 0
    tail = max_chars * 3 // 8  # log tails carry the last error: keep 5/8 head, 3/8 tail of the budget
    head = max_chars - tail
    omitted = len(material) - max_chars
    return f"{material[:head].rstrip()}\n[… gekürzt: {omitted} Zeichen ausgelassen …]\n{material[-tail:].lstrip()}", omitted


def _finish(instruction: str, material: str, max_chars: int) -> Split:
    material = material.strip("\n")
    capped, omitted = _cap(material, max_chars)
    return Split(_norm(instruction) or DEFAULT_INSTRUCTION_DE, capped, omitted)


def split_material(
    text: str, *, min_chars: int = 200, min_lines: int = 3, ratio: float = 0.5, max_chars: int = 8000
) -> Split:
    """Fenced blocks are material; otherwise a text of at least ``min_chars`` splits when at least ``min_lines``
    lines (and ``ratio`` of the non-empty lines) look like logs, commands or code. The material keeps its line
    breaks and is capped at ``max_chars`` (head + tail); the instruction is whitespace-normalised."""
    raw = text.strip("\n")
    if not raw.strip():
        return Split("", None)
    fences = FENCE_RE.findall(raw)
    if fences:
        return _finish(FENCE_RE.sub(" ", raw), "\n".join(f.strip("\n") for f in fences), max_chars)
    if len(raw) < min_chars:
        return Split(_norm(raw), None)
    lines = raw.splitlines()
    if len(lines) == 1:
        return _finish("", raw, max_chars) if is_material_line(raw) else Split(_norm(raw), None)
    flags: list[bool | None] = [is_material_line(ln) if ln.strip() else None for ln in lines]
    for i in range(1, len(lines) - 1):  # one prose line between two material lines belongs to the material
        if flags[i] is False and flags[i - 1] and flags[i + 1]:
            flags[i] = True
    non_empty = [f for f in flags if f is not None]
    hits = sum(1 for f in non_empty if f)
    if hits < min_lines or hits / len(non_empty) < ratio:
        return Split(_norm(raw), None)
    material = "\n".join(ln for ln, f in zip(lines, flags, strict=True) if f)
    instruction = " ".join(ln.strip() for ln, f in zip(lines, flags, strict=True) if f is False)
    return _finish(instruction, material, max_chars)


def signature_lines(material: str, *, max_lines: int = 5, max_line_chars: int = 120) -> list[str]:
    """The lines worth searching for: error/exception lines first, timestamps, hashes and long numbers removed,
    duplicates dropped — what BM25 and the embedding should see instead of the whole paste."""
    seen: set[str] = set()
    preferred: list[str] = []
    rest: list[str] = []
    for line in material.splitlines():
        s = line.strip()
        if not s or TRUNCATION_RE.search(s):
            continue
        for rx in _STRIP_RES:
            s = rx.sub(" ", s)
        s = _norm(s)[:max_line_chars].strip()
        key = s.lower()
        if not s or key in seen:
            continue
        seen.add(key)
        (preferred if PREFERRED_RE.search(s) else rest).append(s)
    return (preferred + rest)[:max_lines]


def compose_query(instruction: str, material: str | None, regexes: Mapping[str, re.Pattern[str]], *, max_chars: int = 700) -> str:
    """Instruction + identifiers found in the material (hosts, tickets, SOP/FW ids) + its signature lines, capped."""
    parts = [instruction.strip()]
    if material:
        known = " ".join(parts).lower()
        parts.extend(i for i in extract_question_identifiers(material, dict(regexes)) if i.lower() not in known)
        parts.extend(signature_lines(material))
    query = " ".join(p for p in parts if p)
    if len(query) > max_chars:
        query = query[:max_chars].rsplit(" ", 1)[0].rstrip()
    return query


def injection_markers(text: str, *, limit: int = 5) -> list[str]:
    """Phrases that look like instructions to the model inside user text (data, never commands — REQ-002 R7)."""
    found: list[str] = []
    for rx in INJECTION_RES:
        for m in rx.finditer(text):
            snippet = _norm(m.group(0))
            if snippet.lower() not in {f.lower() for f in found}:
                found.append(snippet)
            if len(found) >= limit:
                return found
    return found
