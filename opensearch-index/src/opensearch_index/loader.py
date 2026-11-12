"""Read one docling-graph run from disk.

Accepted inputs:
* a ``response.json`` file (full ``ProcessResponse``, written by ``scripts/process_via_api.py``),
* a directory containing ``response.json`` (canonical), or
* a directory in the ``dgs process`` layout: ``meta.json`` + ``chunks.json`` [+ ``graph.json``, ``markdown.md``].
``document.json`` (the raw DoclingDocument, ~40 MB) is never read.
"""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import ProcessResponse

_META_KEYS = ("document", "degraded", "errors", "warnings", "timings_s", "versions", "cached")


class LoadError(ValueError):
    pass


def load_run(path: str | Path) -> ProcessResponse:
    p = Path(path)
    if p.is_file():
        return ProcessResponse.model_validate(_read_json(p))
    if not p.is_dir():
        raise LoadError(f"{p}: not a file or directory")
    response = p / "response.json"
    if response.is_file():
        return ProcessResponse.model_validate(_read_json(response))
    meta, chunks = p / "meta.json", p / "chunks.json"
    if meta.is_file() and chunks.is_file():
        m = _read_json(meta)
        data = {k: m[k] for k in _META_KEYS if k in m}
        data["chunks"] = _read_json(chunks)
        graph = p / "graph.json"
        data["graph"] = _read_json(graph) if graph.is_file() else None
        markdown = p / "markdown.md"
        data["markdown"] = markdown.read_text(encoding="utf-8") if markdown.is_file() else ""
        return ProcessResponse.model_validate(data)
    found = sorted(x.name for x in p.iterdir())
    raise LoadError(
        f"{p}: expected response.json (process_via_api.py output) or meta.json + chunks.json "
        f"(dgs process output); found {found}"
    )


def _read_json(p: Path):
    with p.open("rb") as fh:
        return json.load(fh)
