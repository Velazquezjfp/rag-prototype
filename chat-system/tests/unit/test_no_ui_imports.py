"""The backend must not import streamlit: the UI is the disposable layer (SPEC §10), the service is what tests and
the CLI run without a browser."""

import ast
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "chat_system"
BACKEND = ["service.py", "repository.py", "db.py", "models.py", "catalog.py", "wiring.py", "cli.py", "settings.py"]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_backend_modules_do_not_import_streamlit():
    for name in BACKEND:
        assert "streamlit" not in _imports(SRC / name), name


def test_importing_the_service_does_not_load_streamlit():
    code = "import sys, chat_system.service, chat_system.cli, chat_system.wiring; print('streamlit' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
