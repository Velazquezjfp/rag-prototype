"""``chat-ask`` (headless turn), ``chat-db`` (alembic), ``chat-doctor`` (is everything wired?)."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

import typer

from .settings import get_settings, redact_db_url

ask_app = typer.Typer(add_completion=False, help="Ask one question headlessly through the real service (streams the answer).")
db_app = typer.Typer(add_completion=False, help="Schema management (Alembic) for CHAT__DB__URL.")
doctor_app = typer.Typer(add_completion=False, help="Check DB, OpenSearch documents, LLM endpoint, user policy and prompt budget.")


def _logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("opensearch").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)


# ------------------------------------------------------------------------------------------------ chat-ask


@ask_app.command()
def ask(
    question: str = typer.Argument(..., help="Die Frage (Deutsch)."),
    graph: bool = typer.Option(True, "--graph/--no-graph", help="slow mode with graph expansion / fast mode"),
    user: str = typer.Option("dev", "--user", help="mock user id (rag_users.USERS)"),
    conversation: str | None = typer.Option(None, "--conversation", help="continue this conversation id"),
    doc_id: list[str] = typer.Option([], "--doc-id", help="restrict to these manuals (repeatable)"),
    json_out: bool = typer.Option(False, "--json", help="print the TurnResult as JSON instead of streaming"),
    log_level: str = typer.Option("WARNING", "--log-level"),
) -> None:
    from rag_users import EnvAuthAdapter, Unauthenticated

    from .service import TurnRefused
    from .wiring import build_service

    _logging(log_level)
    try:
        ctx = EnvAuthAdapter(user).current()
    except Unauthenticated as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    svc = build_service(get_settings())
    try:
        if conversation:
            conv, _ = svc.resume(ctx, conversation)
        else:
            conv = svc.start_conversation(ctx, use_graph=graph, doc_ids=doc_id or None)
        turn = svc.ask(ctx, conv.id, question, use_graph=graph, doc_ids=doc_id or None)
    except TurnRefused as exc:
        typer.echo(f"abgelehnt ({exc.reason}): {exc.message_de}", err=True)
        raise typer.Exit(2) from None

    if json_out:
        res = turn.collect()
        typer.echo(json.dumps(res.__dict__, ensure_ascii=False, indent=2, default=str))
        return
    typer.echo(f"[{ctx.user_id} · Gespräch {conv.id} · {'graph' if graph else 'fast'} · Handbücher {doc_id or 'alle erlaubten'}]", err=True)
    if turn.question_rewritten:
        typer.echo(f"[umformulierte Frage: {turn.question_rewritten}]", err=True)
    try:
        for tok in turn.tokens():
            sys.stdout.write(tok)
            sys.stdout.flush()
    finally:
        if not turn.done:
            turn.abort()
    sys.stdout.write("\n")
    res = turn.to_result()
    if res.citations:
        typer.echo("\nQuellen:")
        for c in res.citations:
            title = f" · {c['doc_title']}" if c.get("doc_title") else ""
            typer.echo(f"  [{c['key']}]{title}")
    typer.echo(
        f"\n[{res.finish_reason} · {res.latency_ms} ms · guardrail={res.guardrail} · heute noch {res.remaining_today} Nachricht(en) · "
        f"noch {res.turns_left} Runde(n) in diesem Gespräch]",
        err=True,
    )


# -------------------------------------------------------------------------------------------------- chat-db


@db_app.command()
def upgrade(revision: str = typer.Argument("head")) -> None:
    """alembic upgrade (default: head) on CHAT__DB__URL."""
    from alembic import command

    from .db import alembic_config

    s = get_settings()
    command.upgrade(alembic_config(s.db.url), revision)
    typer.echo(f"upgraded {redact_db_url(s.db.url)} to {revision}")


@db_app.command()
def revision(message: str = typer.Option(..., "-m", "--message"), autogenerate: bool = typer.Option(True)) -> None:
    """alembic revision --autogenerate -m MESSAGE (compares the models with the live schema)."""
    from alembic import command

    from .db import alembic_config

    s = get_settings()
    command.revision(alembic_config(s.db.url), message=message, autogenerate=autogenerate)


@db_app.command()
def current() -> None:
    """Current schema revision vs. the head shipped with this package."""
    from .db import current_revision, head_revision, make_engine

    s = get_settings()
    engine = make_engine(s.db.url)
    cur, head = current_revision(engine), head_revision()
    typer.echo(f"{redact_db_url(s.db.url)}: current={cur} head={head} {'ok' if cur == head else 'UPGRADE NEEDED'}")
    if cur != head:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------------------------- chat-doctor


@doctor_app.command()
def doctor(json_out: bool = typer.Option(False, "--json"), log_level: str = typer.Option("WARNING", "--log-level")) -> None:
    """Exit 1 when something is off."""
    _logging(log_level)
    report = run_doctor()
    if json_out:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        for check in report["checks"]:
            mark = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}[check["status"]]
            typer.echo(f"{mark} {check['name']:<14} {check['detail']}")
        typer.echo(f"\n{'ok' if report['ok'] else 'PROBLEMS FOUND'}")
    if not report["ok"]:
        raise typer.Exit(1)


def run_doctor() -> dict[str, Any]:
    from rag_users import Policy, Unauthenticated, get_adapter
    from rag_users import get_settings as users_settings

    from .db import current_revision, head_revision, make_engine
    from .wiring import rag_settings

    s = get_settings()
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    # DB + schema
    try:
        engine = make_engine(s.db.url)
        cur, head = current_revision(engine), head_revision()
        if cur == head:
            add("db", "ok", f"{redact_db_url(s.db.url)} at revision {cur}")
        elif cur is None:
            add("db", "fail" if not s.db.auto_upgrade else "warn", f"{redact_db_url(s.db.url)} has no schema yet (auto_upgrade={s.db.auto_upgrade}; chat-db upgrade)")
        else:
            add("db", "fail", f"{redact_db_url(s.db.url)} at {cur}, package head is {head}: chat-db upgrade")
    except Exception as exc:  # noqa: BLE001
        add("db", "fail", f"{redact_db_url(s.db.url)}: {exc}"[:300])

    # OpenSearch documents via the catalog
    rag = None
    try:
        rag = rag_settings()
        from opensearch_index.client import make_client
        from opensearch_index.mappings import IndexNames

        from .catalog import Catalog

        names = IndexNames(rag.index.prefix)
        docs = Catalog(make_client(rag.opensearch), names.documents, ttl_s=0).list_documents()
        if docs:
            add("opensearch", "ok", f"{rag.opensearch.url}: {len(docs)} manual(s): " + ", ".join(f"{d['doc_id']} ({d.get('embedding_model')})" for d in docs))
        else:
            add("opensearch", "fail", f"{rag.opensearch.url}: no documents in {names.documents}")
    except Exception as exc:  # noqa: BLE001
        add("opensearch", "fail", str(exc)[:300])

    # LLM
    if rag is not None:
        try:
            from rag_retrieval import ChatClient

            llm = ChatClient(rag.llm)
            try:
                probe = llm.probe()
            finally:
                llm.close()
            add("llm", "ok" if probe == "ok" else "fail", f"{rag.llm.base_url} model {rag.llm.model}: {probe}")
        except Exception as exc:  # noqa: BLE001
            add("llm", "fail", str(exc)[:300])
        # prompt budget vs context
        k = max(s.retrieval.k, s.retrieval.k_graph)
        need = k * 512 + 1500
        if need > rag.llm.context_limit_tokens:
            add("budget", "warn", f"k={k} x 512 + 1500 = {need} tokens > RAG__LLM__CONTEXT_LIMIT_TOKENS={rag.llm.context_limit_tokens}; lower CHAT__RETRIEVAL__K(_GRAPH) or the context budget")
        else:
            add("budget", "ok", f"k={k} -> up to ~{need} prompt tokens, context limit {rag.llm.context_limit_tokens}, retrieval budget {rag.retrieval.context_token_budget}")

    # users
    try:
        us = users_settings()
        if us.adapter == "env":
            ctx = get_adapter(us).current()
            lim = Policy().limits_for(ctx)
            add("users", "ok", f"adapter env -> {ctx.user_id} {list(ctx.groups)}: {lim.daily_messages}/day, {lim.max_turns_per_conversation} turns, manuals {lim.allowed_doc_ids or 'all'}")
        else:
            add("users", "ok", f"adapter header ({us.header_user}/{us.header_email}/{us.header_groups}); identity comes from the ingress")
        if s.ui.allow_user_switch and us.adapter == "header":
            add("users", "warn", "CHAT__UI__ALLOW_USER_SWITCH=true is ignored with the header adapter")
    except Unauthenticated as exc:
        add("users", "fail", str(exc))
    except Exception as exc:  # noqa: BLE001
        add("users", "fail", str(exc)[:300])

    ok = all(c["status"] != "fail" for c in checks)
    return {"ok": ok, "checks": checks, "settings": {"chat": s.model_dump(), "rag_llm_model": getattr(getattr(rag, "llm", None), "model", None)}}
