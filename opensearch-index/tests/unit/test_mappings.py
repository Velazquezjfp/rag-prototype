from opensearch_index.mappings import (
    MAPPING_VERSION,
    IndexNames,
    chunks_mapping,
    documents_mapping,
    index_bodies,
    manifest_mapping,
    nodes_mapping,
    rrf_pipeline_body,
    sweep_query,
)
from opensearch_index.transform import build_batch


def _props(mapping):
    return set(mapping["properties"])


def test_every_emitted_field_is_mapped(response_small, ontology, settings):
    """dynamic: strict rejects unknown fields at index time; catch that here instead."""
    b = build_batch(
        response_small,
        doc_id="BHB-PLT-0007",
        doc_id_source="ontology_file",
        run_id="r" * 64,
        ontology=ontology,
        embedding_model="test-8d",
        embedding_dim=8,
        embedding_text_prefix="",
        indexed_at="2026-09-02T00:00:00Z",
    )
    chunk_props = _props(chunks_mapping(settings.embedding, settings.index))
    for c in b.chunks:
        assert set(c) <= chunk_props, set(c) - chunk_props
    node_props = _props(nodes_mapping())
    for n in b.nodes:
        assert set(n) <= node_props, set(n) - node_props
    assert set(b.document) <= _props(documents_mapping()), set(b.document) - _props(documents_mapping())


def test_chunks_mapping_knn_field(settings):
    m = chunks_mapping(settings.embedding, settings.index)
    emb = m["properties"]["embedding"]
    assert emb["dimension"] == 8
    assert emb["space_type"] == "cosinesimil"
    assert emb["method"]["engine"] == "lucene" and emb["method"]["name"] == "hnsw"
    assert m["_meta"]["mapping_version"] == MAPPING_VERSION and m["_meta"]["embedding_model"] == "test-8d"
    assert m["dynamic"] == "strict"


def test_index_bodies(settings):
    names = IndexNames("bhbtest")
    bodies = index_bodies(names, settings.embedding, settings.index)
    assert set(bodies) == {"bhbtest-chunks", "bhbtest-nodes", "bhbtest-documents", "bhbtest-manifest"}
    assert bodies["bhbtest-chunks"]["settings"]["index"]["knn"] is True
    assert "knn" not in bodies["bhbtest-nodes"]["settings"]["index"]
    for alias, body in bodies.items():
        assert body["aliases"] == {alias: {}}
        assert body["mappings"]["dynamic"] == "strict"
        assert body["settings"]["analysis"]["analyzer"]["de_text"]["filter"][-1] == "de_stem"
    assert names.physical("bhbtest-chunks") == f"bhbtest-chunks-v{MAPPING_VERSION}"
    assert names.rrf_pipeline == "bhbtest-rrf"


def test_manifest_mapping_has_state_fields():
    props = _props(manifest_mapping())
    assert {"doc_id", "status", "run_id", "previous_run_id", "doc_sha256", "owner", "started_at", "finished_at", "history", "error"} <= props


def test_sweep_query():
    q = sweep_query("BHB-PLT-0007", "abc")
    assert q["query"]["bool"]["filter"] == [{"term": {"doc_id": "BHB-PLT-0007"}}]
    assert q["query"]["bool"]["must_not"] == [{"term": {"run_id": "abc"}}]


def test_rrf_pipeline_body():
    body = rrf_pipeline_body(42)
    proc = body["phase_results_processors"][0]["score-ranker-processor"]
    assert proc["combination"] == {"technique": "rrf", "rank_constant": 42}
