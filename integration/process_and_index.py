#!/usr/bin/env python3
"""Process PDFs with the running docling-graph service and index every result with opensearch-index (osi).

    python process_and_index.py --pdf ../user-manual-books/handbuch_daten/handbuch/Betriebshandbuch_CaaS-Plattform.pdf \
        --run-suffix gemma4 --no-vlm --timeout 10800
    python process_and_index.py --dir ../user-manual-books/handbuch_daten/handbuch --run-suffix gemma4 --no-vlm
    python process_and_index.py --pdf X.pdf --skip-existing --dry-run     # re-plan an existing run dir, no service call

Per book: POST /v1/process (waits on 503 + Retry-After while the service is busy) -> write the run directory in the
process_via_api layout (<out>/<pdf stem>[-<suffix>]/{response,chunks,graph,summary}.json + markdown.md) -> osi plan
and ingest (idempotent: identical output = noop, new extraction = that book's records replaced). Books are
independent: a failure marks that book and the queue continues; nothing reaches OpenSearch for a book whose
processing failed. The service takes one job at a time, so --concurrency defaults to 1; the gain of asyncio is
pipelining (book N indexes while book N+1 converts) and non-blocking back-off.

Runs with the opensearch-index venv (`pip install -r requirements.txt` in this folder); OpenSearch settings come from
opensearch-index/.env / OSI__* exactly as for the osi CLI. The docling-graph service is never modified.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import dataclasses
import json
import logging
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
OSI_DIR = HERE.parent / "opensearch-index"
sys.path.insert(0, str(OSI_DIR / "src"))
os.environ.setdefault("OSI_CONFIG", str(OSI_DIR / "config.yaml"))

log = logging.getLogger("process_and_index")

DEFAULT_DGS_URL = "http://localhost:8080"
DEFAULT_RETRY_AFTER_S = 30.0
PIPELINE_FLAGS = {  # CLI flag -> pipeline_config key (same names as docling-graph/scripts/process_via_api.py)
    "no_vlm": "vlm_enabled",
    "no_graph": "graph_enabled",
    "no_embed": "embedding_enabled",
    "no_ocr": "ocr_enabled",
}


# ----------------------------------------------------------------------------------------------- data


@dataclass
class IndexFlags:
    """Options handed to the indexer, same meaning as `osi ingest --doc-id/--force/--replace/--dry-run`."""

    doc_id: str | None = None
    force: bool = False
    replace: bool = False
    dry_run: bool = False


@dataclass
class RunConfig:
    dgs_url: str
    out_root: Path
    run_suffix: str | None
    options: dict[str, Any]
    ontology: dict[str, Any] | None
    concurrency: int = 1
    timeout_s: float = 10800.0
    skip_existing: bool = False
    index: IndexFlags = field(default_factory=IndexFlags)


@dataclass
class BookResult:
    pdf: Path
    run_dir: Path
    status: str = "failed"  # active | noop | dry-run | failed
    phase: str = "process"  # phase reached: process | write | index | done
    seconds: dict[str, float] = field(default_factory=dict)
    report: dict[str, Any] | None = None
    degraded: dict[str, Any] | None = None
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.status == "failed"


class ProcessError(RuntimeError):
    def __init__(self, status: int, text: str):
        super().__init__(f"HTTP {status}: {text[:2000]}")
        self.status = status
        self.text = text[:2000]


# ----------------------------------------------------------------------------------------------- service


def _retry_after(value: str | None) -> float:
    try:
        return max(0.0, float(value)) if value is not None else DEFAULT_RETRY_AFTER_S
    except ValueError:  # HTTP-date form; the service sends seconds
        return DEFAULT_RETRY_AFTER_S


def request_body(pdf: Path, options: dict[str, Any], ontology: dict[str, Any] | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "document": {
            "name": pdf.name,
            "format": pdf.suffix.lstrip(".") or "pdf",
            "base64_content": base64.b64encode(pdf.read_bytes()).decode(),
        },
        "pipeline_config": options,
    }
    if ontology is not None:
        body["ontology_graph"] = ontology
    return body


async def process_one(
    client: httpx.AsyncClient,
    pdf: Path,
    options: dict[str, Any],
    ontology: dict[str, Any] | None,
    *,
    deadline_s: float,
) -> dict[str, Any]:
    """POST /v1/process; on 503 sleep Retry-After (default 30 s) and retry until the deadline; other errors raise."""
    body = request_body(pdf, options, ontology)
    end = time.monotonic() + deadline_s
    attempt = 0
    while True:
        attempt += 1
        r = await client.post("/v1/process", json=body)
        if r.status_code == 200:
            return r.json()
        if r.status_code != 503:
            raise ProcessError(r.status_code, r.text)
        wait = _retry_after(r.headers.get("Retry-After"))
        remaining = end - time.monotonic()
        if wait > remaining:
            raise ProcessError(503, f"service busy for {deadline_s:.0f}s ({attempt} attempts): {r.text}")
        log.info("%s: service busy (503), retrying in %.0fs (attempt %d)", pdf.name, wait, attempt)
        await asyncio.sleep(wait)


def preflight(dgs_url: str) -> dict[str, Any]:
    """healthz + capabilities of the service, so the run log states which models did the extraction."""
    with httpx.Client(base_url=dgs_url, timeout=httpx.Timeout(20, connect=10), trust_env=False) as client:
        health = client.get("/healthz")
        if health.status_code != 200:
            raise ProcessError(health.status_code, f"healthz: {health.text}")
        caps = client.get("/v1/capabilities")
        caps.raise_for_status()
        return caps.json()


def describe_capabilities(caps: dict[str, Any]) -> str:
    models = caps.get("models", {})
    parts = []
    for key in ("llm", "vlm", "embedding"):
        m = models.get(key) or {}
        state = "on" if m.get("enabled", True) else "off"
        parts.append(f"{key}={m.get('model')}({state})")
    limits = caps.get("limits", {})
    parts.append(f"deadline={limits.get('request_deadline_s')}s jobs={limits.get('concurrent_jobs')}")
    parts.append(f"endpoints={caps.get('endpoint_status')}")
    return " ".join(parts)


# ----------------------------------------------------------------------------------------------- run dir


def run_dir_name(pdf: Path, suffix: str | None) -> str:
    return f"{pdf.stem}-{suffix}" if suffix else pdf.stem


def summarize(resp: dict[str, Any], *, http_seconds: float | None = None) -> dict[str, Any]:
    """Same block as docling-graph/scripts/process_via_api.py; node/edge counts taken from the lists themselves."""
    chunks = resp.get("chunks") or []
    g = resp.get("graph")
    meta = (g or {}).get("meta", {})
    doc = resp.get("document", {})
    return {
        "http_seconds": http_seconds,
        "cached": resp.get("cached"),
        "pages": doc.get("pages"),
        "tables": doc.get("tables"),
        "pictures": doc.get("pictures"),
        "chunks": len(chunks),
        "chunks_by_kind": dict(Counter(c.get("kind") for c in chunks)),
        "embedded": sum(c.get("embedding") is not None for c in chunks),
        "max_tokens": max((c.get("token_count") or 0 for c in chunks), default=0),
        "degraded": resp.get("degraded"),
        "errors": resp.get("errors"),
        "timings_s": resp.get("timings_s"),
        "versions": resp.get("versions"),
        "nodes": len(g.get("nodes", [])) if g else None,
        "edges": len(g.get("edges", [])) if g else None,
        "nodes_by_type": meta.get("nodes_by_type") if g else None,
        "edges_by_type": meta.get("edges_by_type") if g else None,
        "edges_by_polarity": meta.get("edges_by_polarity") if g else None,
        "unresolved_targets": len(meta.get("unresolved_targets", [])) if g else None,
        "conflicts": meta.get("conflicts") if g else None,
    }


def write_run_dir(resp: dict[str, Any], out_dir: Path, *, http_seconds: float | None = None) -> Path:
    """response.json, markdown.md, chunks.json, graph.json (if present), summary.json - the process_via_api layout."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "response.json").write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
    (out_dir / "markdown.md").write_text(resp.get("markdown") or "", encoding="utf-8")
    (out_dir / "chunks.json").write_text(json.dumps(resp.get("chunks") or [], ensure_ascii=False, indent=1), encoding="utf-8")
    if resp.get("graph"):
        (out_dir / "graph.json").write_text(json.dumps(resp["graph"], ensure_ascii=False, indent=1), encoding="utf-8")
    summary = summarize(resp, http_seconds=http_seconds)
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_dir


