"""The ingest protocol against the in-memory fake: noop, replace, force, guards, lease, failure, dry-run."""

import copy
from datetime import UTC, datetime, timedelta

import pytest
from fake_client import FakeClient, fake_bulk

from opensearch_index import indexer as ix_mod
from opensearch_index.indexer import Indexer, IngestError, LeaseHeld, MappingMismatch, PlanError
from opensearch_index.mappings import MAPPING_VERSION, manifest_mapping
from opensearch_index.settings import Settings


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(ix_mod.helpers, "bulk", fake_bulk)
    return client


@pytest.fixture
def ix(fake, settings, ontology):
    indexer = Indexer(fake, settings, ontology, owner="test:1")
    indexer.bootstrap()
    return indexer


def run(ix, resp, *, dry_run=False, force=False, replace=False, doc_id=None):
    plan = ix.plan(resp, doc_id_override=doc_id, force=force, replace=replace)
    return plan, ix.ingest(plan, resp, dry_run=dry_run, force=force)


def counts(fake, names, doc_id="BHB-PLT-0007"):
    return {
        "chunks": sum(1 for d in fake.all_docs(names.chunks) if d["doc_id"] == doc_id),
        "nodes": sum(1 for d in fake.all_docs(names.nodes) if d["doc_id"] == doc_id),
        "documents": sum(1 for d in fake.all_docs(names.documents) if d["doc_id"] == doc_id),
    }


def manifest(fake, ix, doc_id="BHB-PLT-0007"):
    return fake.get(ix.names.manifest, doc_id)["_source"]


def mutated(resp):
    """A different extraction of the same PDF: one chunk fewer, one isolated node fewer, one label changed."""
    other = copy.deepcopy(resp)
    other.chunks.pop()
    referenced = {e.source for e in other.graph.edges} | {e.target for e in other.graph.edges}
    isolated = next(n for n in other.graph.nodes if n.id not in referenced)
    other.graph.nodes.remove(isolated)
    other.graph.nodes[0].label += " (neu)"
    return other


# ---------------------------------------------------------------- bootstrap


def test_bootstrap_idempotent(fake, ix):
    assert sorted(fake.aliases) == ["bhbtest-chunks", "bhbtest-documents", "bhbtest-manifest", "bhbtest-nodes"]
    assert fake.aliases["bhbtest-chunks"] == f"bhbtest-chunks-v{MAPPING_VERSION}"
    assert "bhbtest-rrf" in fake.pipelines
    again = ix.bootstrap()
    assert again["created"] == [] and len(again["existing"]) == 4
    ix.check_indices()


def test_bootstrap_skips_rrf_on_old_server(monkeypatch, settings, ontology):
    client = FakeClient(version="2.17.1")
    monkeypatch.setattr(ix_mod.helpers, "bulk", fake_bulk)
    report = Indexer(client, settings, ontology).bootstrap()
    assert report["pipeline"].startswith("skipped")


def test_dimension_mismatch_refused(fake, ix, ontology):
    other = Settings(_env_file=None, index={"prefix": "bhbtest"}, embedding={"dim": 16}, ontology={"path": str(ontology.path)})
    with pytest.raises(MappingMismatch, match="dimension 8 != OSI__EMBEDDING__DIM 16"):
        Indexer(fake, other, ontology).check_indices()


def test_missing_indices_refused(fake, settings, ontology, monkeypatch):
    monkeypatch.setattr(ix_mod.helpers, "bulk", fake_bulk)
    with pytest.raises(MappingMismatch, match="bootstrap"):
        Indexer(fake, settings, ontology).check_indices()


# ---------------------------------------------------------------- first ingest, noop


def test_first_ingest(fake, ix, response_small):
    plan, report = run(ix, response_small)
    assert plan.action == "ingest" and plan.doc_id == "BHB-PLT-0007" and plan.doc_id_source == "ontology_file"
    assert report.status == "active"
    assert report.counts == {"chunks": 12, "nodes": 59, "edges": 11, "documents": 1}
    assert report.swept == {"chunks": 0, "nodes": 0, "documents": 0, "edges": 0}
    assert counts(fake, ix.names) == {"chunks": 12, "nodes": 59, "documents": 1}
    m = manifest(fake, ix)
    assert m["status"] == "active" and m["run_id"] == plan.run_id and m["previous_run_id"] is None
    assert m["counts"] == report.counts and m["history"] == []
    assert set(m) <= set(manifest_mapping()["properties"]), set(m) - set(manifest_mapping()["properties"])


