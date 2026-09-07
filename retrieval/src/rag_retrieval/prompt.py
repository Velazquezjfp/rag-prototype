"""Prompt injection: the German system prompt and the context block rendered from a ``RetrievalResult``
(Entitäten → Fakten → Quellen), budgeted with the stored ``token_count`` of every chunk (no tokenizer needed)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .models import ChunkGroup, Message, RenderedContext, RetrievalResult

NO_EVIDENCE_ANSWER = "Dazu steht nichts in den Handbüchern."

SYSTEM_PROMPT_DE = f"""Du bist der Assistent für die IT-Betriebshandbücher (BHB) des BAVD. Du beantwortest Fragen des Betriebspersonals ausschließlich aus dem bereitgestellten Kontext, der aus drei Teilen besteht: Entitäten (Einträge aus dem Wissensgraphen mit ihren Eigenschaften), Fakten (Beziehungen zwischen Einträgen) und Quellen (Textstellen und Tabellen aus den Handbüchern).

Regeln:
1. Verwende nur Informationen aus dem Kontext. Ergänze nichts aus eigenem Wissen und rate nicht.
2. Belege jede Aussage mit der Quelle in eckigen Klammern, z. B. [BHB-PLT-0007 S. 19]. Dokument-ID und Seite stehen bei jeder Entität, jedem Fakt und jeder Quelle.
3. Enthält der Kontext keine Antwort auf die Frage, antworte genau mit: „{NO_EVIDENCE_ANSWER}“ – ohne weitere Sätze.
4. Fakten mit „NICHT“ sind ausdrücklich verneinte Aussagen (z. B. es besteht KEINE Abhängigkeit). Einträge mit „severity: keine“ bedeuten: keine Auswirkung. Gib solche Verneinungen als Verneinung wieder und nenne die Begründung aus dem Zitat.
5. Widersprechen sich zwei Handbücher, nenne beide Aussagen mit ihren Quellen, ohne eine davon zu verwerfen.
6. Übernimm Bezeichner wörtlich: Ticket-, SOP-, Firewall-, Host-, Zonen- und Dokument-IDs, Namen, Ports, Pfade.
7. Antworte auf Deutsch, knapp und in ganzen Sätzen. Reihenfolgen, Schritte und Aufzählungen als nummerierte Liste bzw. Liste.
"""


CHARS_PER_TOKEN = 2.6  # measured: a 19,120-character prompt of this corpus = 7,336 Gemini tokens


def estimate_tokens(text: str) -> int:
    """Rough token count for German text with identifiers and markdown tables (no tokenizer dependency)."""
    return max(1, int(len(text) / CHARS_PER_TOKEN))


# --------------------------------------------------------------------------- table parts


def _table_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.lstrip().startswith("|")]


def _strip_repeated(first_body: str, part_body: str, caption: str | None) -> str:
    lines = part_body.splitlines()
    while lines and (not lines[0].strip() or (caption and lines[0].strip() == caption.strip())):
        lines.pop(0)
    header = _table_lines(first_body)[:2]
    if (
        len(header) == 2
        and set(header[1].replace("|", "").strip()) <= set("-: ")
        and len(lines) >= 2
        and lines[0].strip() == header[0].strip()
        and lines[1].strip() == header[1].strip()
    ):
        lines = lines[2:]
    return "\n".join(lines)


def merge_parts(group: ChunkGroup) -> str:
    """Body of a group: text chunks as they are; table parts with caption and repeated header rows only once."""
    parts = group.parts
    if not parts:
        return ""
    first = parts[0].body_text or parts[0].text
    if len(parts) == 1:
        return first.strip()
    out = [first.rstrip()]
    for p in parts[1:]:
        body = _strip_repeated(first, p.body_text or p.text, group.caption)
        if body.strip():
            out.append(body.rstrip())
    return "\n".join(out).strip()


def source_header(n: int, group: ChunkGroup) -> str:
    bits = [f"### Quelle {n}", group.doc_id + (f" „{group.doc_title}“" if group.doc_title else ""), f"S. {group.cite.split('S. ', 1)[1]}"]
    if group.heading_breadcrumb:
        bits.append(" › ".join(group.heading_breadcrumb))
    if group.caption and group.caption not in (group.heading_breadcrumb or []):
        bits.append(group.caption + (f" ({len(group.parts)} Teile)" if len(group.parts) > 1 else ""))
    bits.append("[" + ", ".join(group.chunk_ids) + "]")
    return " · ".join(bits)


# --------------------------------------------------------------------------- context


def render_context(
    result: RetrievalResult, *, token_budget: int | None = None, max_facts: int | None = None
) -> RenderedContext:
    """Entitäten, Fakten, then Quellen by rank until the budget is spent (facts and entities always fit first)."""
    budget = token_budget if token_budget is not None else 6000
    sections: list[str] = []
    used = 0
    included_edges: list[str] = []

    if result.entities:
        lines = ["## Entitäten"] + [f"- {c.rendered}" for c in result.entities]
        block = "\n".join(lines)
        sections.append(block)
        used += estimate_tokens(block)

    facts = result.facts[:max_facts] if max_facts is not None else result.facts
    if facts:
        lines = ["## Fakten"] + [f"- {f.rendered}" for f in facts]
        block = "\n".join(lines)
        sections.append(block)
        used += estimate_tokens(block)
        included_edges = [f.edge_id for f in facts]

    included: list[str] = []
    dropped: list[str] = []
    source_blocks: list[str] = []
    for g in result.groups:
        header = source_header(len(source_blocks) + 1, g)
        body = merge_parts(g)
        cost = (g.token_count or estimate_tokens(body)) + 40
        if source_blocks and used + cost > budget:
            dropped.extend(g.chunk_ids)
            continue
        source_blocks.append(f"{header}\n{body}")
        included.extend(g.chunk_ids)
        used += cost
    if source_blocks:
        sections.append("## Quellen\n" + "\n\n".join(source_blocks))

    text = "\n\n".join(sections) if sections else "(keine passenden Stellen in den Handbüchern gefunden)"
    return RenderedContext(
        text=text,
        token_estimate=estimate_tokens(text),
        included_chunk_ids=included,
        included_edge_ids=included_edges,
        dropped_chunk_ids=dropped,
    )


def _as_message(m: Message | Mapping[str, Any]) -> Message:
    return m if isinstance(m, Message) else Message.model_validate(dict(m))


def build_messages(
    result: RetrievalResult,
    question: str,
    history: Sequence[Message | Mapping[str, Any]] | None = None,
    *,
    system_prompt: str | None = None,
    token_budget: int | None = None,
    max_facts: int | None = None,
    max_history_turns: int = 3,
    context_limit_tokens: int | None = None,
) -> list[dict[str, str]]:
    """``system`` + the last ``max_history_turns`` user/assistant pairs + ``Kontext: … Frage: …``.

    Raises ``ValueError`` when the estimated prompt exceeds ``context_limit_tokens``."""
    ctx = render_context(result, token_budget=token_budget, max_facts=max_facts)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt or SYSTEM_PROMPT_DE}]
    if history:
        turns = [_as_message(m) for m in history if _as_message(m).role in ("user", "assistant")]
        for m in turns[-2 * max_history_turns :]:
            messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": f"Kontext:\n{ctx.text}\n\nFrage: {question}"})
    if context_limit_tokens is not None:
        total = sum(estimate_tokens(m["content"]) for m in messages)
        if total > context_limit_tokens:
            raise ValueError(
                f"prompt estimate {total} tokens exceeds the model context limit {context_limit_tokens} "
                f"(lower RAG__RETRIEVAL__CONTEXT_TOKEN_BUDGET or RAG__RETRIEVAL__FINAL_K)"
            )
    return messages
