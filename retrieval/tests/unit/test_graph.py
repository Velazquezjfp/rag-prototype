import json

import pytest
from conftest import GRAPH_ZSD
from opensearch_index.identity import edge_id as compute_edge_id
from opensearch_index.schemas import GraphEdge

from rag_retrieval.graph import GraphStore, tokenize, type_rank


def test_small_graph_loaded_from_document_record(graph_small, small_batch):
    st = graph_small.stats()
    assert st.documents == ["BHB-PLT-0007"]
    assert st.node_ids == len(small_batch.nodes) == 59
    assert st.edge_ids == len(small_batch.edge_ids) == 11 and st.edge_records == 11
    assert st.shared_node_ids == 0 and st.negative_edges == 0
    assert st.nodes_by_type["ImpactStatement"] == 20
    assert graph_small.title("BHB-PLT-0007") == "Betriebshandbuch ZSD - Zentrale Sicherheitsdienste"
    assert graph_small.titles == {"BHB-PLT-0007": "Betriebshandbuch ZSD - Zentrale Sicherheitsdienste"}
    assert graph_small.documents["BHB-PLT-0007"].embedding_model == "test-8d"


def test_lookups(graph_small):
    ids = graph_small.resolve("keycloak")
    assert ids == {"Component_9ac69fd304962fd3"}
    assert graph_small.type_of("Component_9ac69fd304962fd3") == "Component"
    assert graph_small.label("nope") == "nope" and graph_small.type_of("nope") is None
    assert graph_small.label_forms("keycloak") == {"Keycloak"}
    assert "vollausfall" in graph_small.label_tokens("ImpactStatement_2362b3b496672170")
    assert graph_small.nodes_with_token("vollausfall") >= {"ImpactStatement_2362b3b496672170"}
    assert graph_small.resolve("zsd") >= {"System_75ad2ed0e39eb520"}  # alias


def test_expand_one_hop_all_relations(graph_small):
    doc = "Document_ddfceb8b3907ff3e"
    expanded = graph_small.expand([doc])
    types = sorted({occ[0].type for occ in expanded.values()})
    assert types == ["DOCUMENTS", "RELATED_DOCUMENT"]
    assert len(expanded) == 7  # 1 DOCUMENTS + 3 outgoing + 3 incoming RELATED_DOCUMENT
    assert graph_small.neighbours(doc) >= {"System_75ad2ed0e39eb520", "Document_234d427649efd1ba"}
    assert graph_small.expand([doc], doc_ids=["OTHER"]) == {}
    assert graph_small.expand(["unknown"]) == {}


def test_edge_ids_computed_when_missing():
    raw = json.loads(GRAPH_ZSD.read_text(encoding="utf-8")) if GRAPH_ZSD.is_file() else None
    if raw is None:
        pytest.skip("reference graph missing")
    assert "id" not in raw["edges"][0]
    store = GraphStore.from_blobs([("BHB-PLT-0007", raw)])
    e0 = raw["edges"][0]
    eid = compute_edge_id(GraphEdge.model_validate(e0))
    assert store.edge(eid) and store.edge(eid)[0].source == e0["source"]
    assert len(eid) == 16


def test_missing_graph_blob_is_tolerated():
    store = GraphStore.from_blobs([("D", None)])
    assert store.stats().node_ids == 0 and "D" in store.documents


def test_tokenize_and_type_rank():
    assert tokenize("PKI-Ausfall (Issuing CA) | VPP") == ["pki-ausfall", "issuing", "ca", "vpp"]
    assert "pki" in tokenize("PKI-Ausfall", split_compounds=True)
    assert type_rank("ImpactStatement") == 0 < type_rank("Host") < type_rank("Term")


# ---------------------------------------------------------------- real graphs (skipped without out/)


def test_real_union_shares_node_ids(real_graph):
    st = real_graph.stats()
    assert st.documents == ["BHB-PLT-0001", "BHB-PLT-0007"]
    assert st.shared_node_ids == 60
    assert st.node_ids == 400 and st.edge_ids == 281 and st.negative_edges == 8


def test_real_vault_one_hop_has_the_two_negative_dependencies(real_graph):
    vault_ids = real_graph.resolve("vault")
    assert {real_graph.type_of(n) for n in vault_ids} >= {"System", "Component", "Host"}
    expanded = real_graph.expand(vault_ids)
    negatives = {
        (real_graph.label(e[0].source), e[0].type, real_graph.label(e[0].target), e[0].qualifier)
        for e in expanded.values()
        if e[0].polarity == "negative"
    }
    assert ("Vault", "DEPENDS_ON", "PKI", "für Vault-Unseal") in negatives
    assert ("Vault", "DEPENDS_ON", "Keycloak", "für Vault-Unseal") in negatives


def test_real_precedes_chain(real_graph):
    steps = [n for n in real_graph.label_index.values() for n in n if real_graph.type_of(n) == "StartupStep"]
    expanded = real_graph.expand(set(steps))
    assert sum(1 for e in expanded.values() if e[0].type == "PRECEDES") == 21


def test_real_ostermann_alias_and_shared_person(real_graph):
    ids = real_graph.resolve("kai ostermann")
    assert ids and any(len({o.doc_id for o in real_graph.occurrences(n)}) == 2 for n in ids)
    assert real_graph.resolve("ostermann")  # alias / short-form node
