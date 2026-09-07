from conftest import ONTOLOGY_PATH

from rag_retrieval import facts as F
from rag_retrieval.graph import GraphStore
from rag_retrieval.models import ChannelEvidence, ChunkHit


def _store() -> GraphStore:
    g = GraphStore()
    g.add_document(
        "BHB-PLT-0007",
        {
            "nodes": [
                {"id": "Component_vault", "type": "Component", "label": "Vault", "aliases": [], "attributes": {"technology": "Vault 1.16"}, "provenance": {"pages": [9], "chunk_ids": ["z-0026"]}},
                {"id": "Component_pki", "type": "Component", "label": "PKI", "aliases": ["Public-Key-Infrastruktur"], "attributes": {}, "quote": "PKI mit Issuing CA", "provenance": {"pages": [6], "chunk_ids": ["z-0010"]}},
                {"id": "Person_kai", "type": "Person", "label": "Kai Ostermann", "aliases": [], "attributes": {"role_title": "IAM-Betrieb", "phone_ext": "1315"}, "provenance": {"pages": [26], "chunk_ids": ["z-0088"]}},
                {"id": "Person_ost", "type": "Person", "label": "Ostermann", "aliases": ["Kai Ostermann"], "attributes": {"org_unit": "IT-S 1"}, "provenance": {"pages": [22], "chunk_ids": ["z-0070"]}},
                {"id": "Impact_vpp", "type": "ImpactStatement", "label": "Vault versiegelt | VPP", "aliases": [], "attributes": {"severity": "keine", "symptom": "keine", "event": "Vault versiegelt"}, "provenance": {"pages": [19], "chunk_ids": ["z-0060"]}},
                {"id": "Doc_zsd", "type": "Document", "label": "BHB ZSD", "aliases": [], "attributes": {"doc_id": "BHB-PLT-0007"}, "provenance": {"pages": [1], "chunk_ids": ["z-0000"]}},
                {"id": "Term_x", "type": "Term", "label": "Sealed", "aliases": [], "attributes": {"definition": "versiegelt"}, "provenance": {"pages": [29], "chunk_ids": ["z-0100"]}},
                {"id": "Person_reuss", "type": "Person", "label": "Dr. Annika Reuß", "aliases": [], "attributes": {}, "provenance": {"pages": [26], "chunk_ids": ["z-0088"]}},
            ],
            "edges": [
                {"id": "e-neg", "source": "Component_vault", "target": "Component_pki", "type": "DEPENDS_ON", "polarity": "negative", "qualifier": "für Vault-Unseal", "quote": "benötigt weder PKI noch IAM", "properties": {"dependency_kind": "zertifikat"}, "provenance": {"pages": [19], "chunk_ids": ["z-0063"]}},
                {"id": "e-pos", "source": "Component_pki", "target": "Component_vault", "type": "DEPENDS_ON", "polarity": "positive", "qualifier": None, "quote": "Zugangsdaten in Vault", "properties": {}, "provenance": {"pages": [19], "chunk_ids": ["z-0063"]}},
                {"id": "e-resp", "source": "Person_kai", "target": "Component_vault", "type": "RESPONSIBLE_FOR", "polarity": "positive", "qualifier": None, "quote": None, "properties": {"raci": "verantwortlich", "empty": None}, "provenance": {"pages": [26], "chunk_ids": ["z-0088"]}},
                {"id": "e-unk", "source": "Person_kai", "target": "Person_reuss", "type": "ESCALATES_TO", "polarity": "unknown", "qualifier": None, "quote": None, "properties": {"level": 2}, "provenance": {"pages": [26], "chunk_ids": ["z-0088"]}},
                {"id": "e-doc", "source": "Doc_zsd", "target": "Component_vault", "type": "DOCUMENTS", "polarity": "positive", "qualifier": None, "quote": None, "properties": {}, "provenance": {"pages": [1], "chunk_ids": ["z-0000"]}},
            ],
        },
    )
    g.add_document(
        "BHB-PLT-0001",
        {
            "nodes": [
                {"id": "Component_vault", "type": "Component", "label": "Vault", "aliases": [], "attributes": {"technology": "Vault 1.16"}, "provenance": {"pages": [4], "chunk_ids": ["c-0004"]}},
                {"id": "Person_kai", "type": "Person", "label": "Kai Ostermann", "aliases": [], "attributes": {"role_title": "IAM (Keycloak)"}, "provenance": {"pages": [6], "chunk_ids": ["c-0006"]}},
            ],
            "edges": [
                {"id": "e-resp", "source": "Person_kai", "target": "Component_vault", "type": "RESPONSIBLE_FOR", "polarity": "positive", "qualifier": None, "quote": None, "properties": {"raci": "verantwortlich"}, "provenance": {"pages": [6], "chunk_ids": ["c-0006"]}},
            ],
        },
    )
    return g