def test_rerun_same_output_is_noop(fake, ix, response_small):
    run(ix, response_small)
    writes = len(fake.index_calls)
    plan, report = run(ix, response_small)
    assert plan.action == "noop" and report.status == "noop"
    assert any("already indexed" in r for r in plan.reasons)
    assert len(fake.index_calls) == writes


def test_new_extraction_replaces_and_sweeps(fake, ix, response_small):
    first, _ = run(ix, response_small)
    plan, report = run(ix, mutated(response_small))
    assert plan.action == "ingest" and any("new extraction" in r for r in plan.reasons)
    assert report.status == "active"
    assert report.swept["chunks"] == 1 and report.swept["nodes"] == 1
    assert counts(fake, ix.names) == {"chunks": 11, "nodes": 58, "documents": 1}
    assert all(d["run_id"] == plan.run_id for d in fake.all_docs(ix.names.chunks))
    m = manifest(fake, ix)
    assert m["previous_run_id"] == first.run_id
    assert [h["run_id"] for h in m["history"]] == [first.run_id]


def test_force_reindexes(fake, ix, response_small):
    run(ix, response_small)
    plan, report = run(ix, response_small, force=True)
    assert plan.action == "ingest" and "forced" in plan.reasons
    assert report.status == "active" and counts(fake, ix.names)["chunks"] == 12


def test_graph_none(fake, ix, response_small):
    response_small.graph = None
    plan, report = run(ix, response_small)
    assert report.status == "active" and report.counts["nodes"] == 0
    assert fake.get(ix.names.documents, "BHB-PLT-0007")["_source"]["graph"] is None


# ---------------------------------------------------------------- guards


def new_version(resp, name):
    other = copy.deepcopy(resp)
    other.document.name = name
    other.document.sha256 = "ff" * 32
    for c in other.chunks:
        c.chunk_id = "ffffffffffff" + c.chunk_id[12:]
    if other.graph:
        for n in other.graph.nodes:
            n.provenance.chunk_ids = ["ffffffffffff" + cid[12:] for cid in n.provenance.chunk_ids]
        for e in other.graph.edges:
            e.provenance.chunk_ids = ["ffffffffffff" + cid[12:] for cid in e.provenance.chunk_ids]
    return other


def test_new_pdf_version_same_name_replaces(fake, ix, response_small):
    run(ix, response_small)
    plan, report = run(ix, new_version(response_small, response_small.document.name))
    assert plan.action == "replace"
    assert report.swept["chunks"] == 12 and report.swept["nodes"] == 59  # every old-prefix record gone
    assert counts(fake, ix.names) == {"chunks": 12, "nodes": 59, "documents": 1}
    assert all(c["chunk_id"].startswith("ffffffffffff") for c in fake.all_docs(ix.names.chunks))


def test_new_file_name_needs_replace_flag(fake, ix, response_small):
    run(ix, response_small)
    v2 = new_version(response_small, "Betriebshandbuch_ZSD_v3.pdf")  # not in ontology -> page-1 regex -> same doc_id
    with pytest.raises(PlanError, match="--replace"):
        ix.plan(v2)
    plan, report = run(ix, v2, replace=True)
    assert plan.action == "replace" and report.status == "active"


def test_same_content_under_other_doc_id_is_refused(fake, ix, response_small):
    run(ix, response_small)
    with pytest.raises(PlanError, match="already indexed as doc_id BHB-PLT-0007"):
        ix.plan(response_small, doc_id_override="BHB-PLT-9999")
    plan = ix.plan(response_small, doc_id_override="BHB-PLT-9999", force=True)
    assert plan.action == "ingest" and any("forced" in w for w in plan.warnings)


# ---------------------------------------------------------------- lease


def _set_indexing(fake, ix, started_at):
    m = {
        "doc_id": "BHB-PLT-0007", "status": "indexing", "run_id": "x" * 64, "previous_run_id": None,
        "doc_sha256": "2bb722f565a0ff49ccb42790a6ada683d86cef0486c8a1da8b55f5265c845c72", "doc_name": "Betriebshandbuch_ZSD.pdf",
        "doc_id_source": "ontology_file", "owner": "other:9", "started_at": started_at, "finished_at": None,
        "counts": None, "swept": None, "embedding_model": "test-8d", "mapping_version": MAPPING_VERSION,
        "indexer_version": "0.1.0", "error": None, "history": [],
    }
    fake.index(index=ix.names.manifest, id="BHB-PLT-0007", body=m)


