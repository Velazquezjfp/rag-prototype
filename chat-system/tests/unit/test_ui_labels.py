"""The search status line and the captions are pure functions of the turn (REQ-001 R9) — tested without Streamlit's
AppTest, whose element tree loses the ``st.status`` container in the rerun that follows every turn."""

from __future__ import annotations

from types import SimpleNamespace

from chat_system.ui.chat import MODE_LABEL_DE, WEAK_FOLLOW_UP_NOTE_DE, status_label
from conftest import make_result


def _turn(result, *, guardrail=False, weak_follow_up=False):
    return SimpleNamespace(result=result, guardrail=guardrail, weak_follow_up=weak_follow_up)


def test_status_label_is_honest_about_what_was_used():
    normal = _turn(make_result("Was passiert, wenn Vault versiegelt ist?"))
    assert status_label(normal) == "2 Quellen · 1 Fakten · 1 Entitäten (Graph)"
    fast = _turn(make_result("Frage?", mode="fast"))
    assert status_label(fast).endswith("(schnell)")
    guard = _turn(make_result("Apfelkuchen?", weak=True), guardrail=True)
    label = status_label(guard)
    assert "Modell nicht aufgerufen" in label and "Quellen" not in label and "Fakten" not in label
    follow = _turn(make_result("Mach ein Script daraus", weak=True), weak_follow_up=True)
    assert status_label(follow) == "Keine neuen Treffer · Antwort aus dem Gesprächsverlauf"
    overview = make_result("Wer ist verantwortlich?")
    overview.mode = "overview"
    assert status_label(_turn(overview)).endswith("(Übersicht)")
    assert MODE_LABEL_DE["overview"] == "Übersicht" and "Gesprächsverlauf" in WEAK_FOLLOW_UP_NOTE_DE


def test_assistant_labels_and_captions():
    """REQ-002 R10: the status line names the assistant and the assessed evidence; captions and the sidebar line are
    pure functions of the persisted diagnostics."""
    from chat_system.ui.chat import analysis_caption, format_user_message
    from chat_system.ui.sidebar import mode_caption

    strong = _turn(make_result("Mach ein Skript"))
    strong.profile = "assistant"
    assert status_label(strong) == "Technik-Assistent · 2 Quellen · 1 Fakten · 1 Entitäten · Evidenz stark (Graph)"
    weak = make_result("Exit-Code 137?", weak=True)
    weak.weak_evidence = False  # guardrail off: nothing blocks, but the assessment says weak
    weak.diagnostics.assessed_weak = True
    w = _turn(weak)
    w.profile = "assistant"
    assert status_label(w).startswith("Technik-Assistent · ") and "Evidenz schwach" in status_label(w)
    assert analysis_caption({"task": "Skript", "in_scope": True, "systems": "ZSD", "basis": ["Handbücher", "Verlauf"]}) == "Einordnung: Aufgabe: Skript · Bereich: innerhalb · System: ZSD · Grundlage: Handbücher, Verlauf"
    assert analysis_caption({"in_scope": False}) == "Einordnung: Aufgabe: Sonstiges · Bereich: außerhalb"
    assert mode_caption("assistant", False) == "Modus: Technik-Assistent · Guardrail aus"
    assert mode_caption("strict", True) == "Modus: Handbuch-Antworten · Guardrail an"
    assert format_user_message("Frage?\n$ oc get nodes\n$ oc get co\n$ vault status\n" * 5).count("```text") == 1
