import json

from opensearch_index.identity import (
    clean_text,
    edge_id,
    node_identity,
    normalize_identity,
)
from opensearch_index.ontology import IdentityRule
from opensearch_index.schemas import GraphEdge, GraphNode


def test_normalize_modes():
    assert normalize_identity("bhb-plt-0007", "upper") == "BHB-PLT-0007"
    assert normalize_identity("  Event-System   2.0 ", "casefold") == "event-system 2.0"
    assert normalize_identity("Dr. Martina Kellerhoff", "strip_titles_then_casefold") == "martina kellerhoff"
    assert normalize_identity("Prof. Dr. Hans Reuß", "strip_titles_then_casefold") == "hans reuss"  # casefold: ß -> ss, as in dgs norm_key
    assert normalize_identity("Vault.", None) == "vault"


def test_node_identity_simple_key():
    n = GraphNode(id="Incident_x", type="Incident", label="ZSDSUP-0247", attributes={"ticket_id": "zsdsup-0247"})
    assert node_identity(n, IdentityRule(keys=("ticket_id",)), None) == ("zsdsup-0247", "zsdsup-0247")


def test_node_identity_composite_and_scope():
    n = GraphNode(id="StartupStep_x", type="StartupStep", label="Vault entsiegeln", attributes={"order": 3})
    ident, norm = node_identity(n, IdentityRule(keys=("order", "label")), None)
    assert ident == "3|Vault entsiegeln"
    assert norm == "3|vault entsiegeln"
    comp = GraphNode(id="Component_x", type="Component", label="Dispatcher", attributes={})
    _, norm = node_identity(comp, IdentityRule(keys=("label",), normalize="casefold", scope="system"), "Zentrale Sicherheitsdienste")
    assert norm == "zentrale sicherheitsdienste::dispatcher"


def test_node_identity_falls_back_to_label():
    n = GraphNode(id="Host_x", type="Host", label="iam-p01", attributes={})
    assert node_identity(n, IdentityRule(keys=("hostname",)), None) == ("iam-p01", "iam-p01")


def test_edge_id_stable_and_content_sensitive():
    a = GraphEdge(source="A", target="B", type="DEPENDS_ON", polarity="negative", quote="q", provenance={"chunk_ids": ["x-1", "x-0"]})
    b = GraphEdge.model_validate(json.loads('{"provenance": {"chunk_ids": ["x-0", "x-1"]}, "quote": "q", "polarity": "negative", "type": "DEPENDS_ON", "target": "B", "source": "A"}'))
    assert edge_id(a) == edge_id(b)
    assert len(edge_id(a)) == 16
    c = a.model_copy(update={"quote": "other"})
    d = a.model_copy(update={"polarity": "positive"})
    assert len({edge_id(a), edge_id(c), edge_id(d)}) == 3


def test_edge_ids_unique_on_reference(real_response):
    ids = [edge_id(e) for e in real_response.graph.edges]
    assert len(ids) == len(set(ids)) == 154


def test_clean_text_removes_soft_hyphen():
    assert clean_text("Sicherheits­dienste") == "Sicherheitsdienste"
