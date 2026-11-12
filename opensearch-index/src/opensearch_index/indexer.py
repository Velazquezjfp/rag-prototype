"""The ingest protocol: plan -> lease -> bulk -> verify -> sweep -> finalize. Deterministic ids make every step
idempotent; the manifest document (``_id = doc_id``) is both the record and the lock.

Chunk and node ids are logical, so a new run overwrites records in place and a stale sweep removes what the new run
did not write. Readers never filter by ``run_id``: after a failed run the index holds a superset, never a hole, and
the next successful run heals it.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from opensearchpy import ConflictError, NotFoundError, OpenSearch, helpers

from . import __version__
from .client import cluster_info
from .identity import resolve_doc_id, run_fingerprint
from .mappings import MAPPING_VERSION, IndexNames, index_bodies, rrf_pipeline_body, sweep_query
from .ontology import Ontology
from .schemas import ProcessResponse
from .settings import Settings
from .transform import IndexBatch, build_batch, bulk_actions, compute_edge_ids

log = logging.getLogger(__name__)

Action = Literal["noop", "ingest", "replace"]


class IngestError(RuntimeError):
    pass


class LeaseHeld(IngestError):
    pass


class MappingMismatch(IngestError):
    pass


class PlanError(IngestError):
    pass


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass
class IngestPlan:
    action: Action
    doc_id: str
    doc_id_source: str
    doc_name: str
    doc_sha256: str
    run_id: str
    counts: dict[str, int]
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    previous: dict[str, Any] | None = None  # current manifest source, if any
    seq_no: int | None = None
    primary_term: int | None = None

    def summary(self) -> dict[str, Any]:
        d = asdict(self)
        prev = d.pop("previous")
        d["previous"] = (
            {k: prev.get(k) for k in ("status", "run_id", "doc_sha256", "doc_name", "finished_at")} if prev else None
        )
        d.pop("seq_no")
        d.pop("primary_term")
        return d


@dataclass
class IngestReport:
    status: str  # noop | dry-run | active | failed
    plan: dict[str, Any]
    counts: dict[str, int] = field(default_factory=dict)
    swept: dict[str, int] = field(default_factory=dict)
    duration_s: float = 0.0
    error: str | None = None
    sweep_query: dict[str, Any] | None = None


@dataclass
class _Lease:
    seq_no: int
    primary_term: int
    body: dict[str, Any]


class Indexer:
    def __init__(self, client: OpenSearch, settings: Settings, ontology: Ontology, *, owner: str | None = None):
        self.client = client
        self.settings = settings
        self.ontology = ontology
        self.names = IndexNames(settings.index.prefix)
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}"

    # ------------------------------------------------------------------ indices

    def bootstrap(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Create missing indices (physical ``-vN`` + alias) and the RRF search pipeline; verify existing ones."""
        report: dict[str, Any] = {"created": [], "existing": [], "pipeline": None, "dry_run": dry_run}
        bodies = index_bodies(self.names, self.settings.embedding, self.settings.index)
        for alias, body in bodies.items():
            physical = self.names.physical(alias)
            if self.client.indices.exists(index=physical):
                report["existing"].append(physical)
                if not self.client.indices.exists_alias(name=alias) and not dry_run:
                    self.client.indices.put_alias(index=physical, name=alias)
                continue
            report["created"].append(physical)
            if not dry_run:
                self.client.indices.create(index=physical, body=body)
        if not dry_run:
            self.check_indices()
        if self.settings.index.rrf_pipeline:
            info = cluster_info(self.client)
            if info.supports_rrf:
                if not dry_run:
                    self.client.transport.perform_request(
                        "PUT",
                        f"/_search/pipeline/{self.names.rrf_pipeline}",
                        body=rrf_pipeline_body(self.settings.index.rrf_rank_constant),
                    )
                report["pipeline"] = self.names.rrf_pipeline
            else:
                report["pipeline"] = f"skipped (server {info.version} < 2.19)"
        return report

    def check_indices(self) -> None:
        """Refuse to write into indices of another mapping version or vector dimension."""
        for alias in self.names.aliases:
            try:
                mappings = self.client.indices.get_mapping(index=alias)
            except NotFoundError as exc:
                raise MappingMismatch(f"index alias {alias} does not exist - run `osi bootstrap`") from exc
            for physical, m in mappings.items():
                meta = m.get("mappings", {}).get("_meta", {})
                version = meta.get("mapping_version")
                if version != MAPPING_VERSION:
                    raise MappingMismatch(
                        f"{physical}: mapping_version {version} != {MAPPING_VERSION} (this tool) - migrate first"
                    )
                if alias == self.names.chunks:
                    dim = m["mappings"]["properties"]["embedding"].get("dimension")
                    if dim != self.settings.embedding.dim:
                        raise MappingMismatch(
                            f"{physical}: knn dimension {dim} != OSI__EMBEDDING__DIM {self.settings.embedding.dim}"
                        )

    # ------------------------------------------------------------------ plan

    def plan(
        self,
        resp: ProcessResponse,
        *,
        doc_id_override: str | None = None,
        force: bool = False,
        replace: bool = False,
    ) -> IngestPlan:
        res = resolve_doc_id(resp, self.ontology, doc_id_override)
        edge_ids = compute_edge_ids(resp.graph)
        run_id = run_fingerprint(
            resp,
            edge_ids,
            ontology_fingerprint=self.ontology.fingerprint,
            embedding_model=self.settings.embedding.model,
            embedding_dim=self.settings.embedding.dim,
            mapping_version=MAPPING_VERSION,
        )
        sha = resp.document.sha256
        counts = {
            "chunks": len(resp.chunks),
            "nodes": len(resp.graph.nodes) if resp.graph else 0,
            "edges": len(edge_ids),
            "documents": 1,
        }
        manifest, seq_no, primary_term = self._get_manifest(res.doc_id)
        plan = IngestPlan(
            action="ingest",
            doc_id=res.doc_id,
            doc_id_source=res.source,
            doc_name=resp.document.name,
            doc_sha256=sha,
            run_id=run_id,
            counts=counts,
            warnings=list(res.warnings),
            previous=manifest,
            seq_no=seq_no,
            primary_term=primary_term,
        )
        other = self._manifest_by_sha(sha, exclude_doc_id=res.doc_id)
        if other is not None:
            msg = f"content sha256 {sha[:12]} is already indexed as doc_id {other['doc_id']} ({other.get('doc_name')})"
            if not force:
                raise PlanError(msg + " - check the document id; --force overrides")
            plan.warnings.append(msg + " (forced)")
        if manifest is None:
            plan.reasons.append("no manifest for this doc_id")
        elif manifest.get("status") == "active" and manifest.get("run_id") == run_id and not force:
            plan.action = "noop"
            plan.reasons.append(f"already indexed (run {run_id[:12]}, {manifest.get('finished_at')})")
        elif manifest.get("doc_sha256") != sha:
            plan.action = "replace"
            plan.reasons.append(
                f"content version changes: {str(manifest.get('doc_sha256'))[:12]} ({manifest.get('doc_name')}) -> "
                f"{sha[:12]} ({resp.document.name})"
            )
            if manifest.get("doc_name") != resp.document.name and not replace:
                raise PlanError(
                    f"doc_id {res.doc_id} currently holds {manifest.get('doc_name')!r}; the new file is "
                    f"{resp.document.name!r} - pass --replace if this is the same manual"
                )
        else:
            if manifest.get("status") != "active":
                plan.reasons.append(f"previous ingest {manifest.get('status')} (run {str(manifest.get('run_id'))[:12]})")
            if manifest.get("run_id") != run_id:
                plan.reasons.append(f"new extraction: run {str(manifest.get('run_id'))[:12]} -> {run_id[:12]}")
            if force:
                plan.reasons.append("forced")
        return plan

    # ------------------------------------------------------------------ ingest

    def ingest(self, plan: IngestPlan, resp: ProcessResponse, *, dry_run: bool = False, force: bool = False) -> IngestReport:
        t0 = time.time()
        if plan.action == "noop":
            return IngestReport(status="noop", plan=plan.summary(), counts=plan.counts, duration_s=round(time.time() - t0, 3))
        batch = self._build(plan, resp)
        if dry_run:
            return IngestReport(
                status="dry-run",
                plan=plan.summary(),
                counts=batch.counts,
                sweep_query=sweep_query(plan.doc_id, plan.run_id),
                duration_s=round(time.time() - t0, 3),
            )
        self.check_indices()
        lease = self._acquire_lease(plan, batch, force=force)
        try:
            self._bulk(batch)
            self._refresh()
            self._verify_counts(batch)
            swept = self._sweep(batch.doc_id, batch.run_id)
            self._finalize(lease, batch, swept)
        except Exception as exc:
            self._fail(lease, str(exc))
            raise
        return IngestReport(
            status="active",
            plan=plan.summary(),
            counts=batch.counts,
            swept=swept,
            duration_s=round(time.time() - t0, 3),
        )

    def _build(self, plan: IngestPlan, resp: ProcessResponse) -> IndexBatch:
        emb = self.settings.embedding
        return build_batch(
            resp,
            doc_id=plan.doc_id,
            doc_id_source=plan.doc_id_source,
            run_id=plan.run_id,
            ontology=self.ontology,
            embedding_model=emb.model,
            embedding_dim=emb.dim,
            embedding_text_prefix=emb.text_prefix,
            indexed_at=utcnow_iso(),
        )

    def _acquire_lease(self, plan: IngestPlan, batch: IndexBatch, *, force: bool) -> _Lease:
        prev = plan.previous
        now = utcnow_iso()
        if prev and prev.get("status") == "indexing" and not force:
            started = _parse_iso(prev.get("started_at"))
            age = (datetime.now(UTC) - started).total_seconds() if started else None
            if age is not None and age < self.settings.ingest.lock_ttl_s:
                raise LeaseHeld(
                    f"an ingest of {plan.doc_id} is in progress since {prev.get('started_at')} by {prev.get('owner')} "
                    f"({int(age)} s ago; lock_ttl_s={self.settings.ingest.lock_ttl_s}); --force takes it over"
                )
        previous_run = prev.get("run_id") if prev and prev.get("status") == "active" else (prev or {}).get("previous_run_id")
        body = {
            "doc_id": plan.doc_id,
            "status": "indexing",
            "run_id": plan.run_id,
            "previous_run_id": previous_run,
            "doc_sha256": plan.doc_sha256,
            "doc_name": plan.doc_name,
            "doc_id_source": plan.doc_id_source,
            "owner": self.owner,
            "started_at": now,
            "finished_at": None,
            "counts": batch.counts,
            "swept": None,
            "embedding_model": self.settings.embedding.model,
            "mapping_version": MAPPING_VERSION,
            "indexer_version": __version__,
            "error": None,
            "history": (prev or {}).get("history") or [],
        }
        try:
            if prev is None:
                r = self.client.index(index=self.names.manifest, id=plan.doc_id, body=body, op_type="create", refresh=True)
            else:
                r = self.client.index(
                    index=self.names.manifest,
                    id=plan.doc_id,
                    body=body,
                    if_seq_no=plan.seq_no,
                    if_primary_term=plan.primary_term,
                    refresh=True,
                )
        except ConflictError as exc:
            raise LeaseHeld(f"manifest of {plan.doc_id} changed underneath us (concurrent ingest?) - re-run") from exc
        return _Lease(seq_no=r["_seq_no"], primary_term=r["_primary_term"], body=body)

    def _bulk(self, batch: IndexBatch) -> None:
        ok, errors = helpers.bulk(
            self.client,
            bulk_actions(batch, self.names),
            chunk_size=self.settings.ingest.bulk_size,
            raise_on_error=False,
            raise_on_exception=True,
            max_retries=3,
            initial_backoff=2,
            request_timeout=self.settings.ingest.request_timeout_s,
        )
        if errors:
            first = errors[0]
            raise IngestError(f"bulk: {len(errors)} item(s) failed, {ok} ok; first: {_short(first)}")
        log.info("bulk indexed %d documents for %s", ok, batch.doc_id)

    def _refresh(self) -> None:
        self.client.indices.refresh(index=",".join([self.names.chunks, self.names.nodes, self.names.documents]))

    def _count(self, index: str, doc_id: str, run_id: str | None = None) -> int:
        filters: list[dict[str, Any]] = [{"term": {"doc_id": doc_id}}]
        if run_id:
            filters.append({"term": {"run_id": run_id}})
        return int(self.client.count(index=index, body={"query": {"bool": {"filter": filters}}})["count"])

    def _verify_counts(self, batch: IndexBatch) -> None:
        got = {
            "chunks": self._count(self.names.chunks, batch.doc_id, batch.run_id),
            "nodes": self._count(self.names.nodes, batch.doc_id, batch.run_id),
        }
        expected = {"chunks": len(batch.chunks), "nodes": len(batch.nodes)}
        if got != expected:
            raise IngestError(f"count verification failed after bulk: expected {expected}, found {got}")
        doc = self.client.get(index=self.names.documents, id=batch.doc_id)["_source"]
        if doc.get("run_id") != batch.run_id:
            raise IngestError(f"document record of {batch.doc_id} carries run {doc.get('run_id')}, expected {batch.run_id}")

    def _sweep(self, doc_id: str, run_id: str) -> dict[str, int]:
        swept: dict[str, int] = {}
        for key, index in (("chunks", self.names.chunks), ("nodes", self.names.nodes)):
            r = self.client.delete_by_query(index=index, body=sweep_query(doc_id, run_id), conflicts="proceed", refresh=True)
            if r.get("failures"):
                raise IngestError(f"stale sweep on {index} reported failures: {_short(r['failures'][0])}")
            swept[key] = int(r.get("deleted", 0))
        swept["documents"] = 0
        swept["edges"] = 0
        return swept

    def _finalize(self, lease: _Lease, batch: IndexBatch, swept: dict[str, int]) -> None:
        body = dict(lease.body)
        prev = body.get("history") or []
        entry = None
        if body.get("previous_run_id") and body["previous_run_id"] != batch.run_id:
            entry = {"run_id": body["previous_run_id"], "replaced_at": utcnow_iso()}
        body.update(
            status="active",
            finished_at=utcnow_iso(),
            counts=batch.counts,
            swept=swept,
            error=None,
            history=([entry] if entry else []) + prev[: self.settings.ingest.history_keep],
        )
        self._write_manifest(lease, body)

    def _fail(self, lease: _Lease, error: str) -> None:
        body = dict(lease.body)
        body.update(status="failed", finished_at=utcnow_iso(), error=error[:2000])
        try:
            self._write_manifest(lease, body)
        except Exception as exc:  # best effort: the original error is what the caller needs
            log.warning("could not record the failure in the manifest: %s", exc)

    def _write_manifest(self, lease: _Lease, body: dict[str, Any]) -> None:
        try:
            self.client.index(
                index=self.names.manifest,
                id=body["doc_id"],
                body=body,
                if_seq_no=lease.seq_no,
                if_primary_term=lease.primary_term,
                refresh=True,
            )
        except ConflictError as exc:
            raise IngestError(f"manifest of {body['doc_id']} was modified during the ingest (concurrent run?)") from exc

    # ------------------------------------------------------------------ manifest lookups

    def _get_manifest(self, doc_id: str) -> tuple[dict[str, Any] | None, int | None, int | None]:
        try:
            r = self.client.get(index=self.names.manifest, id=doc_id)
        except NotFoundError:
            return None, None, None
        return r["_source"], r.get("_seq_no"), r.get("_primary_term")

    def _manifest_by_sha(self, sha: str, *, exclude_doc_id: str) -> dict[str, Any] | None:
        try:
            r = self.client.search(
                index=self.names.manifest,
                body={"size": 5, "query": {"term": {"doc_sha256": sha}}},
            )
        except NotFoundError:
            return None
        for hit in r["hits"]["hits"]:
            if hit["_source"].get("doc_id") != exclude_doc_id:
                return hit["_source"]
        return None

    # ------------------------------------------------------------------ delete / status

    def delete_document(self, doc_id: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for key, index in (("chunks", self.names.chunks), ("nodes", self.names.nodes)):
            r = self.client.delete_by_query(
                index=index, body={"query": {"term": {"doc_id": doc_id}}}, conflicts="proceed", refresh=True
            )
            out[key] = int(r.get("deleted", 0))
        for key, index in (("documents", self.names.documents), ("manifest", self.names.manifest)):
            try:
                self.client.delete(index=index, id=doc_id, refresh=True)
                out[key] = 1
            except NotFoundError:
                out[key] = 0
        return out

    def status(self) -> dict[str, Any]:
        info = cluster_info(self.client)
        out: dict[str, Any] = {
            "cluster": {"name": info.cluster_name, "version": info.version, "knn": info.has_knn},
            "indices": {},
            "documents": [],
            "attention": [],
            "cross_document_node_ids": None,
        }
        for alias in self.names.aliases:
            try:
                out["indices"][alias] = int(self.client.count(index=alias)["count"])
            except NotFoundError:
                out["indices"][alias] = None
        if out["indices"].get(self.names.manifest) is None:
            out["attention"].append("indices missing - run `osi bootstrap`")
            return out
        manifests = self.client.search(
            index=self.names.manifest, body={"size": 500, "sort": [{"doc_id": "asc"}], "query": {"match_all": {}}}
        )["hits"]["hits"]
        per_doc = {"chunks": self._by_doc(self.names.chunks), "nodes": self._by_doc(self.names.nodes)}
        for h in manifests:
            m = h["_source"]
            row = {
                "doc_id": m["doc_id"],
                "status": m.get("status"),
                "doc_name": m.get("doc_name"),
                "doc_sha256": str(m.get("doc_sha256"))[:12],
                "run_id": str(m.get("run_id"))[:12],
                "finished_at": m.get("finished_at"),
                "indexed": {k: per_doc[k].get(m["doc_id"], 0) for k in per_doc},
                "counts": m.get("counts"),
                "history": len(m.get("history") or []),
            }
            out["documents"].append(row)
            if m.get("status") == "failed":
                out["attention"].append(f"{m['doc_id']}: last ingest failed: {m.get('error')}")
            elif m.get("status") == "indexing":
                out["attention"].append(f"{m['doc_id']}: ingest in progress since {m.get('started_at')} by {m.get('owner')}")
        for doc_id, n in per_doc["chunks"].items():
            if doc_id not in {r["doc_id"] for r in out["documents"]}:
                out["attention"].append(f"{doc_id}: {n} chunks without a manifest (interrupted first ingest?)")
        agg = self.client.search(
            index=self.names.nodes,
            body={
                "size": 0,
                "aggs": {"shared": {"terms": {"field": "node_id", "min_doc_count": 2, "size": 10000}}},
            },
        )["aggregations"]["shared"]["buckets"]
        out["cross_document_node_ids"] = {"count": len(agg), "sample": [b["key"] for b in agg[:10]]}
        return out

    def _by_doc(self, index: str) -> dict[str, int]:
        r = self.client.search(
            index=index, body={"size": 0, "aggs": {"by_doc": {"terms": {"field": "doc_id", "size": 1000}}}}
        )
        return {b["key"]: b["doc_count"] for b in r["aggregations"]["by_doc"]["buckets"]}


def _short(obj: Any, n: int = 400) -> str:
    s = str(obj)
    return s if len(s) <= n else s[:n] + "…"
