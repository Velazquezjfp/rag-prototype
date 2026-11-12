"""The work of one ingest call, without the HTTP framing: resolve the ontology, read what the target index holds,
compare it with what docling-graph-service produces, let the service process the document, index the result.

Nothing is written to disk. Every refusal is an :class:`IngestFailure` with the HTTP status the API returns.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml
from opensearch_index.identity import DocIdUnresolved
from opensearch_index.indexer import Indexer, IngestError, LeaseHeld, MappingMismatch, PlanError
from opensearch_index.mappings import IndexNames
from opensearch_index.ontology import Ontology, parse_ontology
from opensearch_index.schemas import ProcessResponse
from opensearch_index.settings import EmbeddingSettings
from opensearch_index.settings import Settings as OsiSettings
from opensearch_index.transform import VectorError
from opensearchpy.exceptions import AuthorizationException, NotFoundError, TransportError
from pydantic import ValidationError

log = logging.getLogger(__name__)

PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


class IngestFailure(Exception):
    """A refused or failed ingest; ``status`` is the HTTP status of the API answer."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ------------------------------------------------------------------------------------------------ ontology


@dataclass
class OntologyChoice:
    source: str  # the configured name ("bhb") or "upload"
    ontology: Ontology  # what the indexer needs: document ids, identifier patterns, identity rules
    graph: dict[str, Any]  # the document sent to docling-graph-service as ``ontology_graph``

    def info(self) -> dict[str, Any]:
        o = self.ontology
        return {"source": self.source, "name": o.name, "version": o.version, "fingerprint": o.fingerprint[:12]}


def resolve_ontology(named: dict[str, str], name: str | None, upload: bytes | None) -> OntologyChoice:
    """Exactly one of ``ontology=<name>`` (a configured ontology) and an uploaded YAML; neither is refused."""
    available = ", ".join(sorted(named)) or "none configured"
    if name and upload:
        raise IngestFailure(400, "pass either ontology=<name> or ontology_file, not both")
    if not name and not upload:
        raise IngestFailure(
            400,
            f"no ontology: pass ontology=<name> (available: {available}) or upload a YAML document as ontology_file",
        )
    if name:
        if name not in named:
            raise IngestFailure(400, f"unknown ontology {name!r} (available: {available})")
        path = Path(named[name])
        if not path.is_file():
            raise IngestFailure(500, f"ontology {name!r} is configured as {path}, but that file does not exist")
        raw, source = path.read_bytes(), name
    else:
        raw, source = upload or b"", "upload"
    try:
        graph = yaml.safe_load(raw)
        ontology = parse_ontology(raw, source=named[name] if name else "<upload>")
    except (yaml.YAMLError, ValueError, re.error) as exc:
        raise IngestFailure(400, f"ontology ({source}) is not usable: {str(exc)[:500]}") from exc
    if not isinstance(graph, dict) or not graph.get("classes"):
        raise IngestFailure(400, f"ontology ({source}) has no classes: is this an ontology YAML?")
    # YAML knows dates, JSON does not: the document travels to docling-graph-service as JSON
    graph = json.loads(json.dumps(graph, default=str))
    return OntologyChoice(source=source, ontology=ontology, graph=graph)


# --------------------------------------------------------------------------------------------- target index


def index_info(client: Any, prefix: str) -> dict[str, Any]:
    """What ``<prefix>-chunks`` holds: embedding model and vector size. An unknown prefix is refused - creating
    indices is a deliberate admin step (``osi bootstrap``), never a side effect of an ingest call."""
    if not PREFIX_RE.match(prefix):
        raise IngestFailure(400, f"invalid index prefix {prefix!r}: lower-case letters, digits and '-', 2-31 characters")
    names = IndexNames(prefix)
    hint = f"create the indices in OpenSearch first (osi bootstrap with OSI__INDEX__PREFIX={prefix}) and grant the writer role {prefix}-*"
    try:
        mappings = client.indices.get_mapping(index=names.chunks)
    except NotFoundError as exc:
        raise IngestFailure(404, f"unknown index prefix {prefix!r}: {names.chunks} does not exist - {hint}") from exc
    except AuthorizationException as exc:
        raise IngestFailure(404, f"index prefix {prefix!r} is not accessible for this service - {hint}") from exc
    except TransportError as exc:
        raise IngestFailure(502, f"OpenSearch is not usable: {type(exc).__name__}: {str(exc)[:300]}") from exc
    except Exception as exc:  # noqa: BLE001 - connection refused, TLS, DNS: all "OpenSearch is not reachable"
        raise IngestFailure(502, f"OpenSearch is not reachable: {type(exc).__name__}: {str(exc)[:300]}") from exc
    physical, body = next(iter(mappings.items()))
    m = body.get("mappings", {})
    meta = m.get("_meta", {})
    return {
        "prefix": prefix,
        "index": physical,
        "embedding_model": meta.get("embedding_model"),
        "embedding_dim": (m.get("properties", {}).get("embedding") or {}).get("dimension"),
        "mapping_version": meta.get("mapping_version"),
    }


# ------------------------------------------------------------------------------------ docling-graph-service


