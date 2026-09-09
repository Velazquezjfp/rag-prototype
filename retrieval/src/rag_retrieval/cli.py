"""``rag-retrieve`` command line: ask | graph-stats | entities | check."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="rag-retrieval: hybrid search + graph expansion over the indexed manuals, prompt injection, answer",
)


@app.callback()
def _main(
    url: str | None = typer.Option(None, "--url", help="OpenSearch URL (overrides RAG__OPENSEARCH__URL)"),
    prefix: str | None = typer.Option(None, "--prefix", help="index prefix (overrides RAG__INDEX__PREFIX)"),
    ontology: Path | None = typer.Option(None, "--ontology", help="ontology.yaml (overrides RAG__ONTOLOGY__PATH)"),
    log_level: str = typer.Option("WARNING", "--log-level"),
) -> None:
    logging.basicConfig(level=log_level.upper(), format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    logging.getLogger("opensearch").setLevel(max(logging.ERROR, logging.getLogger().level))
    logging.getLogger("httpx").setLevel(max(logging.WARNING, logging.getLogger().level))
    if url:
        os.environ["RAG__OPENSEARCH__URL"] = url
    if prefix:
        os.environ["RAG__INDEX__PREFIX"] = prefix
    if ontology:
        os.environ["RAG__ONTOLOGY__PATH"] = str(ontology)
    from .settings import get_settings

    get_settings.cache_clear()


def _retriever():
    from .retriever import Retriever
    from .settings import get_settings

    return Retriever(get_settings())


def _llm(settings):
    from .chat import ChatClient

    return ChatClient(settings.llm)


def _out(obj: Any) -> None:
    typer.echo(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def _err(msg: str) -> None:
    typer.echo(f"error: {msg}", err=True)


def _load_history(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise typer.BadParameter("history file must be a JSON list of {role, content}")
    return [{"role": str(m["role"]), "content": str(m["content"])} for m in data]


def _short_via(via: str, limit: int = 3) -> str:
    parts = [p.strip() for p in via.split(",")]
    return ", ".join(parts[:limit]) + (f", … (+{len(parts) - limit})" if len(parts) > limit else "")


def _print_result(result, *, show_context: bool, budget: int | None, profile: str = "strict") -> None:
    d = result.diagnostics
    typer.echo(f"Frage: {result.question}")
    if d.rewritten_question and d.rewritten_question != result.question:
        typer.echo(f"Umformuliert: {d.rewritten_question}")
    typer.echo(f"Profil: {profile}" + (f" · Material: {d.material_chars} Zeichen" + (" (gekürzt)" if d.material_truncated else "") if d.material_chars else ""))
    if d.material_chars and d.question != result.question:
        typer.echo(f"Suchanfrage: {d.question}")
    if d.injection_suspected:
        typer.echo(f"Hinweis: Formulierungen wie Anweisungen in der Eingabe: {d.injection_suspected}")
    typer.echo(
        f"Modus: {result.mode} · Identifier: {d.identifiers or '-'} · Labels: {d.resolved_labels or '-'}"
        f" · Startknoten: {len(d.start_nodes)}"
    )
    if d.partial_labels:
        typer.echo(f"Teiltreffer in Labels: {d.partial_labels}")
    ch = " · ".join(
        f"{c.channel} {c.returned}" + (f" ({c.took_ms} ms)" if c.took_ms is not None else "") for c in d.channels
    )
    typer.echo(f"Kanäle: {ch}")
    if result.weak_evidence:
        typer.echo(f"Guardrail: SCHWACHE EVIDENZ – {result.weak_evidence_reason}")
    elif not d.guardrail_enabled:
        typer.echo("Guardrail: aus – Evidenz bewertet: " + (f"schwach ({d.assessed_reason})" if d.assessed_weak else "stark"))
    else:
        typer.echo("Guardrail: ok")
    for w in d.warnings:
        typer.echo(f"warning: {w}", err=True)
    typer.echo("")
    typer.echo(f"Treffer ({len(result.groups)} Quellen aus {len(result.chunks)} Chunks):")
    for g in result.groups:
        where = " › ".join(g.heading_breadcrumb) if g.heading_breadcrumb else ""
        if g.caption:
            where = f"{where} · {g.caption}" if where else g.caption
        if len(g.parts) > 1:
            where += f" ({len(g.parts)} Teile)"
        if not where:
            first = (g.parts[0].body_text or g.parts[0].text).strip().replace("\n", " ")
            where = f"„{first[:70]}…“"
        via = " ".join(
            f"{c.channel}#{c.rank}" + (f"({_short_via(c.via)})" if c.via and c.channel in ("identifier", "label", "graph") else "")
            for p in g.parts
            for c in p.channels
        )
        typer.echo(f" {g.rank:2d}. {g.cite} · {where}")
        typer.echo(f"     via {via}")
    if result.facts:
        typer.echo("")
        typer.echo(f"Fakten ({len(result.facts)}):")
        for f in result.facts:
            typer.echo(f" - {f.rendered}")
    if result.entities:
        typer.echo("")
        typer.echo(f"Entitäten ({len(result.entities)}):")
        for e in result.entities:
            typer.echo(f" - {e.rendered}")
    typer.echo("")
    typer.echo("Zeiten: " + " · ".join(f"{k} {v} ms" for k, v in d.timings_ms.items()))
    if show_context:
        from .prompt import render_context

        ctx = render_context(result, token_budget=budget)
        typer.echo("")
        typer.echo(f"----- Kontext (~{ctx.token_estimate} Tokens, {len(ctx.included_chunk_ids)} Chunks, {len(ctx.dropped_chunk_ids)} verworfen) -----")
        typer.echo(ctx.text)
        typer.echo("----- Ende Kontext -----")


@app.command()
def ask(
    question: str = typer.Argument(..., help="the question, in German"),
    graph: bool = typer.Option(True, "--graph/--no-graph", help="slow mode with 1-hop graph expansion (default) or fast mode"),
    k: int | None = typer.Option(None, "--k", help="chunks kept after fusion (RAG__RETRIEVAL__FINAL_K)"),
    doc: list[str] = typer.Option([], "--doc", help="restrict to these document ids (repeatable)"),
    json_out: bool = typer.Option(False, "--json", help="print the full RetrievalResult as JSON"),
    answer_: bool = typer.Option(False, "--answer", help="also ask the model (RAG__LLM__MODEL)"),
    stream: bool = typer.Option(False, "--stream", help="stream the answer token by token"),
    force: bool = typer.Option(False, "--force", help="call the model even when the guardrail says weak evidence"),
    model: str | None = typer.Option(None, "--model", help="override the chat model for this call"),
    show_context: bool = typer.Option(False, "--show-context", help="print the rendered context block"),
    budget: int | None = typer.Option(None, "--budget", help="context token budget (RAG__RETRIEVAL__CONTEXT_TOKEN_BUDGET)"),
    history_file: Path | None = typer.Option(None, "--history-file", help="JSON list of {role, content}; enables question rewriting"),
    profile: str | None = typer.Option(None, "--profile", help="strict | assistant (default: RAG__PROMPT__PROFILE, auto = assistant iff the guardrail is off)"),
    material_file: Path | None = typer.Option(None, "--material-file", help="log/command/script text attached as material (REQ-002); a pasted question is split automatically"),
) -> None:
    """Retrieve for one question; with --answer also generate the answer (exit 2 when the guardrail refuses)."""
    from .analysis import AnalysisSplitter, split_analysis
    from .chat import answer as answer_fn
    from .chat import rewrite_question
    from .material import split_material
    from .settings import resolve_profile

    r = _retriever()
    s = r.settings
    effective_profile = profile or resolve_profile(s)
    if effective_profile not in ("strict", "assistant"):
        raise typer.BadParameter("--profile must be strict or assistant")
    strict = effective_profile == "strict"
    material: str | None = material_file.read_text(encoding="utf-8") if material_file else None
    if material is None:
        split = split_material(question)
        question, material = split.instruction, split.material
    history = _load_history(history_file)
    rewritten = None
    llm = None
    if history:
        llm = _llm(s)
        rw = rewrite_question(history, question, llm)
        rewritten = rw.rewritten
        if rw.error:
            typer.echo(f"warning: rewrite failed ({rw.error}); using the original question", err=True)
    result = r.retrieve(rewritten or question, use_graph=graph, k=k, doc_ids=doc or None, material=material)
    if rewritten and rewritten != question:
        result.diagnostics.rewritten_question = rewritten
        result.question = question
    if json_out:
        _out(result.model_dump())
    else:
        _print_result(result, show_context=show_context, budget=budget, profile=effective_profile)
    if not answer_:
        return
    if strict and result.weak_evidence and not force and not history:
        typer.echo("")
        typer.echo(f"Antwort: {answer_fn(result, question, llm, history)}")  # type: ignore[arg-type]
        raise typer.Exit(code=2)
    llm = llm or _llm(s)
    typer.echo("")
    if strict and result.weak_evidence and not force:
        typer.echo("Hinweis: schwache Evidenz – Antwort aus dem Gesprächsverlauf (keine neuen Quellen)")
    typer.echo(f"Antwort ({model or s.llm.model}):")
    try:
        out = answer_fn(
            result,
            question,
            llm,
            history,
            stream=stream,
            force=force,
            model=model,
            token_budget=budget if budget is not None else s.retrieval.context_token_budget,
            max_facts=s.retrieval.max_facts_in_prompt,
            context_limit_tokens=s.llm.context_limit_tokens,
            max_history_turns=s.retrieval.history_turns,
            doc_ids=doc or None,
            profile=effective_profile,
            material=material,
            ecosystem=None if strict else r.ecosystem_summary(doc or None),
        )
        analysis = None
        if stream:
            if not strict:
                out = AnalysisSplitter(out)  # type: ignore[arg-type]
            for tok in out:  # type: ignore[union-attr]
                typer.echo(tok, nl=False)
            typer.echo("")
            analysis = getattr(out, "analysis", None)
            if getattr(out, "finish_reason", None) == "length":
                typer.echo("[Antwort vom Modell gekürzt (max_tokens) – RAG__LLM__MAX_TOKENS erhöhen]", err=True)
        else:
            if not strict:
                analysis, out = split_analysis(out)  # type: ignore[arg-type]
            typer.echo(out)
        if analysis is not None:
            typer.echo(f"[Einordnung: {analysis.summary_de()}]")
    except Exception as exc:  # noqa: BLE001
        _err(str(exc))
        raise typer.Exit(code=1) from exc
    finally:
        llm.close()


@app.command("graph-stats")
def graph_stats(json_out: bool = typer.Option(False, "--json")) -> None:
    """Size of the in-memory union graph: documents, node ids (shared across books), edges, labels, types."""
    st = _retriever().graph.stats()
    if json_out:
        _out(st.as_dict())
        return
    typer.echo(f"documents: {', '.join(st.documents)}")
    typer.echo(f"node ids: {st.node_ids} ({st.node_records} records, {st.shared_node_ids} shared across books)")
    typer.echo(f"edges: {st.edge_ids} ({st.negative_edges} negative) · labels/aliases indexed: {st.labels}")
    typer.echo("nodes by type: " + ", ".join(f"{t} {n}" for t, n in st.nodes_by_type.items()))
    typer.echo("edges by type: " + ", ".join(f"{t} {n}" for t, n in st.edges_by_type.items()))


@app.command()
def entities(
    text: str = typer.Argument(..., help="label, alias or question fragment to resolve against the graph"),
    hops: bool = typer.Option(True, "--hops/--no-hops", help="also list the 1-hop facts"),
) -> None:
    """Resolve a label to node ids across books, show occurrences and their 1-hop facts."""
    from . import facts as facts_mod
    from .query import match_labels

    r = _retriever()
    g = r.graph
    keys, resolved, terms = match_labels(text, g, max_ngram=r.settings.retrieval.label_max_ngram, min_chars=1)
    if not keys:
        typer.echo("no label or alias matches")
        raise typer.Exit(code=1)
    typer.echo(f"matched: {keys} · terms for node_labels: {terms}")
    for key in keys:
        for nid in sorted(resolved[key]):
            occ = g.occurrences(nid)
            typer.echo(f"\n{nid} ({occ[0].type}) label={occ[0].label!r} aliases={list(occ[0].aliases)}")
            for n in occ:
                attrs = facts_mod.render_attributes(n.attributes)
                typer.echo(f"  {n.doc_id} S. {', '.join(map(str, n.pages)) or '?'} chunks={len(n.chunk_ids)}" + (f" — {attrs}" if attrs else ""))
            if hops:
                expanded = g.expand([nid])
                for _eid, edges in sorted(expanded.items(), key=lambda kv: (kv[1][0].polarity != "negative", kv[1][0].type)):
                    typer.echo("  · " + facts_mod.render_fact(g, edges, relation_de=r.relation_labels.get(edges[0].type), edge_ref=False))


@app.command()
def check(json_out: bool = typer.Option(False, "--json")) -> None:
    """Aliases, indexed documents and their embedding model vs the configured one, embedding probe, LLM probe."""
    report = _retriever().check()
    _out(report)
    raise typer.Exit(code=0 if report.get("ok") else 1)