REL = {"DEPENDS_ON": "hängt ab von", "RESPONSIBLE_FOR": "verantwortlich für", "ESCALATES_TO": "eskaliert an"}


def test_render_negative_fact_with_qualifier_quote_and_label_de():
    g = _store()
    text = F.render_fact(g, g.edge("e-neg"), relation_de="hängt ab von")
    assert text.startswith("Vault —DEPENDS_ON (hängt ab von)→ PKI (dependency_kind=zertifikat): NICHT (für Vault-Unseal) — „benötigt weder PKI noch IAM“")
    assert text.endswith("[BHB-PLT-0007 S. 19; Kante e-neg]")
    assert "Kante" not in F.render_fact(g, g.edge("e-neg"), relation_de=None, edge_ref=False)


def test_render_unknown_and_merged_occurrences():
    g = _store()
    unk = F.render_fact(g, g.edge("e-unk"), relation_de="eskaliert an")
    assert "(unsicher)" in unk and "(level=2)" in unk
    same_edge_two_books = F.render_fact(g, g.edge("e-resp"), relation_de=None)
    assert "[BHB-PLT-0007 S. 26; BHB-PLT-0001 S. 6; Kante e-resp]" in same_edge_two_books
    assert "empty" not in same_edge_two_books  # None-valued properties are dropped


def test_build_facts_order_negative_first_then_boost_then_priority():
    g = _store()
    expanded = g.expand(["Component_vault", "Person_kai"])
    facts = F.build_facts(g, expanded, start_nodes=["Component_vault", "Person_kai"], label_nodes=["Component_vault"], relation_labels=REL, max_facts=10)
    assert [f.edge_id for f in facts][:2] == ["e-neg", "e-pos"]  # touch the label node, negative first
    assert facts[0].polarity == "negative" and facts[0].relation_de == "hängt ab von" and facts[0].via_start_node == "Vault"
    assert facts[0].doc_ids == ["BHB-PLT-0007"] and facts[0].pages == [19] and facts[0].chunk_ids == ["z-0063"]
    resp = next(f for f in facts if f.edge_id == "e-resp")
    assert resp.doc_ids == ["BHB-PLT-0001", "BHB-PLT-0007"] and resp.pages == [6, 26]
    boosted = F.build_facts(g, expanded, start_nodes=["Person_kai", "Component_vault"], label_nodes=[], relation_labels=REL, max_facts=10, boost=("ESCALATES_TO",))
    assert boosted[0].edge_id == "e-unk"  # the relation the question asks about comes first ...
    assert boosted[1].edge_id == "e-neg"  # ... then negatives before positives among the rest
    assert len(F.build_facts(g, expanded, start_nodes=[], label_nodes=[], relation_labels={}, max_facts=2)) == 2


def _hit(rank, node_ids):
    return ChunkHit(chunk_id=f"c{rank}", doc_id="D", rank=rank, fused_score=1.0 / rank, channels=[ChannelEvidence(channel="knn", rank=rank)], group_key=f"c{rank}", node_ids=node_ids)


def test_select_start_nodes_priorities_and_cap():
    g = _store()
    seeds = [_hit(1, ["Doc_zsd", "Term_x", "Person_reuss", "Component_pki"]), _hit(2, ["Component_pki", "Impact_vpp"])]
    order = F.select_start_nodes(g, label_nodes=["Component_vault", "unknown"], seed_hits=seeds, max_nodes=10, partial_nodes=["Impact_vpp"], question_keys={"pki"})
    assert order[0] == "Component_vault" and order[1] == "Impact_vpp"
    assert order[2] == "Component_pki"  # mentions a question word (and is in two seeds)
    assert "Doc_zsd" not in order and "Term_x" not in order
    assert F.select_start_nodes(g, label_nodes=[], seed_hits=seeds, max_nodes=1) == ["Component_pki"]
    boosted = F.select_start_nodes(g, label_nodes=[], seed_hits=seeds, max_nodes=10, boost_types=("Person",))
    assert boosted[0] == "Person_reuss"


