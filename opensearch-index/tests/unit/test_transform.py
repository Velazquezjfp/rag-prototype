import copy

import pytest

from opensearch_index.mappings import IndexNames
from opensearch_index.transform import (
    VectorError,
    build_batch,
    bulk_actions,
    extract_identifiers,
    node_doc_id,
)


def _batch(resp, ontology, **over):
    kw = {
        "doc_id": "BHB-PLT-0007",
        "doc_id_source": "ontology_file",
        "run_id": "r" * 64,
        "ontology": ontology,
        "embedding_model": "test-8d",
        "embedding_dim": 8,
        "embedding_text_prefix": "",
        "indexed_at": "2026-09-02T00:00:00Z",
    }
    kw.update(over)
    return build_batch(resp, **kw)


def test_extract_identifiers(ontology):
    text = "Ticket ZSDSUP-0247 laut SOP-ZSD-06 auf iam-p01 (Zone ZONE-INT) siehe BHB-PLT-­0007, FW-ZSD-001"
    ids = extract_identifiers(text, ontology.regexes)
    assert {"ZSDSUP-0247", "SOP-ZSD-06", "iam-p01", "ZONE-INT", "BHB-PLT-0007", "FW-ZSD-001"} <= set(ids)
    assert extract_identifiers(None, ontology.regexes) == []


def test_batch_counts_and_ids(response_small, ontology):
    b = _batch(response_small, ontology)
    assert b.counts == {"chunks": 12, "nodes": len(response_small.graph.nodes), "edges": len(response_small.graph.edges), "documents": 1}
    assert b.sha12 == "2bb722f565a0"
    actions = list(bulk_actions(b, IndexNames("bhbtest")))
    assert len(actions) == 12 + len(b.nodes) + 1
    chunk_ids = {a["_id"] for a in actions if a["_index"] == "bhbtest-chunks"}
    assert chunk_ids == {c.chunk_id for c in response_small.chunks}
    node_ids = {a["_id"] for a in actions if a["_index"] == "bhbtest-nodes"}
    assert node_ids == {node_doc_id("2bb722f565a0", n.id) for n in response_small.graph.nodes}
    assert [a["_id"] for a in actions if a["_index"] == "bhbtest-documents"] == ["BHB-PLT-0007"]
    assert all(a["_op_type"] == "index" for a in actions)


def test_chunk_documents(response_small, ontology):
    b = _batch(response_small, ontology)
    by_id = {c["chunk_id"]: c for c in b.chunks}
    title = by_id["2bb722f565a0-0002"]
    assert "BHB-PLT-0007" in title["identifiers"]
    assert title["doc_id"] == "BHB-PLT-0007" and title["run_id"] == "r" * 64
    assert title["embedding_model"] == "test-8d" and len(title["embedding"]) == 8
    doc_chunk = by_id["2bb722f565a0-0007"]
    assert "Document_ddfceb8b3907ff3e" in doc_chunk["node_ids"]
    assert "Document" in doc_chunk["node_types"]
    assert "BHB-PLT-0007" in doc_chunk["node_labels"]  # alias of the Document node
    assert "­" not in "".join(c["text"] for c in b.chunks)


def test_edge_endpoints_reach_the_evidence_chunk(response_small, ontology):
    b = _batch(response_small, ontology)
    by_id = {c["chunk_id"]: c for c in b.chunks}
    for e, eid in zip(response_small.graph.edges, b.edge_ids, strict=True):
        for cid in e.provenance.chunk_ids:
            c = by_id[cid]
            assert eid in c["edge_ids"]
            assert {e.source, e.target} <= set(c["node_ids"])


def test_node_documents(response_small, ontology):
    b = _batch(response_small, ontology)
    doc_node = next(n for n in b.nodes if n["node_id"] == "Document_ddfceb8b3907ff3e")
    assert doc_node["identity"] == "BHB-PLT-0007" and doc_node["identity_norm"] == "BHB-PLT-0007"
    assert doc_node["attributes"]["doc_id"] == "BHB-PLT-0007"
    assert "BHB-PLT-0007" in doc_node["identifiers"]
    assert doc_node["degree"] >= 1
    assert doc_node["scope"] == "document"
    assert all("attributes" not in n or n["attributes"] for n in b.nodes)  # empty attributes are omitted


def test_document_record(response_small, ontology):
    b = _batch(response_small, ontology)
    d = b.document
    assert d["title"].startswith("Betriebshandbuch ZSD")
    assert d["version"] == "2.3" and d["ci_id"] == "CI-PLT-0007"
    assert d["root_system"] == "Zentrale Sicherheitsdienste"
    assert "BHB-VRF-0207" in d["related_doc_ids"] and "BHB-PLT-0007" not in d["related_doc_ids"]
    assert d["markdown"] == response_small.markdown
    assert [e["id"] for e in d["graph"]["edges"]] == b.edge_ids
    assert d["counts"]["chunks"] == 12
    assert d["embedding_dim"] == 8


def test_vector_validation(response_small, ontology):
    with pytest.raises(VectorError, match="dim"):
        _batch(response_small, ontology, embedding_dim=1024)
    zero = copy.deepcopy(response_small)
    zero.chunks[1].embedding = [0.0] * 8
    with pytest.raises(VectorError, match="zero"):
        _batch(zero, ontology)
    none = copy.deepcopy(response_small)
    none.chunks[1].embedding = None
    b = _batch(none, ontology)
    assert "embedding" not in b.chunks[1] and "embedding" in b.chunks[0]


def test_graph_none(response_small, ontology):
    response_small.graph = None
    b = _batch(response_small, ontology)
    assert b.nodes == [] and b.edge_ids == [] and b.document["graph"] is None
    assert b.chunks[7]["node_ids"] == []
    assert b.counts["edges"] == 0