# ----------------------------------------------------------------------------------------------- indexer


def _osi_settings():
    from opensearch_index.settings import Settings

    env_file = OSI_DIR / ".env"
    return Settings(_env_file=str(env_file) if env_file.is_file() else None)


def _ontology_path(settings) -> Path:
    """OSI__ONTOLOGY__PATH may be relative to the opensearch-index folder (as in its .env.example)."""
    p = Path(settings.ontology.path)
    if p.is_absolute() or p.is_file():
        return p
    alt = OSI_DIR / p
    return alt if alt.is_file() else p


def index_run(out_dir: Path, flags: IndexFlags):
    """opensearch_index: load_run -> Indexer.plan -> Indexer.ingest. Synchronous; the orchestrator runs it in a thread."""
    from opensearch_index.client import make_client
    from opensearch_index.indexer import Indexer
    from opensearch_index.loader import load_run
    from opensearch_index.ontology import load_ontology

    settings = _osi_settings()
    client = make_client(settings.opensearch)
    indexer = Indexer(client, settings, load_ontology(_ontology_path(settings)))
    resp = load_run(out_dir)
    plan = indexer.plan(resp, doc_id_override=flags.doc_id, force=flags.force, replace=flags.replace)
    for w in plan.warnings:
        log.warning("%s: %s", out_dir.name, w)
    return indexer.ingest(plan, resp, dry_run=flags.dry_run, force=flags.force)


