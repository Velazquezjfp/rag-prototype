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
    OVERVIEW_INSTRUCTION_DE,
    SYSTEM_PROMPT_DE,
    WEAK_FOLLOW_UP_NOTE_DE,
    build_messages,
    estimate_tokens,
    merge_parts,
    render_context,
    scope_line,
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
    assert msgs[-1]["role"] == "user" and msgs[-1]["content"].endswith("\n\nFrage: Frage?")
    # a single-manual context is named first (REQ-001 R5), then the rendered block
    assert msgs[-1]["content"].startswith("Kontext:\nHandbuch im Kontext: BHB-PLT-0007 „ZSD“") and "\n\n## Quellen" in msgs[-1]["content"]
    assert build_messages(res, "Frage?", None, system_prompt="S")[0]["content"] == "S"
    with pytest.raises(ValueError, match="context limit"):
        build_messages(res, "Frage?", context_limit_tokens=10)
    assert NO_EVIDENCE_ANSWER in SYSTEM_PROMPT_DE and "[BHB-PLT-0007 S. 19]" in SYSTEM_PROMPT_DE


def test_rules_allow_reuse_of_earlier_answers_and_grade_the_refusal():
    """REQ-001 R5: rule 1 permits transforming earlier answers, rule 3 asks back with options before refusing."""
    assert "früheren Antworten in diesem Gespräch" in SYSTEM_PROMPT_DE and "Skript" in SYSTEM_PROMPT_DE
    assert "welches System oder Handbuch gemeint ist" in SYSTEM_PROMPT_DE and "als Auswahl" in SYSTEM_PROMPT_DE
    assert SYSTEM_PROMPT_DE.count(NO_EVIDENCE_ANSWER) == 1 and "ohne weitere Sätze" in SYSTEM_PROMPT_DE


def test_overview_instruction_only_for_overview_results():
    g = _group([_hit("c1", [4], "Text.")])
    slow = build_messages(_result([g]), "Frage?")
    assert OVERVIEW_INSTRUCTION_DE not in slow[0]["content"]
    res = _result([g])
    res.mode = "overview"
    over = build_messages(res, "Frage?")
    assert over[0]["content"].startswith(SYSTEM_PROMPT_DE.rstrip()) and over[0]["content"].endswith(OVERVIEW_INSTRUCTION_DE)
    assert "eine Zeile je Eintrag" in OVERVIEW_INSTRUCTION_DE and "Rückfrage" in OVERVIEW_INSTRUCTION_DE
    custom = build_messages(res, "Frage?", system_prompt="S")
    assert custom[0]["content"] == "S\n\n" + OVERVIEW_INSTRUCTION_DE


def test_weak_note_replaces_the_context_and_keeps_the_history():
    g = _group([_hit("c1", [4], "Text.")])
    history = [Message(role="user", content="Wie entsiegle ich den Vault?"), {"role": "assistant", "content": "vault operator unseal [BHB-PLT-0007 S. 19]"}]
    msgs = build_messages(_result([g], weak=True), "Mach ein Script daraus", history, weak_note=True)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert "## Quellen" not in msgs[-1]["content"] and "Text." not in msgs[-1]["content"]
    assert msgs[-1]["content"].startswith("Kontext:\n" + WEAK_FOLLOW_UP_NOTE_DE) and msgs[-1]["content"].endswith("Frage: Mach ein Script daraus")
    assert NO_EVIDENCE_ANSWER in WEAK_FOLLOW_UP_NOTE_DE and "früheren Antworten" in WEAK_FOLLOW_UP_NOTE_DE
    # an explicit manual filter is still named on a weak follow-up; nothing is derived from the non-evidence chunks
    with_filter = build_messages(_result([g], weak=True), "q", history, weak_note=True, doc_ids=["BHB-PLT-0001"])
    assert with_filter[-1]["content"].startswith("Kontext:\nHandbuch-Filter: BHB-PLT-0001 – die Frage")


def test_scope_line_names_the_filter_or_the_single_manual():
    """REQ-001 R5: with a manual filter (or a single manual in the context) the model must not ask which manual."""
    g = _group([_hit("c1", [4], "Text.")])
    res = _result([g])
    assert scope_line(res, ["BHB-PLT-0007"]) == "Handbuch-Filter: BHB-PLT-0007 „ZSD“ – die Frage bezieht sich auf dieses Handbuch."
    assert scope_line(res, None) == "Handbuch im Kontext: BHB-PLT-0007 „ZSD“ – die Frage bezieht sich auf dieses Handbuch."
    two = scope_line(res, ["BHB-PLT-0001", "BHB-PLT-0007"])
    assert two.startswith("Handbuch-Filter (mehrere): BHB-PLT-0001, BHB-PLT-0007 „ZSD“") and two.endswith("diese Handbücher.")
    # two manuals in the context and no filter -> no line (asking which manual is legitimate)
    other = _hit("c2", [5], "Anderes.")
    other.doc_id = "BHB-PLT-0001"
    assert scope_line(_result([g, _group([other], rank=2)]), None) is None
    msgs = build_messages(res, "Wer ist verantwortlich?", doc_ids=["BHB-PLT-0007"])
    assert msgs[-1]["content"].startswith("Kontext:\nHandbuch-Filter: BHB-PLT-0007")
    assert "Handbuch-Filter" in SYSTEM_PROMPT_DE and "nicht nach dem Handbuch" in SYSTEM_PROMPT_DE


