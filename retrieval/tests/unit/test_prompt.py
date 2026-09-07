import pytest

from rag_retrieval.models import (
    ChannelEvidence,
    ChunkGroup,
    ChunkHit,
    Diagnostics,
    EntityCard,
    EntityOccurrence,
    GraphFact,
    Message,
    RetrievalResult,
    format_pages,
)
from rag_retrieval.prompt import (
    NO_EVIDENCE_ANSWER,
    SYSTEM_PROMPT_DE,
    build_messages,
    estimate_tokens,
    merge_parts,
    render_context,
    source_header,
)


def _hit(cid, pages, body, *, kind="text", caption=None, tokens=None, rank=1, crumbs=("1 Kapitel",)):
    return ChunkHit(chunk_id=cid, doc_id="BHB-PLT-0007", doc_title="ZSD", kind=kind, caption=caption, page_numbers=pages, heading_breadcrumb=list(crumbs), body_text=body, text=body, token_count=tokens if tokens is not None else max(1, len(body) // 3), rank=rank, fused_score=1.0, channels=[ChannelEvidence(channel="knn", rank=rank)], group_key=f"BHB-PLT-0007|table|{caption}" if caption else cid)


def _group(parts, rank=1):
    best = parts[0]
    return ChunkGroup(key=best.group_key, doc_id=best.doc_id, doc_title=best.doc_title, kind=best.kind, caption=best.caption, heading_breadcrumb=best.heading_breadcrumb, pages=sorted({p for h in parts for p in h.page_numbers}), chunk_ids=[h.chunk_id for h in parts], parts=list(parts), rank=rank, fused_score=1.0)


def _fact(eid="e1", polarity="positive"):
    return GraphFact(edge_id=eid, doc_ids=["BHB-PLT-0007"], source_id="a", source_label="A", relation="DEPENDS_ON", target_id="b", target_label="B", polarity=polarity, pages=[19], chunk_ids=["x"], rendered=f"A —DEPENDS_ON→ B{': NICHT' if polarity == 'negative' else ''} [BHB-PLT-0007 S. 19; Kante {eid}]")


def _card():
    return EntityCard(node_ids=["n"], type="ImpactStatement", label="Vault versiegelt | VPP", occurrences=[EntityOccurrence(doc_id="BHB-PLT-0001", label="x", attributes={"severity": "keine"}, pages=[19])], matched_by="label", rendered="Vault versiegelt | VPP (ImpactStatement) — severity: keine [BHB-PLT-0001 S. 19]")


def _result(groups, facts=(), entities=(), weak=False):
    chunks = [p for g in groups for p in g.parts]
    return RetrievalResult(question="Frage?", mode="slow", chunks=chunks, groups=list(groups), facts=list(facts), entities=list(entities), weak_evidence=weak, diagnostics=Diagnostics(question="Frage?", mode="slow"))


def test_format_pages():
    assert format_pages([9, 8]) == "8–9" and format_pages([1, 2, 26]) == "1–2, 26" and format_pages([]) == "?" and format_pages([5]) == "5"


def test_estimate_tokens():
    assert estimate_tokens("") == 1 and estimate_tokens("x" * 260) == 100


def test_context_order_entities_facts_sources_and_ids():
    g = _group([_hit("c1", [4], "Text eins.")])
    ctx = render_context(_result([g], facts=[_fact()], entities=[_card()]))
    i_e, i_f, i_q = ctx.text.index("## Entitäten"), ctx.text.index("## Fakten"), ctx.text.index("## Quellen")
    assert i_e < i_f < i_q
    assert "- Vault versiegelt | VPP (ImpactStatement) — severity: keine" in ctx.text
    assert "- A —DEPENDS_ON→ B [BHB-PLT-0007 S. 19; Kante e1]" in ctx.text
    assert "### Quelle 1 · BHB-PLT-0007 „ZSD“ · S. 4 · 1 Kapitel · [c1]\nText eins." in ctx.text
    assert ctx.included_chunk_ids == ["c1"] and ctx.included_edge_ids == ["e1"] and ctx.dropped_chunk_ids == []
    assert ctx.token_estimate == estimate_tokens(ctx.text)


def test_budget_drops_lower_ranked_groups_but_keeps_the_first():
    g1 = _group([_hit("c1", [4], "A" * 900, tokens=300)], rank=1)
    g2 = _group([_hit("c2", [5], "B" * 900, tokens=300)], rank=2)
    g3 = _group([_hit("c3", [6], "C" * 90, tokens=30)], rank=3)
    ctx = render_context(_result([g1, g2, g3]), token_budget=420)
    assert ctx.included_chunk_ids == ["c1", "c3"] and ctx.dropped_chunk_ids == ["c2"]
    tiny = render_context(_result([g1, g2, g3]), token_budget=1)
    assert tiny.included_chunk_ids == ["c1"] and tiny.dropped_chunk_ids == ["c2", "c3"]


def test_max_facts_limits_the_fact_block():
    ctx = render_context(_result([], facts=[_fact("e1"), _fact("e2", "negative"), _fact("e3")]), max_facts=2)
    assert ctx.included_edge_ids == ["e1", "e2"] and "Kante e3" not in ctx.text and "NICHT" in ctx.text


def test_empty_result_has_placeholder():
    ctx = render_context(_result([]))
    assert "keine passenden Stellen" in ctx.text and ctx.included_chunk_ids == []


def test_merge_table_parts_dedupes_caption_and_header_rows():
    cap = "Tabelle 5: Portmatrix"
    p1 = _hit("t-0030", [8], f"{cap}\n\n| Regel | Ziel |\n| - | - |\n| FW-1 | a |", kind="table", caption=cap, rank=1)
    p2 = _hit("t-0031", [9], f"{cap}\n\n| Regel | Ziel |\n| - | - |\n| FW-2 | b |", kind="table", caption=cap, rank=2)
    p3 = _hit("t-0032", [9], "| FW-3 | c |", kind="table", caption=cap, rank=3)
    merged = merge_parts(_group([p1, p2, p3]))
    assert merged.count(cap) == 1 and merged.count("| Regel | Ziel |") == 1
    assert merged.splitlines()[-3:] == ["| FW-1 | a |", "| FW-2 | b |", "| FW-3 | c |"]
    assert merge_parts(_group([p1])) == p1.body_text
    header = source_header(3, _group([p1, p2, p3]))
    assert header.startswith("### Quelle 3 · BHB-PLT-0007 „ZSD“ · S. 8–9 · 1 Kapitel · Tabelle 5: Portmatrix (3 Teile) · [t-0030, t-0031, t-0032]")


def test_build_messages_shape_history_and_limit():
    g = _group([_hit("c1", [4], "Text.")])
    res = _result([g])
    history = [Message(role="user", content=f"u{i}") if i % 2 == 0 else {"role": "assistant", "content": f"a{i}"} for i in range(10)]
    msgs = build_messages(res, "Frage?", history, max_history_turns=2)
    assert msgs[0] == {"role": "system", "content": SYSTEM_PROMPT_DE}
    assert [m["content"] for m in msgs[1:-1]] == ["u6", "a7", "u8", "a9"]
    assert msgs[-1]["role"] == "user" and msgs[-1]["content"].startswith("Kontext:\n## Quellen") and msgs[-1]["content"].endswith("\n\nFrage: Frage?")
    assert build_messages(res, "Frage?", None, system_prompt="S")[0]["content"] == "S"
    with pytest.raises(ValueError, match="context limit"):
        build_messages(res, "Frage?", context_limit_tokens=10)
    assert NO_EVIDENCE_ANSWER in SYSTEM_PROMPT_DE and "[BHB-PLT-0007 S. 19]" in SYSTEM_PROMPT_DE
