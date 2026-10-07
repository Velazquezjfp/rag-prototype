"""Anzeige- und Vergleichshilfen für das Notebook ``vergleich.ipynb`` — nur Darstellung und Messung, keine Suchlogik."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

from rag_retrieval.models import RetrievalResult
from rag_retrieval.prompt import render_context

pd.set_option("display.max_colwidth", 120)
pd.set_option("display.width", 200)


def _short(v: Any, n: int = 120) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


# --------------------------------------------------------------------------- die vier Indizes als Tabellen
def df_chunks(records: Sequence[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "chunk_id": r.get("chunk_id"),
            "doc_id": r.get("doc_id"),
            "kind": r.get("kind"),
            "pages": ",".join(map(str, r.get("page_numbers") or [])),
            "heading": " › ".join(r.get("heading_breadcrumb") or []),
            "caption": r.get("caption") or "",
            "identifiers": ", ".join(r.get("identifiers") or []),
            "node_labels": len(r.get("node_labels") or []),
            "edge_ids": len(r.get("edge_ids") or []),
            "tokens": r.get("token_count"),
            "text": _short(r.get("text") or "", 160),
        }
        for r in records
    ]
    return pd.DataFrame(rows).sort_values(["doc_id", "chunk_id"]).reset_index(drop=True)


def df_nodes(records: Sequence[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "doc_id": r.get("doc_id"),
            "node_id": r.get("node_id"),
            "type": r.get("type"),
            "label": r.get("label"),
            "aliases": ", ".join(r.get("aliases") or []),
            "degree": r.get("degree"),
            "pages": ",".join(map(str, r.get("pages") or [])),
            "chunks": len(r.get("chunk_ids") or []),
            "attributes": _short(r.get("attributes") or {}, 140),
        }
        for r in records
    ]
    return pd.DataFrame(rows).sort_values(["doc_id", "type", "label"]).reset_index(drop=True)


def df_documents(records: Sequence[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "doc_id": r.get("doc_id"),
            "title": r.get("title"),
            "version": r.get("version"),
            "root_system": r.get("root_system"),
            "name": r.get("name"),
            "pages": r.get("pages"),
            "tables": r.get("tables"),
            **{f"n_{k}": v for k, v in (r.get("counts") or {}).items()},
            "embedding_model": r.get("embedding_model"),
            "prefix": repr(r.get("embedding_text_prefix")),
            "graph_blob": "ja" if r.get("graph") else "–",
        }
        for r in records
    ]
    return pd.DataFrame(rows).sort_values("doc_id").reset_index(drop=True)


def df_manifest(records: Sequence[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "doc_id": r.get("doc_id"),
            "status": r.get("status"),
            "run_id": str(r.get("run_id"))[:12],
            "doc_sha256": str(r.get("doc_sha256"))[:12],
            "doc_name": r.get("doc_name"),
            "counts": _short(r.get("counts") or {}, 80),
            "swept": _short(r.get("swept") or {}, 60),
            "embedding_model": r.get("embedding_model"),
            "finished_at": r.get("finished_at"),
            "history": len(r.get("history") or []),
        }
        for r in records
    ]
    return pd.DataFrame(rows).sort_values("doc_id").reset_index(drop=True)


def fetch_all(client: Any, index: str, *, excludes: Sequence[str] = (), size: int = 5000) -> list[dict[str, Any]]:
    """Alle Datensätze eines Index (OpenSearch-Client oder SqliteSearchClient, gleiche Schnittstelle)."""
    body: dict[str, Any] = {"size": size, "query": {"match_all": {}}}
    if excludes:
        body["_source"] = {"excludes": list(excludes)}
    return [h["_source"] for h in client.search(index=index, body=body)["hits"]["hits"]]


# --------------------------------------------------------------------------- Kanäle und Ergebnisse
def channel_hits(responses: dict[str, Any]) -> dict[str, list[tuple[str, float | None]]]:
    """``run_channels``-Antwort → je Kanal ``[(chunk_id, score)]``."""
    return {ch: [(h["_id"], h.get("_score")) for h in resp.hits] for ch, resp in responses.items()}


def df_channel_side_by_side(a: dict[str, list[tuple[str, float | None]]], b: dict[str, list[tuple[str, float | None]]], *, names: tuple[str, str], n: int = 10) -> pd.DataFrame:
    rows = []
    for ch in a.keys() | b.keys():
        la, lb = a.get(ch, []), b.get(ch, [])
        for i in range(min(n, max(len(la), len(lb)))):
            ca, sa = la[i] if i < len(la) else ("", None)
            cb, sb = lb[i] if i < len(lb) else ("", None)
            rows.append({"channel": ch, "rank": i + 1, f"{names[0]}": ca, f"{names[0]} score": None if sa is None else round(sa, 4), f"{names[1]}": cb, f"{names[1]} score": None if sb is None else round(sb, 4), "gleich": "✓" if ca == cb else ""})
    order = {"knn": 0, "bm25": 1, "identifier": 2, "label": 3, "graph": 4}
    return pd.DataFrame(rows).sort_values(["channel", "rank"], key=lambda s: s.map(order) if s.name == "channel" else s).reset_index(drop=True)


def overlap(a: Sequence[str], b: Sequence[str], n: int | None = None) -> float:
    """Anteil gemeinsamer Treffer in den ersten ``n`` (Mengenvergleich; Reihenfolge egal)."""
    sa, sb = set(a[:n] if n else a), set(b[:n] if n else b)
    denom = min(len(sa), len(sb)) if sa and sb else max(len(sa), len(sb))
    return 1.0 if not denom else len(sa & sb) / denom


def channel_overlaps(a: dict[str, list[tuple[str, float | None]]], b: dict[str, list[tuple[str, float | None]]], n: int = 10) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for ch in ("knn", "bm25", "identifier", "label"):
        if ch in a or ch in b:
            out[ch] = round(overlap([c for c, _ in a.get(ch, [])], [c for c, _ in b.get(ch, [])], n), 2)
        else:
            out[ch] = None
    return out


def df_result(result: RetrievalResult) -> pd.DataFrame:
    rows = []
    for h in result.chunks:
        via = " ".join(f"{c.channel}#{c.rank}" for c in h.channels)
        where = " › ".join(h.heading_breadcrumb[-2:]) if h.heading_breadcrumb else ""
        rows.append({"rank": h.rank, "cite": h.cite, "kind": h.kind, "where": (where + (" · " + h.caption if h.caption else ""))[:90], "channels": via, "fused": round(h.fused_score, 4), "chunk_id": h.chunk_id})
    return pd.DataFrame(rows)


def df_rrf(result: RetrievalResult, rank_constant: int = 60, top: int = 3) -> pd.DataFrame:
    """Die RRF-Formel vorgerechnet: ``score = Σ 1/(k + rank)`` über die Kanäle, in denen der Chunk vorkommt."""
    rows = []
    for h in result.chunks[:top]:
        parts = [f"1/({rank_constant}+{c.rank})" for c in h.channels]
        rows.append({"rank": h.rank, "chunk_id": h.chunk_id, "Kanäle (Rang)": ", ".join(f"{c.channel}#{c.rank}" for c in h.channels), "Summe": " + ".join(parts), "fused_score": round(sum(1 / (rank_constant + c.rank) for c in h.channels), 5), "gespeichert": round(h.fused_score, 5)})
    return pd.DataFrame(rows)


def df_facts(result: RetrievalResult, n: int = 12) -> pd.DataFrame:
    return pd.DataFrame([{"#": i, "fact": f.rendered} for i, f in enumerate(result.facts[:n], 1)])


def df_entities(result: RetrievalResult, n: int = 10) -> pd.DataFrame:
    return pd.DataFrame([{"#": i, "type": e.type, "label": e.label, "matched_by": e.matched_by, "card": _short(e.rendered, 160)} for i, e in enumerate(result.entities[:n], 1)])


def _score_levels(hits: Sequence[tuple[str, float | None]], ndigits: int) -> list[list[str]]:
    """Treffer zu Gruppen gleicher Punktzahl (absteigend). Absolute Werte unterscheiden sich je Engine, die Struktur nicht."""
    groups: list[list[str]] = []
    last: float | None = None
    for cid, s in hits:
        s = round(s or 0.0, ndigits)
        if last is None or s != last:
            groups.append([])
            last = s
        groups[-1].append(cid)
    return groups


def same_up_to_ties(a: Sequence[tuple[str, float | None]], b: Sequence[tuple[str, float | None]], ndigits: int = 4) -> bool:
    """Gleiche Trefferliste bis auf die Reihenfolge innerhalb gleicher Punktzahl (OpenSearch sortiert Gleichstände nach
    Indexposition, die von der Indexgeschichte abhängt). Verglichen werden die Gruppen gleicher Punktzahl: gleiche
    Gruppengrößen, gleiche Mengen je Gruppe; nur die letzte Gruppe darf durch ``k`` abgeschnitten sein."""
    ga, gb = _score_levels(a, ndigits), _score_levels(b, ndigits)
    if len(ga) != len(gb) or [len(g) for g in ga] != [len(g) for g in gb]:
        return False
    return all(set(x) == set(y) for x, y in list(zip(ga, gb))[:-1])


import re as _re

_CITE_TAIL = _re.compile(r"\s(\[[^\[\]]*\])$")
_ATTR_SPLIT = _re.compile(r"; (?=[a-z_][a-z0-9_]*: )")  # nur vor dem nächsten ``key: `` trennen — Werte dürfen "; " enthalten
_PROPS = _re.compile(r"\(([a-z_][a-z0-9_]*=(?:[^()]|\([^()]*\))*)\)")  # Fakten: ``(k=v, k=v)`` — Kantenattribute, Werte mit einer Klammerebene
_PROP_SPLIT = _re.compile(r", (?=[a-z_][a-z0-9_]*=)")


def _sorted_props(s: str) -> str:
    return _PROPS.sub(lambda m: "(" + ", ".join(sorted(_PROP_SPLIT.split(m.group(1)))) + ")", s)


def _sorted_attrs(s: str) -> str:
    return "; ".join(sorted(_ATTR_SPLIT.split(s)))


def normalize_context(text: str) -> str:
    """Attribute innerhalb einer Zeile sortieren (Zitat am Zeilenende vorher abtrennen): OpenSearch gibt Objektschlüssel
    bei ``_source``-Filterung in anderer Reihenfolge zurück als gespeichert (geprüft: ``get`` behält sie, ``search`` mit
    ``includes`` nicht). Inhalt und Zitate bleiben unverändert — nur die Reihenfolge der ``k: v``-Paare wird neutralisiert."""
    out: list[str] = []
    run: list[str] = []  # aufeinanderfolgende Vorkommen-Zeilen ("    · …") einer Entity-Card: Reihenfolge = Ladereihenfolge der Handbücher

    def flush() -> None:
        out.extend(sorted(run))
        run.clear()

    for line in text.splitlines():
        m = _CITE_TAIL.search(line)
        cite = m.group(1) if m else ""
        body = _sorted_props(line[: m.start()] if m else line)  # Fakten: Kantenattribute stehen VOR dem „Zitat“
        head, sep, attrs = body.partition(" — ")
        if sep:
            norm = head + sep + _sorted_attrs(attrs)
        else:
            indent = len(head) - len(head.lstrip())
            prefix = head[:indent] + ("· " if head.lstrip().startswith("· ") else "")
            norm = prefix + _sorted_attrs(head[len(prefix):])
        norm += " " + cite if cite else ""
        if norm.lstrip().startswith("· "):
            run.append(norm)
        else:
            flush()
            out.append(norm)
    flush()
    return "\n".join(out)


def compare_results(a: RetrievalResult, b: RetrievalResult, *, names: tuple[str, str] = ("OpenSearch", "SQLite")) -> dict[str, Any]:
    """Gleichheit dessen, was der Prompt sieht: Chunks, Reihenfolge, Guardrail, Fakten, Entitäten, Zitate, Kontexttext."""
    ca, cb = [h.chunk_id for h in a.chunks], [h.chunk_id for h in b.chunks]
    ctx_a, ctx_b = render_context(a).text, render_context(b).text
    return {
        "Frage": a.question,
        "Guardrail gleich": a.weak_evidence == b.weak_evidence,
        "Top-10 gleiche Menge": set(ca) == set(cb),
        "Top-10 gleiche Reihenfolge": ca == cb,
        "Überschneidung Top-10": round(overlap(ca, cb), 2),
        "Fakten gleich": [f.edge_id for f in a.facts] == [f.edge_id for f in b.facts],
        f"Fakten {names[0]}/{names[1]}": f"{len(a.facts)}/{len(b.facts)}",
        "Entitäten gleich": [e.label for e in a.entities] == [e.label for e in b.entities],
        "Zitate gleich": [c.key for c in a.citations] == [c.key for c in b.citations],
        "Kontext gleich": normalize_context(ctx_a) == normalize_context(ctx_b),
        "Kontext byte-gleich": ctx_a == ctx_b,
        f"Fakten nur {names[0]}": len({f.edge_id for f in a.facts} - {f.edge_id for f in b.facts}),
        f"Fakten nur {names[1]}": len({f.edge_id for f in b.facts} - {f.edge_id for f in a.facts}),
        f"ms search {names[0]}/{names[1]}": f"{a.diagnostics.timings_ms.get('search')}/{b.diagnostics.timings_ms.get('search')}",
        f"ms graph {names[0]}/{names[1]}": f"{a.diagnostics.timings_ms.get('graph')}/{b.diagnostics.timings_ms.get('graph')}",
    }


def context_diff(a: RetrievalResult, b: RetrievalResult, n: int = 20) -> list[str]:
    import difflib

    la, lb = normalize_context(render_context(a).text).splitlines(), normalize_context(render_context(b).text).splitlines()
    return [l for l in difflib.unified_diff(la, lb, lineterm="", n=0) if not l.startswith(("---", "+++", "@@"))][:n]


# --------------------------------------------------------------------------- Re-Vektorisierung (optional)
def reembed_run(run_dir: str | Path, out_dir: str | Path, *, base_url: str, api_key: str | None, model: str, text_prefix: str = "", batch: int = 64) -> Path:
    """``response.json`` eines Laufs mit dem konfigurierten Embedding-Endpunkt neu vektorisieren und als neuen Lauf
    schreiben (``out_dir/response.json``). Texte, Graph und IDs bleiben; nur ``chunks[].embedding`` ändert sich —
    damit lässt sich derselbe Test mit einem anderen Embedding-Modell wiederholen."""
    import httpx

    src = Path(run_dir) / "response.json" if Path(run_dir).is_dir() else Path(run_dir)
    resp = json.loads(src.read_text(encoding="utf-8"))
    texts = [text_prefix + c["text"] for c in resp["chunks"]]
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    vectors: list[list[float]] = []
    with httpx.Client(base_url=base_url, headers=headers, timeout=180.0, trust_env=False) as client:
        for i in range(0, len(texts), batch):
            r = client.post("/embeddings", json={"model": model, "input": texts[i : i + batch]})
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            vectors.extend(d["embedding"] for d in data)
    for c, v in zip(resp["chunks"], vectors, strict=True):
        c["embedding"] = v
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "response.json").write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- Ressourcen und Last
def docker_mem_mb(container: str) -> float | None:
    """RSS des Containers laut ``docker stats`` (MiB); None, wenn docker nicht erreichbar ist."""
    try:
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container], capture_output=True, text=True, timeout=20).stdout
        m = _re.search(r"([\d.]+)\s*([KMG])i?B", out.split("/")[0])
        if not m:
            return None
        factor = {"K": 1 / 1024, "M": 1.0, "G": 1024.0}[m.group(2)]
        return round(float(m.group(1)) * factor, 1)
    except Exception:  # noqa: BLE001 - Anzeige
        return None


def rss_mb() -> float:
    import psutil

    return round(psutil.Process().memory_info().rss / 2**20, 1)


def dir_size_mb(path: str | Path) -> float:
    p = Path(path)
    if p.is_file():
        return round(p.stat().st_size / 2**20, 2)
    return round(sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 2**20, 2)


def timeit(fn: Callable[[], Any], rounds: int = 5) -> dict[str, float]:
    ts = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    return {"min_ms": round(ts[0], 1), "p50_ms": round(ts[len(ts) // 2], 1), "max_ms": round(ts[-1], 1)}


def concurrent(fn: Callable[[int], Any], *, workers: int = 10, calls: int = 30) -> dict[str, float]:
    """``calls`` Aufrufe mit ``workers`` Threads gleichzeitig; Latenz je Aufruf und Gesamtdurchsatz."""
    lat: list[float] = []

    def one(i: int) -> None:
        t0 = time.perf_counter()
        fn(i)
        lat.append((time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, range(calls)))
    wall = time.perf_counter() - t0
    lat.sort()
    return {"calls": calls, "workers": workers, "p50_ms": round(lat[len(lat) // 2], 1), "p95_ms": round(lat[int(len(lat) * 0.95) - 1], 1), "max_ms": round(lat[-1], 1), "wall_s": round(wall, 2), "calls_per_s": round(calls / wall, 1)}