def dgs_capabilities(http: httpx.Client) -> dict[str, Any]:
    try:
        r = http.get("/v1/capabilities", timeout=60.0)
    except httpx.HTTPError as exc:
        raise IngestFailure(502, f"docling-graph-service is not reachable at {http.base_url}: {type(exc).__name__}: {exc}") from exc
    if r.status_code != 200:
        raise IngestFailure(502, f"docling-graph-service /v1/capabilities answered HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def dgs_embedding(caps: dict[str, Any]) -> dict[str, Any]:
    emb = (caps.get("models") or {}).get("embedding") or {}
    return {
        "model": emb.get("model"),
        "dim": emb.get("dim"),
        "text_prefix": emb.get("text_prefix") or "",
        "enabled": bool(emb.get("enabled", True)),
    }


def check_embedding(index: dict[str, Any], produced: dict[str, Any]) -> None:
    """One index holds vectors of exactly one model. Refuse before any work when the service produces another."""
    target = f"{index['prefix']}-chunks holds {index['embedding_model']} ({index['embedding_dim']} dimensions)"
    if not produced["enabled"]:
        raise IngestFailure(409, f"embeddings are switched off in docling-graph-service, but {target}; nothing was processed")
    same_model = index["embedding_model"] is None or produced["model"] == index["embedding_model"]
    if not same_model or produced["dim"] != index["embedding_dim"]:
        raise IngestFailure(
            409,
            f"embedding mismatch: {target}, docling-graph-service produces {produced['model']} "
            f"({produced['dim']} dimensions); nothing was processed",
        )


def _retry_after(value: str | None, default: float) -> float:
    try:
        return max(0.0, float(value)) if value is not None else default
    except ValueError:
        return default


def call_dgs(
    http: httpx.Client,
    *,
    name: str,
    content: bytes,
    ontology_graph: dict[str, Any],
    options: dict[str, Any],
    timeout_s: float,
    busy_retry_s: float,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], float]:
    """``POST /v1/process``. The service takes one document at a time: on 503 wait (Retry-After) and try again
    until ``timeout_s`` is used up. Returns the response and the seconds the call took."""
    body = {
        "document": {
            "name": name,
            "format": Path(name).suffix.lstrip(".").lower() or "pdf",
            "base64_content": base64.b64encode(content).decode(),
        },
        "pipeline_config": options,
        "ontology_graph": ontology_graph,
    }
    t0 = time.monotonic()
    end = t0 + timeout_s
    attempt = 0
    while True:
        attempt += 1
        try:
            r = http.post("/v1/process", json=body)
        except httpx.HTTPError as exc:
            raise IngestFailure(502, f"docling-graph-service call failed: {type(exc).__name__}: {exc}") from exc
        if r.status_code == 200:
            return r.json(), round(time.monotonic() - t0, 1)
        if r.status_code != 503:
            # 4xx: the document or the ontology is wrong - hand the service's answer on; 5xx: the service failed
            status = r.status_code if 400 <= r.status_code < 500 else 502
            raise IngestFailure(status, f"docling-graph-service HTTP {r.status_code}: {r.text[:1500]}")
        wait = _retry_after(r.headers.get("Retry-After"), busy_retry_s)
        if time.monotonic() + wait > end:
            raise IngestFailure(503, f"docling-graph-service stayed busy for {timeout_s:.0f} s ({attempt} attempts)")
        log.info("%s: docling-graph-service is busy (503), retrying in %.0f s (attempt %d)", name, wait, attempt)
        sleep(wait)


def summarize(resp: dict[str, Any], seconds: float) -> dict[str, Any]:
    chunks = resp.get("chunks") or []
    graph = resp.get("graph") or {}
    doc = resp.get("document") or {}
    return {
        "seconds": seconds,
        "cached": resp.get("cached"),
        "pages": doc.get("pages"),
        "tables": doc.get("tables"),
        "pictures": doc.get("pictures"),
        "chunks": len(chunks),
        "embedded": sum(c.get("embedding") is not None for c in chunks),
        "nodes": len(graph.get("nodes") or []),
        "edges": len(graph.get("edges") or []),
        "degraded": resp.get("degraded"),
        "errors": resp.get("errors") or [],
        "timings_s": resp.get("timings_s"),
        "versions": resp.get("versions"),
    }


# --------------------------------------------------------------------------------------------------- index


def index_response(
    client: Any,
    osi: OsiSettings,
    ontology: Ontology,
    resp_json: dict[str, Any],
    *,
    prefix: str,
    embedding: dict[str, Any],
    doc_id: str | None = None,
    force: bool = False,
    replace: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """opensearch-index: plan and ingest (same rules as ``osi ingest``): an unchanged book is a noop, a new
    extraction replaces that book's records. Returns the indexer report as a dict."""
    settings = osi.model_copy(
        update={
            "index": osi.index.model_copy(update={"prefix": prefix}),
            "embedding": EmbeddingSettings(
                model=embedding["model"], dim=embedding["dim"], text_prefix=embedding.get("text_prefix") or ""
            ),
        }
    )
    try:
        resp = ProcessResponse.model_validate(resp_json)
    except ValidationError as exc:
        raise IngestFailure(502, f"docling-graph-service answered in an unexpected shape: {str(exc)[:500]}") from exc
    indexer = Indexer(client, settings, ontology)
    try:
        plan = indexer.plan(resp, doc_id_override=doc_id, force=force, replace=replace)
        report = indexer.ingest(plan, resp, dry_run=dry_run, force=force)
    except DocIdUnresolved as exc:
        raise IngestFailure(422, f"{exc} - pass doc_id=<document id> in the call") from exc
    except VectorError as exc:
        raise IngestFailure(422, f"the processed document cannot be indexed: {exc}") from exc
    except (PlanError, LeaseHeld, MappingMismatch) as exc:
        raise IngestFailure(409, str(exc)) from exc
    except IngestError as exc:
        raise IngestFailure(500, f"indexing failed: {exc}") from exc
    except TransportError as exc:
        raise IngestFailure(502, f"OpenSearch failed while indexing: {type(exc).__name__}: {str(exc)[:500]}") from exc
    return {**asdict(report), "warnings": list(plan.warnings)}
