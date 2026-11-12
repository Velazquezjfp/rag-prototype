"""FastAPI front of the ingest service.

    GET  /healthz            no key; liveness
    GET  /v1/info            defaults, target index, what docling-graph-service produces
    POST /v1/ingest          multipart: pdf + (ontology=<name> | ontology_file=<YAML>) [+ prefix, doc_id, ocr, vlm, ...]
    GET  /v1/jobs[/{id}]     the last jobs (in memory): a call that lost its connection still shows its result here

One document at a time (docling-graph-service works that way too); a second call gets 503 + Retry-After. The
endpoint is synchronous on purpose: the job runs to its end even when the caller's connection is cut.
Start: ``uvicorn --factory ingest_service.api:create_app --host 0.0.0.0 --port 8090``
"""

from __future__ import annotations

import hmac
import logging
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Security, UploadFile
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from opensearch_index.client import make_client
from opensearch_index.settings import Settings as OsiSettings

from . import __version__, core
from .settings import Settings, get_settings

log = logging.getLogger("ingest_service")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Jobs:
    """The last ``keep`` jobs, newest last. In memory only: a restart forgets them (nothing is persisted)."""

    def __init__(self, keep: int) -> None:
        self._keep = max(1, keep)
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def start(self, **fields: Any) -> dict[str, Any]:
        job = {"job_id": uuid.uuid4().hex[:12], "state": "running", "status": None, "started_at": _now(),
               "finished_at": None, "doc_id": None, "error": None, **fields}
        with self._lock:
            self._jobs[job["job_id"]] = job
            while len(self._jobs) > self._keep:
                self._jobs.popitem(last=False)
        return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._jobs.values()))


