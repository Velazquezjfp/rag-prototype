"""``osi`` command line: bootstrap | ingest | status | verify | search | delete."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False, help="opensearch-index: OpenSearch store for docling-graph output")


@app.callback()
def _main(
    url: str | None = typer.Option(None, "--url", help="OpenSearch URL (overrides OSI__OPENSEARCH__URL)"),
    prefix: str | None = typer.Option(None, "--prefix", help="index prefix (overrides OSI__INDEX__PREFIX)"),
    ontology: Path | None = typer.Option(None, "--ontology", help="ontology.yaml (overrides OSI__ONTOLOGY__PATH)"),
    log_level: str = typer.Option("WARNING", "--log-level"),
) -> None:
    logging.basicConfig(level=log_level.upper(), format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    # the client logs every non-2xx response; a 404 on the manifest lookup is the normal first-ingest path
    logging.getLogger("opensearch").setLevel(max(logging.ERROR, logging.getLogger().level))
    if url:
        os.environ["OSI__OPENSEARCH__URL"] = url
    if prefix:
        os.environ["OSI__INDEX__PREFIX"] = prefix
    if ontology:
        os.environ["OSI__ONTOLOGY__PATH"] = str(ontology)
    from .settings import get_settings

    get_settings.cache_clear()


def _ctx():
    from .client import make_client
    from .indexer import Indexer
    from .ontology import load_ontology
    from .settings import get_settings

    s = get_settings()
    client = make_client(s.opensearch)
    return s, client, Indexer(client, s, load_ontology(s.ontology.path))


def _out(obj: Any, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
    else:
        typer.echo(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def _err(msg: str) -> None:
    typer.echo(f"error: {msg}", err=True)


@app.command()
def bootstrap(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Create the indices (bhb-chunks/-nodes/-documents/-manifest) and the RRF search pipeline; idempotent."""
    _, _, ix = _ctx()
    report = ix.bootstrap(dry_run=dry_run)
    typer.echo(json.dumps(report, indent=1))


@app.command()
def ingest(
    paths: list[Path] = typer.Argument(..., help="run directory (response.json | meta.json+chunks.json) or a response.json"),
    doc_id: str | None = typer.Option(None, "--doc-id", help="logical document id override (e.g. BHB-PLT-0007)"),
    force: bool = typer.Option(False, "--force", help="re-index even if this exact output is already active; take over a stale lease"),
    replace: bool = typer.Option(False, "--replace", help="allow replacing a differently named file under the same doc_id"),
    dry_run: bool = typer.Option(False, "--dry-run", help="resolve, fingerprint, validate and print the plan; write nothing"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Index docling-graph output idempotently: same output = no-op, new output = replace that document's records."""
    from .indexer import IngestError
    from .loader import LoadError, load_run

    _, _, ix = _ctx()
    failures = 0
    for path in paths:
        try:
            resp = load_run(path)
            plan = ix.plan(resp, doc_id_override=doc_id, force=force, replace=replace)
            report = ix.ingest(plan, resp, dry_run=dry_run, force=force)
        except (LoadError, IngestError, ValueError) as exc:
            failures += 1
            _err(f"{path}: {exc}")
            continue
        for w in plan.warnings:
            typer.echo(f"warning: {w}", err=True)
        if json_out:
            _out({"path": str(path), **report.__dict__}, True)
        else:
            p = report.plan
            typer.echo(
                f"{path}: {report.status:7} doc_id={p['doc_id']} ({p['doc_id_source']}) sha={p['doc_sha256'][:12]} "
                f"run={p['run_id'][:12]} counts={report.counts} swept={report.swept or '-'} "
                f"reasons={p['reasons']} {report.duration_s}s"
            )
            if report.sweep_query:
                typer.echo(f"  would sweep: {json.dumps(report.sweep_query)}")
    raise typer.Exit(code=1 if failures else 0)


@app.command()
def status(json_out: bool = typer.Option(False, "--json")) -> None:
    """Manifests, counts per index and per document, cross-document node ids, things needing attention."""
    _, _, ix = _ctx()
    _out(ix.status(), json_out)


@app.command()
def verify(json_out: bool = typer.Option(False, "--json")) -> None:
    """Cluster gate: reachable, version, k-NN plugin present, dim-N vector round trip on a temporary index."""
    from .client import cluster_info, verify_knn_roundtrip
    from .mappings import IndexNames
    from .settings import redact

    s, client, _ = _ctx()
    info = cluster_info(client)
    out: dict[str, Any] = {
        "endpoint": redact(s.opensearch),
        "cluster": info.cluster_name,
        "version": info.version,
        "distribution": info.distribution,
        "plugins": info.plugins,
        "knn_plugin": info.has_knn,
        "rrf_supported": info.supports_rrf,
    }
    if not info.has_knn:
        out["knn_roundtrip"] = "SKIPPED - opensearch-knn plugin missing (request k-NN by name)"
        _out(out, json_out)
        raise typer.Exit(code=1)
    out["knn_roundtrip"] = verify_knn_roundtrip(client, dim=s.embedding.dim, names=IndexNames(s.index.prefix))
    _out(out, json_out)


@app.command()
def search(
    text: str | None = typer.Option(None, "--text", help="BM25 over text/body_text/caption"),
    knn_from_chunk: str | None = typer.Option(None, "--knn-from-chunk", help="k-NN with the stored vector of this chunk"),
    identifier: list[str] = typer.Option([], "--identifier", help="exact identifier (ticket, SOP, host, ...)"),
    node_id: str | None = typer.Option(None, "--node-id", help="node across documents + its edges"),
    hybrid: bool = typer.Option(False, "--hybrid", help="fuse the given clauses with RRF (bhb-rrf pipeline)"),
    k: int = typer.Option(10, "--k"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Smoke queries against the indexed data (no embedding endpoint needed)."""
    from . import search as sq

    s, client, ix = _ctx()
    names = ix.names
    if node_id:
        _out(sq.node_lookup(client, names, node_id), json_out)
        return
    vector = sq.stored_vector(client, names, knn_from_chunk) if knn_from_chunk else None
    if hybrid:
        hits = sq.hybrid_rrf(client, names, text=text, vector=vector, identifiers=identifier or None, k=k)
    elif vector is not None:
        hits = sq.knn(client, names, vector, k)
    elif identifier:
        hits = sq.by_identifiers(client, names, identifier, k)
    elif text:
        hits = sq.bm25(client, names, text, k)
    else:
        _err("give --text, --knn-from-chunk, --identifier or --node-id")
        raise typer.Exit(code=2)
    _out(hits, json_out)


@app.command()
def delete(
    doc_id: str = typer.Option(..., "--doc-id"),
    yes: bool = typer.Option(False, "--yes", help="do not ask"),
) -> None:
    """Remove every record of one document (chunks, nodes, document, manifest)."""
    _, _, ix = _ctx()
    if not yes and not typer.confirm(f"delete all records of {doc_id} from prefix {ix.names.prefix}?"):
        raise typer.Exit(code=1)
    typer.echo(json.dumps(ix.delete_document(doc_id)))


if __name__ == "__main__":
    app()