def test_lease_held_by_running_ingest(fake, ix, response_small):
    _set_indexing(fake, ix, datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    with pytest.raises(LeaseHeld, match="in progress"):
        run(ix, response_small)
    assert counts(fake, ix.names)["chunks"] == 0
    plan, report = run(ix, response_small, force=True)  # takeover
    assert report.status == "active"


def test_stale_lease_is_taken_over(fake, ix, response_small):
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    _set_indexing(fake, ix, old)
    plan, report = run(ix, response_small)
    assert report.status == "active" and manifest(fake, ix)["owner"] == "test:1"


def test_concurrent_manifest_change_is_detected(fake, ix, response_small, monkeypatch):
    plan = ix.plan(response_small)
    # someone else writes the manifest between plan and lease
    _set_indexing(fake, ix, (datetime.now(UTC) - timedelta(hours=2)).isoformat().replace("+00:00", "Z"))
    with pytest.raises(LeaseHeld, match="changed underneath"):
        ix.ingest(plan, response_small)


# ---------------------------------------------------------------- failure and healing


def test_failed_bulk_keeps_previous_run_and_retry_heals(fake, ix, response_small, monkeypatch):
    first, _ = run(ix, response_small)
    other = mutated(response_small)

    def failing_bulk(client, actions, **kw):
        n = 0
        for a in actions:
            if a["_index"].endswith("chunks") and n >= 5:
                continue  # silently lose the rest -> item errors
            client.index(index=a["_index"], id=a["_id"], body=a["_source"])
            n += 1
        return n, [{"index": {"_id": "lost", "error": {"type": "boom"}}}]

    monkeypatch.setattr(ix_mod.helpers, "bulk", failing_bulk)
    with pytest.raises(IngestError, match="bulk"):
        run(ix, other)
    m = manifest(fake, ix)
    assert m["status"] == "failed" and "bulk" in m["error"]
    assert m["previous_run_id"] == first.run_id
    # nothing was swept: the old run's records are all still there (superset, never a hole)
    assert ix._count(ix.names.chunks, "BHB-PLT-0007", first.run_id) >= 12 - 5
    assert counts(fake, ix.names)["chunks"] == 12
    monkeypatch.setattr(ix_mod.helpers, "bulk", fake_bulk)
    plan, report = run(ix, other)
    assert plan.action == "ingest" and any("failed" in r for r in plan.reasons)
    assert report.status == "active" and counts(fake, ix.names) == {"chunks": 11, "nodes": 58, "documents": 1}
    assert manifest(fake, ix)["previous_run_id"] == first.run_id


def test_count_verification_blocks_sweep(fake, ix, response_small, monkeypatch):
    run(ix, response_small)
    other = mutated(response_small)

    def lossy_bulk(client, actions, **kw):  # claims success but drops one node
        dropped = False
        for a in actions:
            if a["_index"].endswith("nodes") and not dropped:
                dropped = True
                continue
            client.index(index=a["_index"], id=a["_id"], body=a["_source"])
        return 0, []

    monkeypatch.setattr(ix_mod.helpers, "bulk", lossy_bulk)
    with pytest.raises(IngestError, match="count verification"):
        run(ix, other)
    assert manifest(fake, ix)["status"] == "failed"
    assert counts(fake, ix.names)["chunks"] == 12  # old chunk not swept


# ---------------------------------------------------------------- dry run, delete, status


def test_dry_run_writes_nothing(fake, ix, response_small):
    plan, report = run(ix, response_small, dry_run=True)
    assert report.status == "dry-run" and report.counts["chunks"] == 12
    assert report.sweep_query["query"]["bool"]["must_not"] == [{"term": {"run_id": plan.run_id}}]
    assert counts(fake, ix.names) == {"chunks": 0, "nodes": 0, "documents": 0}
    assert fake.count(ix.names.manifest)["count"] == 0


def test_delete_document(fake, ix, response_small):
    run(ix, response_small)
    out = ix.delete_document("BHB-PLT-0007")
    assert out == {"chunks": 12, "nodes": 59, "documents": 1, "manifest": 1}
    assert counts(fake, ix.names) == {"chunks": 0, "nodes": 0, "documents": 0}
    assert ix.delete_document("BHB-PLT-0007") == {"chunks": 0, "nodes": 0, "documents": 0, "manifest": 0}


def test_status(fake, ix, response_small):
    st = ix.status()
    assert st["documents"] == [] and st["indices"]["bhbtest-chunks"] == 0
    run(ix, response_small)
    st = ix.status()
    row = st["documents"][0]
    assert row["doc_id"] == "BHB-PLT-0007" and row["status"] == "active"
    assert row["indexed"] == {"chunks": 12, "nodes": 59}
    assert st["attention"] == []
    assert st["cross_document_node_ids"]["count"] == 0
    fake.index(index=ix.names.manifest, id="BHB-PLT-0007", body={**manifest(fake, ix), "status": "failed", "error": "x"})
    assert any("failed" in a for a in ix.status()["attention"])
