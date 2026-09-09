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