def test_ecosystem_summary_lists_manuals_systems_and_counts(graph_small):
    """REQ-002 R3: the assistant is grounded in the indexed manuals even when a question retrieves nothing."""
    from rag_retrieval.prompt import ecosystem_summary

    text = ecosystem_summary(graph_small)
    assert text.startswith("- BHB-PLT-0007") and "Systeme: " in text and "Komponenten: Keycloak" in text
    assert "Verfahren 3" in text and "Störungsbilder 2" in text and "Alarme 1" in text
    assert "Zentrale Sicherheitsdienste" in text and estimate_tokens(text) <= 400
    assert ecosystem_summary(graph_small, ["BHB-PLT-0007"]) == text and ecosystem_summary(graph_small, ["BHB-PLT-0001"]) == ""
    # names are capped, the tail says how many more
    assert "(+" in ecosystem_summary(graph_small, max_names=2) and "weitere)" in ecosystem_summary(graph_small, max_names=2)
    # a tiny budget keeps the first manual and lists the rest by id
    assert ecosystem_summary(graph_small, max_tokens=1).startswith("- BHB-PLT-0007")


def test_assistant_profile_prompt_layout():
    """REQ-002 R2/R3/R4/R5/R7: assistant system prompt + ecosystem; Evidenzlage first, material fenced, injection note,
    the question last; the strict profile is byte-identical to before."""
    from rag_retrieval.prompt import (
        ASSISTANT_SYSTEM_PROMPT_DE,
        INJECTION_NOTE_DE,
        MATERIAL_HEADER_DE,
        OUT_OF_SCOPE_ANSWER_DE,
        evidence_line,
    )

    g = _group([_hit("c1", [4], "Text.")])
    res = _result([g])
    res.diagnostics.assessed_weak = True
    res.diagnostics.assessed_reason = "r"
    res.diagnostics.injection_suspected = ["du bist jetzt"]
    msgs = build_messages(res, "Mach ein Skript", profile="assistant", material="$ oc get nodes\n$ vault status", ecosystem="- BHB-PLT-0007 „ZSD“: Systeme: Vault")
    system = msgs[0]["content"]
    assert system.startswith(ASSISTANT_SYSTEM_PROMPT_DE.rstrip()) and system.endswith("Handbücher im System:\n- BHB-PLT-0007 „ZSD“: Systeme: Vault")
    user = msgs[-1]["content"]
    assert user.startswith("Kontext:\nEvidenzlage: schwach (r)\nHandbuch im Kontext: BHB-PLT-0007 „ZSD“")
    assert f"\n\n{MATERIAL_HEADER_DE}\n```\n$ oc get nodes\n$ vault status\n```" in user
    assert user.index(MATERIAL_HEADER_DE) < user.index(INJECTION_NOTE_DE) < user.index("\n\nFrage: Mach ein Skript")
    assert user.endswith("\n\nFrage: Mach ein Skript") and evidence_line(res) == "Evidenzlage: schwach (r)"
    plain = build_messages(_result([g]), "Frage?", profile="assistant")[-1]["content"]
    assert plain.startswith("Kontext:\nEvidenzlage: stark\n") and "Material" not in plain and INJECTION_NOTE_DE not in plain
    # weak_note is a strict-profile mechanism: the assistant keeps the context and sees the Evidenzlage instead
    weak = build_messages(_result([g], weak=True), "q", [Message(role="user", content="h")], weak_note=True, profile="assistant")[-1]["content"]
    assert "## Quellen" in weak and WEAK_FOLLOW_UP_NOTE_DE not in weak and weak.startswith("Kontext:\nEvidenzlage: schwach\n")
    # strict: unchanged prompt, no evidence line, ecosystem ignored; material still reaches the strict prompt
    strict = build_messages(_result([g]), "Frage?", ecosystem="x")
    assert strict[0]["content"] == SYSTEM_PROMPT_DE and "Evidenzlage" not in strict[-1]["content"]
    with_material = build_messages(_result([g]), "Was ist das?", material="x ```y``` z")[-1]["content"]
    assert f"{MATERIAL_HEADER_DE}\n````\nx ```y``` z\n````\n\nFrage: Was ist das?" in with_material
    assert ASSISTANT_SYSTEM_PROMPT_DE.count(OUT_OF_SCOPE_ANSWER_DE) == 1 and "<einordnung>" in ASSISTANT_SYSTEM_PROMPT_DE
    assert "(Regel 1)" not in OVERVIEW_INSTRUCTION_DE and "allgemeines Fachwissen" in ASSISTANT_SYSTEM_PROMPT_DE


def test_fit_history_drops_the_oldest_pairs_before_failing():
    """REQ-002 R8: a long conversation shrinks to the context limit instead of raising; system + context must fit."""
    g = _group([_hit("c1", [4], "Text.")])
    res = _result([g])
    history = [Message(role="user" if i % 2 == 0 else "assistant", content=str(i) * 260) for i in range(6)]  # ~100 tokens each
    base = sum(estimate_tokens(m["content"]) for m in build_messages(res, "Frage?"))
    msgs = build_messages(res, "Frage?", history, max_history_turns=3, context_limit_tokens=base + 250)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"] and msgs[1]["content"].startswith("4")
    assert len(build_messages(res, "Frage?", history, max_history_turns=3, context_limit_tokens=base + 700)) == 8
    with pytest.raises(ValueError, match="context limit"):
        build_messages(res, "Frage?", history, context_limit_tokens=base - 1)
    with pytest.raises(ValueError, match="context limit"):
        build_messages(res, "Frage?", history, max_history_turns=3, context_limit_tokens=base + 250, fit_history=False)