def create_app(
    settings: Settings | None = None,
    *,
    osi_settings: OsiSettings | None = None,
    os_client: Any | None = None,
    dgs_transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> FastAPI:
    settings = settings or get_settings()
    if not settings.api_key.strip():
        raise RuntimeError("INGEST__API_KEY is not set: the ingest API does not start without an API key")
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("opensearch").setLevel(logging.ERROR)  # a 404 on the manifest of a new book is normal
    logging.getLogger("httpx").setLevel(logging.WARNING)
    osi = osi_settings or OsiSettings()
    # trust_env=False: a proxy must never sit between this service and docling-graph-service (long requests)
    http = httpx.Client(base_url=settings.dgs.url.rstrip("/"), timeout=httpx.Timeout(settings.dgs.timeout_s, connect=10.0),
                        trust_env=False, transport=dgs_transport)
    jobs = Jobs(settings.jobs_keep)
    busy = threading.Lock()
    state: dict[str, Any] = {"os": os_client}

    def opensearch() -> Any:
        if state["os"] is None:
            state["os"] = make_client(osi.opensearch)
        return state["os"]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("ingest-service %s: dgs=%s opensearch=%s default prefix=%s ontologies=%s", __version__,
                 settings.dgs.url, osi.opensearch.url, settings.default_prefix, sorted(settings.ontologies))
        yield
        http.close()

    app = FastAPI(title="ingest-service", version=__version__, lifespan=lifespan,
                  description="PDF + ontology in; docling-graph-service processes it; the result is indexed into OpenSearch.")

    key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
    bearer = HTTPBearer(auto_error=False)

    def require_key(
        api_key: str | None = Security(key_header),
        token: HTTPAuthorizationCredentials | None = Security(bearer),
    ) -> None:
        supplied = api_key or (token.credentials if token else None)
        if not supplied or not hmac.compare_digest(supplied.encode(), settings.api_key.encode()):
            raise HTTPException(401, "missing or wrong API key (header X-API-Key, or Authorization: Bearer <key>)")

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "busy": busy.locked()}

    @app.get("/v1/info", dependencies=[Depends(require_key)])
    def info() -> dict[str, Any]:
        """The defaults of a call and what the two backends currently say - look here before the first ingest."""
        out: dict[str, Any] = {
            "service": "ingest-service",
            "version": __version__,
            "defaults": {
                "prefix": settings.default_prefix,
                "ontologies": {n: {"path": p, "available": Path(p).is_file()} for n, p in settings.ontologies.items()},
                "max_upload_mb": settings.max_upload_mb,
            },
            "opensearch": {"url": osi.opensearch.url, "user": osi.opensearch.username},
            "dgs": {"url": settings.dgs.url},
        }
        try:
            out["opensearch"]["index"] = core.index_info(opensearch(), settings.default_prefix)
        except core.IngestFailure as exc:
            out["opensearch"]["error"] = exc.message
        try:
            caps = core.dgs_capabilities(http)
            out["dgs"].update(
                embedding=core.dgs_embedding(caps),
                models={k: {"model": v.get("model"), "enabled": v.get("enabled")} for k, v in (caps.get("models") or {}).items()},
                features=caps.get("features"),
                limits=caps.get("limits"),
            )
        except core.IngestFailure as exc:
            out["dgs"]["error"] = exc.message
        return out

    @app.get("/v1/jobs", dependencies=[Depends(require_key)])
    def list_jobs() -> list[dict[str, Any]]:
        return jobs.list()

    @app.get("/v1/jobs/{job_id}", dependencies=[Depends(require_key)])
    def get_job(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"unknown job {job_id!r} (jobs are kept in memory; a restart forgets them)")
        return job

    @app.post("/v1/ingest", dependencies=[Depends(require_key)])
    def ingest(
        pdf: UploadFile = File(..., description="the document (PDF)"),
        ontology: str | None = Form(None, description="name of a configured ontology, e.g. bhb"),
        ontology_file: UploadFile | None = File(None, description="or: an ontology YAML for this call"),
        prefix: str | None = Form(None, description="index prefix; default from the service (bhb). The indices must exist."),
        doc_id: str | None = Form(None, description="document id, when the ontology and page 1 do not give one"),
        ocr: bool | None = Form(None, description="OCR on/off for this document; default: the service's setting"),
        vlm: bool | None = Form(None, description="picture descriptions on/off; default: the service's setting"),
        force: bool = Form(False, description="index again although this exact result is already active"),
        replace: bool = Form(False, description="allow another file name under the same document id"),
        dry_run: bool = Form(False, description="process and plan, write nothing to OpenSearch"),
    ) -> JSONResponse:
        name = Path(pdf.filename or "document.pdf").name
        content = pdf.file.read()
        if not content:
            raise HTTPException(400, "the uploaded document is empty")
        if len(content) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"document larger than {settings.max_upload_mb} MB")
        upload = ontology_file.file.read() if ontology_file is not None else None
        try:
            choice = core.resolve_ontology(settings.ontologies, (ontology or "").strip() or None, upload or None)
        except core.IngestFailure as exc:
            raise HTTPException(exc.status, exc.message) from exc
        target = (prefix or settings.default_prefix).strip()
        options = {k: v for k, v in (("ocr_enabled", ocr), ("vlm_enabled", vlm)) if v is not None}

        if not busy.acquire(blocking=False):
            raise HTTPException(503, "another document is being ingested; retry later", headers={"Retry-After": "30"})
        job = jobs.start(file=name, size_mb=round(len(content) / 1e6, 2), parameters=None, dgs=None, index=None)
        status = 200
        try:
            idx = core.index_info(opensearch(), target)
            produced = core.dgs_embedding(core.dgs_capabilities(http))
            core.check_embedding(idx, produced)
            job["parameters"] = {
                "prefix": target,
                "index": idx["index"],
                "embedding": {k: produced[k] for k in ("model", "dim", "text_prefix")},
                "ontology": choice.info(),
                "pipeline_config": options or "service defaults",
                "doc_id": doc_id,
                "force": force,
                "replace": replace,
                "dry_run": dry_run,
            }
            log.info("job %s accepted: %s (%.2f MB) parameters=%s", job["job_id"], name, job["size_mb"], job["parameters"])
            resp, seconds = core.call_dgs(http, name=name, content=content, ontology_graph=choice.graph, options=options,
                                          timeout_s=settings.dgs.timeout_s, busy_retry_s=settings.dgs.busy_retry_s, sleep=sleep)
            job["dgs"] = core.summarize(resp, seconds)
            log.info("job %s processed in %.0f s: %s", job["job_id"], seconds, {k: job["dgs"][k] for k in ("pages", "chunks", "embedded", "nodes", "edges", "degraded")})
            report = core.index_response(opensearch(), osi, choice.ontology, resp, prefix=target, embedding=produced,
                                         doc_id=(doc_id or "").strip() or None, force=force, replace=replace, dry_run=dry_run)
            job.update(state="done", status=report["status"], doc_id=report["plan"]["doc_id"], index=report)
            log.info("job %s %s: doc_id=%s counts=%s", job["job_id"], report["status"], job["doc_id"], report.get("counts"))
        except core.IngestFailure as exc:
            status = exc.status
            job.update(state="failed", error=exc.message)
            log.warning("job %s failed (%d): %s", job["job_id"], exc.status, exc.message)
        except Exception as exc:  # noqa: BLE001 - never lose a job to an unexpected error: record it, answer 500
            status = 500
            job.update(state="failed", error=f"{type(exc).__name__}: {str(exc)[:1000]}")
            log.exception("job %s failed unexpectedly", job["job_id"])
        finally:
            job["finished_at"] = _now()
            busy.release()
        return JSONResponse(job, status_code=status)

    return app