def test_entity_cards_merge_alias_keep_conflicts_and_skip_empty():
    g = _store()
    cards = F.build_entity_cards(g, ["Person_kai", "Person_ost", "Component_vault", "Impact_vpp", "Person_reuss", "Component_pki"], matched_by={"Component_vault": "label", "Impact_vpp": "label"}, max_entities=10)
    by_label = {c.label: c for c in cards}
    kai = by_label["Kai Ostermann"]
    assert set(kai.node_ids) == {"Person_kai", "Person_ost"} and "Ostermann" in kai.aliases
    assert len(kai.occurrences) == 3  # 2 books for Person_kai (different attributes) + Person_ost
    assert "IAM-Betrieb" in kai.rendered and "IAM (Keycloak)" in kai.rendered and "[BHB-PLT-0001 S. 6]" in kai.rendered
    vault = by_label["Vault"]
    assert [o.doc_id for o in vault.occurrences] == ["BHB-PLT-0007", "BHB-PLT-0001"]  # one occurrence per book is kept
    assert vault.rendered == "Vault (Component) — technology: Vault 1.16 [BHB-PLT-0007 S. 9; BHB-PLT-0001 S. 4]"  # identical -> one line
    vpp = by_label["Vault versiegelt | VPP"]
    assert "severity: keine" in vpp.rendered and vpp.matched_by == "label"
    assert "Dr. Annika Reuß" not in by_label  # no attributes, no quote -> nothing to say
    assert by_label["PKI"].rendered.startswith("PKI (Component; auch: Public-Key-Infrastruktur) — PKI mit Issuing CA")
    assert [c.matched_by for c in cards][:2] == ["label", "label"]  # label-matched cards first


def test_entity_cards_respect_doc_filter_and_cap():
    g = _store()
    cards = F.build_entity_cards(g, ["Person_kai", "Component_vault"], matched_by={}, doc_ids=["BHB-PLT-0001"], max_entities=1)
    assert len(cards) == 1 and all(o.doc_id == "BHB-PLT-0001" for o in cards[0].occurrences)


def test_value_cap_and_props_rendering():
    long = "x" * 1000
    assert F.render_attributes({"a": long}).endswith("…") and len(F.render_attributes({"a": long})) < 420
    assert F.render_props({"a": [1, 2], "b": {"k": "v"}, "c": None, "d": ""}) == "a=1, 2, b=k: v"


def test_relation_and_type_boost_cues():
    assert F.relation_boost("Wer ist für IAM zuständig und wie eskaliere ich?")[:2] == ("RESPONSIBLE_FOR", "ESCALATES_TO")
    assert F.relation_boost("In welcher Reihenfolge fährt der Verbund an?")[0] == "PRECEDES"
    assert "IMPACT_OF" in F.relation_boost("Was passiert, wenn Vault versiegelt ist?")
    assert F.relation_boost("Was war bei ZSDSUP-0247?")[0] == "PARTNER_TICKET"
    assert F.relation_boost("Apfelkuchen") == ()
    assert F.type_boost("Reihenfolge beim Kaltstart")[0] == "StartupStep"
    assert F.type_boost("wer ist verantwortlich")[0] == "Person"


def test_graph_chunk_ids_order_and_cap():
    g = _store()
    expanded = g.expand(["Component_vault"])
    facts = F.build_facts(g, expanded, start_nodes=["Component_vault"], label_nodes=["Component_vault"], relation_labels=REL, max_facts=10)
    ids = F.graph_chunk_ids(facts, g, label_nodes=["Component_vault"], neighbours=["Component_pki"], limit=100)
    assert ids[0] == "z-0063" and "z-0026" in ids and "z-0010" in ids and len(ids) == len(set(ids))
    assert len(F.graph_chunk_ids(facts, g, label_nodes=[], neighbours=[], limit=1)) == 1


def test_load_relation_labels_from_ontology():
    labels = F.load_relation_labels(ONTOLOGY_PATH)
    assert labels.get("DEPENDS_ON") == "hängt ab von" and labels.get("PARTNER_TICKET") == "Partnervorgang"
    assert F.load_relation_labels("/nonexistent.yaml") == {}