def _as_dict(report: Any) -> dict[str, Any]:
    if isinstance(report, dict):
        return report
    return dataclasses.asdict(report)


# ----------------------------------------------------------------------------------------------- orchestration


def _log_extraction(pdf: Path, resp: dict[str, Any], seconds: float) -> None:
    s = summarize(resp, http_seconds=seconds)
    log.info(
        "%s: converted in %.0fs cached=%s pages=%s chunks=%s embedded=%s nodes=%s edges=%s unresolved=%s degraded=%s",
        pdf.name, seconds, s["cached"], s["pages"], s["chunks"], s["embedded"], s["nodes"], s["edges"],
        s["unresolved_targets"], s["degraded"],
    )
    for err in (resp.get("errors") or [])[:10]:
        log.warning("%s: service error: %s", pdf.name, str(err)[:300])
    degraded = resp.get("degraded") or {}
    if any(degraded.values()):
        log.warning("%s: DEGRADED %s - inspect %s before trusting retrieval on this book", pdf.name, degraded, "summary.json")


async def _one_book(client: httpx.AsyncClient, pdf: Path, cfg: RunConfig, sem: asyncio.Semaphore) -> BookResult:
    run_dir = cfg.out_root / run_dir_name(pdf, cfg.run_suffix)
    res = BookResult(pdf=pdf, run_dir=run_dir)
    try:
        if cfg.skip_existing and (run_dir / "response.json").is_file():
            log.info("%s: %s/response.json exists - skipping the service call (--skip-existing)", pdf.name, run_dir)
            res.seconds["process"] = 0.0
        else:
            async with sem:
                t0 = time.monotonic()
                log.info("%s: POST %s/v1/process (%.1f MB, options=%s)", pdf.name, cfg.dgs_url,
                         pdf.stat().st_size / 1e6, cfg.options)
                resp = await process_one(client, pdf, cfg.options, cfg.ontology, deadline_s=cfg.timeout_s)
                res.seconds["process"] = round(time.monotonic() - t0, 1)
            res.phase = "write"
            t0 = time.monotonic()
            write_run_dir(resp, run_dir, http_seconds=res.seconds["process"])
            res.seconds["write"] = round(time.monotonic() - t0, 1)
            res.degraded = resp.get("degraded")
            _log_extraction(pdf, resp, res.seconds["process"])
        res.phase = "index"
        t0 = time.monotonic()
        report = _as_dict(await asyncio.to_thread(index_run, run_dir, cfg.index))
        res.seconds["index"] = round(time.monotonic() - t0, 1)
        res.report = report
        res.status = str(report.get("status", "failed"))
        res.error = report.get("error")
        (run_dir / "index_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        plan = report.get("plan") or {}
        log.info(
            "%s: index %s doc_id=%s (%s) run=%s counts=%s swept=%s reasons=%s in %.1fs",
            pdf.name, res.status, plan.get("doc_id"), plan.get("doc_id_source"), str(plan.get("run_id"))[:12],
            report.get("counts"), report.get("swept") or "-", plan.get("reasons"), res.seconds["index"],
        )
        if report.get("sweep_query"):
            log.info("%s: would sweep %s", pdf.name, json.dumps(report["sweep_query"]))
        res.phase = "done"
    except Exception as exc:  # noqa: BLE001 - per-book isolation: the queue continues, main() exits 1
        res.status = "failed"
        res.error = f"{type(exc).__name__}: {exc}"
        log.error("%s: failed during %s: %s", pdf.name, res.phase, res.error)
    return res


async def run(pdfs: list[Path], cfg: RunConfig, transport: httpx.AsyncBaseTransport | None = None) -> list[BookResult]:
    """Process and index every PDF; at most cfg.concurrency service calls in flight; indexing overlaps conversion."""
    sem = asyncio.Semaphore(cfg.concurrency)
    timeout = httpx.Timeout(cfg.timeout_s, connect=10)
    # trust_env=False: a corporate proxy must never sit between this script and the service (they drop long requests)
    async with httpx.AsyncClient(base_url=cfg.dgs_url, timeout=timeout, trust_env=False, transport=transport) as client:
        return list(await asyncio.gather(*(_one_book(client, pdf, cfg, sem) for pdf in pdfs)))


# ----------------------------------------------------------------------------------------------- CLI


def collect_pdfs(args: argparse.Namespace) -> list[Path]:
    pdfs: list[Path] = [p.resolve() for p in (args.pdf or [])]
    if args.dir:
        pdfs.extend(sorted(p.resolve() for p in args.dir.glob(args.glob) if p.is_file()))
    seen: set[Path] = set()
    unique = [p for p in pdfs if not (p in seen or seen.add(p))]
    missing = [p for p in unique if not p.is_file()]
    if missing:
        raise SystemExit(f"error: not a file: {', '.join(map(str, missing))}")
    if not unique:
        raise SystemExit("error: no documents - pass --pdf <file> and/or --dir <folder> [--glob '*.pdf']")
    return unique


def build_config(args: argparse.Namespace) -> RunConfig:
    options = {key: False for flag, key in PIPELINE_FLAGS.items() if getattr(args, flag)}
    if args.contract:
        options["extraction_contract"] = args.contract
    ontology = None
    if args.ontology:
        import yaml

        ontology = yaml.safe_load(args.ontology.read_text(encoding="utf-8"))
    return RunConfig(
        dgs_url=args.dgs_url.rstrip("/"),
        out_root=args.out.resolve(),
        run_suffix=args.run_suffix or None,
        options=options,
        ontology=ontology,
        concurrency=max(1, args.concurrency),
        timeout_s=args.timeout,
        skip_existing=args.skip_existing,
        index=IndexFlags(doc_id=args.doc_id, force=args.force, replace=args.replace, dry_run=args.dry_run),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group("documents")
    src.add_argument("--pdf", type=Path, action="append", help="document to process (repeatable)")
    src.add_argument("--dir", type=Path, help="process every file in this folder matching --glob")
    src.add_argument("--glob", default="*.pdf")
    svc = ap.add_argument_group("docling-graph service")
    svc.add_argument("--dgs-url", default=os.environ.get("DGS_URL", DEFAULT_DGS_URL))
    svc.add_argument("--out", type=Path, default=HERE.parent / "out", help="run directories go to <out>/<stem>[-<suffix>]")
    svc.add_argument("--run-suffix", default=None, help="tag for the run directory, e.g. the extraction LLM: gemma4")
    svc.add_argument("--no-vlm", action="store_true", help="pipeline_config.vlm_enabled=false")
    svc.add_argument("--no-graph", action="store_true")
    svc.add_argument("--no-embed", action="store_true")
    svc.add_argument("--no-ocr", action="store_true")
    svc.add_argument("--contract", choices=["dense", "direct"], default=None)
    svc.add_argument("--ontology", type=Path, default=None, help="ontology YAML to send as ontology_graph (default: the service's)")
    svc.add_argument("--concurrency", type=int, default=1, help="service calls in flight (the service accepts one job)")
    svc.add_argument("--timeout", type=float, default=10800.0,
                     help="seconds: HTTP read timeout AND total 503 back-off budget per book; keep >= DGS__SERVICE__REQUEST_DEADLINE_S")
    svc.add_argument("--skip-existing", action="store_true", help="if <run dir>/response.json exists, index it without calling the service")
    idx = ap.add_argument_group("indexer (osi ingest)")
    idx.add_argument("--doc-id", default=None, help="logical document id override (single book only)")
    idx.add_argument("--force", action="store_true", help="re-index even if this exact output is active; take over a stale lease")
    idx.add_argument("--replace", action="store_true", help="allow replacing a differently named file under the same doc_id")
    idx.add_argument("--dry-run", action="store_true", help="indexer plan only, nothing written to OpenSearch (the service call still happens unless --skip-existing)")
    ap.add_argument("--log-level", default="INFO")
    ap.add_argument("--json", action="store_true", help="print the per-book results as JSON at the end")
    args = ap.parse_args(argv)
    if args.doc_id and (args.dir or len(args.pdf or []) > 1):
        ap.error("--doc-id applies to exactly one document")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", stream=sys.stderr)
    logging.getLogger("opensearch").setLevel(logging.ERROR)  # the manifest 404 on a first ingest is normal
    logging.getLogger("httpx").setLevel(logging.WARNING)
    pdfs = collect_pdfs(args)
    cfg = build_config(args)

    needs_service = [p for p in pdfs if not (cfg.skip_existing and (cfg.out_root / run_dir_name(p, cfg.run_suffix) / "response.json").is_file())]
    if needs_service:
        try:
            caps = preflight(cfg.dgs_url)
        except (httpx.HTTPError, ProcessError) as exc:
            log.error("docling-graph service at %s not usable: %s", cfg.dgs_url, exc)
            return 2
        log.info("service %s: %s", cfg.dgs_url, describe_capabilities(caps))
        deadline = (caps.get("limits") or {}).get("request_deadline_s")
        if deadline and cfg.timeout_s < float(deadline):
            log.warning("--timeout %.0fs is below the service deadline %.0fs; a long book would time out client-side", cfg.timeout_s, float(deadline))
    log.info("%d document(s) -> %s (suffix=%s, concurrency=%d, skip_existing=%s, index=%s)",
             len(pdfs), cfg.out_root, cfg.run_suffix, cfg.concurrency, cfg.skip_existing, dataclasses.asdict(cfg.index))

    t0 = time.monotonic()
    results = asyncio.run(run(pdfs, cfg))
    total = time.monotonic() - t0

    for r in results:
        line = f"{r.status:8} {r.pdf.name} -> {r.run_dir.name} {r.seconds}"
        if r.error:
            line += f" error={r.error}"
        print(line)
    failed = [r for r in results if r.failed]
    print(f"{len(results) - len(failed)}/{len(results)} ok in {total:.0f}s" + (f"; failed: {', '.join(r.pdf.name for r in failed)}" if failed else ""))
    if args.json:
        print(json.dumps([{**dataclasses.asdict(r), "pdf": str(r.pdf), "run_dir": str(r.run_dir)} for r in results], ensure_ascii=False, indent=1, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
