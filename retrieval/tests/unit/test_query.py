from rag_retrieval.graph import GraphStore
from rag_retrieval.query import (
    STOPWORDS_DE,
    analyze_question,
    extract_question_identifiers,
    match_labels,
    partial_label_matches,
    question_keys,
)


def test_identifiers_all_ontology_patterns(ontology):
    q = "Was war bei ZSDSUP-0247 laut BHB-PLT-0007, SOP-ZSD-05, FW-ZSD-004 in ZONE-APP-WE auf iam-p01?"
    ids = extract_question_identifiers(q, ontology.regexes)
    assert {"ZSDSUP-0247", "BHB-PLT-0007", "SOP-ZSD-05", "FW-ZSD-004", "ZONE-APP-WE", "iam-p01"} <= set(ids)


def test_host_identifier_is_found_when_typed_with_capitals(ontology):
    assert extract_question_identifiers("Läuft Vault auf IAM-P01?", ontology.regexes) == ["iam-p01"]


def test_no_identifiers_in_plain_question(ontology):
    assert extract_question_identifiers("Was passiert, wenn Vault versiegelt ist?", ontology.regexes) == []


def test_label_ngrams_longest_match_wins(graph_small):
    keys, resolved, terms = match_labels("Wer ist Kai Ostermann und was macht Keycloak?", graph_small)
    assert "kai ostermann" in keys and "keycloak" in keys
    assert all(nid.startswith("Person_") for nid in resolved["kai ostermann"])
    assert "kai ostermann" in terms and "keycloak" in terms


def test_stopwords_and_short_tokens_do_not_resolve(graph_small):
    keys, _, _ = match_labels("wer ist das und wie", graph_small)
    assert keys == []
    assert {"wer", "ist", "das", "und", "wie"} <= STOPWORDS_DE


def test_alias_inside_longer_match_is_also_resolved(graph_small):
    # "Marcel Ebert" (Person) and the alias-only node "Ebert" both exist in the fixture graph
    keys, resolved, _ = match_labels("Was macht Marcel Ebert?", graph_small)
    assert keys[0] == "marcel ebert"
    assert "ebert" in keys


def test_sharp_s_terms_keep_the_stored_spelling():
    """node_labels is lowercase-normalized only; norm_key folds ß->ss, so the term must be the lowercased original."""
    g = GraphStore()
    g.add_document(
        "D1",
        {
            "nodes": [
                {"id": "Person_1", "type": "Person", "label": "Dr. Annika Reuß", "aliases": ["Annika Reuß"], "attributes": {}, "provenance": {"pages": [26], "chunk_ids": []}}
            ],
            "edges": [],
        },
    )
    keys, resolved, terms = match_labels("An wen eskaliert Annika Reuß?", g)
    assert keys == ["annika reuss"]
    assert resolved["annika reuss"] == {"Person_1"}
    assert terms == ["annika reuß"]


def test_hyphen_compound_parts_resolve(graph_small):
    keys, _, _ = match_labels("Wie hängt Keycloak-Vollausfall zusammen?", graph_small)
    assert "keycloak" in keys


def test_question_keys_drop_stopwords_and_split_compounds():
    keys = question_keys("Wie erneuere ich ein TLS-Zertifikat für iam-p01?")
    assert "tls-zertifikat" in keys and "tls" in keys and "zertifikat" in keys
    assert "wie" not in keys and "ich" not in keys and "ein" not in keys


def test_partial_matches_need_an_anchor(graph_small):
    keys = question_keys("Was passiert bei einem Keycloak Vollausfall?")
    with_anchor = partial_label_matches(keys, graph_small, anchors={"keycloak"})
    assert with_anchor and all(graph_small.label(n).startswith("Keycloak Vollausfall") for n in with_anchor)
    assert partial_label_matches(keys, graph_small, anchors=set()) == []
    # generic pairs without an anchor word do not match anything
    assert partial_label_matches(question_keys("neu starten"), graph_small, anchors={"dispatcher"}) == []


def test_analyze_question_plan(graph_small, ontology):
    plan = analyze_question("Was passiert bei einem Keycloak Vollausfall (ZSDSUP-0247)?", regexes=ontology.regexes, graph=graph_small)
    assert plan.identifiers == ["ZSDSUP-0247"]
    assert "keycloak" in plan.label_candidates and "zsdsup-0247" in plan.label_candidates
    assert plan.partial_nodes  # the four "Keycloak Vollausfall | X" ImpactStatements
    assert any(t.startswith("keycloak vollausfall") for t in plan.label_terms)
    assert plan.start_nodes and all(n in plan.start_nodes for ids in plan.resolved.values() for n in ids)
    assert plan.as_dict()["identifiers"] == ["ZSDSUP-0247"]


def test_analyze_without_graph(ontology):
    plan = analyze_question("Was war bei ZSDSUP-0247?", regexes=ontology.regexes, graph=None)
    assert plan.identifiers == ["ZSDSUP-0247"] and plan.label_candidates == [] and plan.partial_nodes == []
