"""The real app.py (Streamlit AppTest, no browser) over the real wiring: OpenSearch + LiteLLM, temporary SQLite.
Gated by CHAT_INTEGRATION=1."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

if not os.environ.get("CHAT_INTEGRATION"):
    pytest.skip("set CHAT_INTEGRATION=1 to run against the live stack", allow_module_level=True)

from streamlit.testing.v1 import AppTest  # noqa: E402

from chat_system.settings import Settings  # noqa: E402
from chat_system.ui import app as ui_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def at(tmp_path, monkeypatch):
    db = tmp_path / "ui.db"
    monkeypatch.setattr(ui_app, "get_settings", lambda: Settings(db={"url": f"sqlite:///{db}"}))
    ui_app.get_service.clear()
    yield AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    ui_app.get_service.clear()


def test_real_turn_in_the_ui_shows_answer_sources_and_diagnostics(at):
    at.run()
    assert not at.exception, at.exception
    at.sidebar.checkbox[0].set_value(True).run()  # Diagnostik anzeigen
    at.chat_input[0].set_value("Was passiert, wenn Vault versiegelt ist?").run()
    assert not at.exception, at.exception
    assert [m.avatar for m in at.chat_message] == ["user", "assistant"]
    answer = at.chat_message[1].markdown[0].value
    print("\n[ui answer]", answer[:200].replace("\n", " "))
    assert "BHB-PLT-" in answer and len(answer) > 80
    labels = [e.label for e in at.expander]
    assert any(lbl.startswith("Quellen (") for lbl in labels) and "Diagnostik" in labels, labels
    assert [sb.label for sb in at.sidebar.selectbox] == ["Gespräche"]  # no user selection


def test_manual_filter_in_the_ui_restricts_the_sources(at):
    at.run()
    opts = at.sidebar.multiselect[0].options  # display labels (format_func), one per indexed manual
    zsd = next(o for o in opts if o.startswith("BHB-PLT-0007"))
    at.sidebar.multiselect[0].select(zsd).run()
    at.chat_input[0].set_value("Was war bei ZSDSUP-0247?").run()
    assert not at.exception, at.exception
    sources = [e for e in at.expander if e.label.startswith("Quellen (")]
    assert sources, [e.label for e in at.expander]
    text = " ".join(m.value for m in sources[0].markdown)
    cited = re.findall(r"\*\*\[\d+\] (BHB-PLT-\d+)\*\*", text)  # the source headers (snippets may mention other manuals)
    assert cited and set(cited) == {"BHB-PLT-0007"}, cited
