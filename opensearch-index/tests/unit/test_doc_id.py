import pytest

from opensearch_index.identity import DocIdUnresolved, resolve_doc_id


def _strip_page1_ids(resp):
    for c in resp.chunks:
        if c.page_numbers == [1]:
            c.text = c.text.replace("BHB-PLT-0007", "")


def test_ontology_file_wins(response_small, ontology):
    res = resolve_doc_id(response_small, ontology)
    assert res.doc_id == "BHB-PLT-0007"
    assert res.source == "ontology_file"
    assert res.warnings == []
    assert res.candidates["page1_regex"] == "BHB-PLT-0007"
    assert res.candidates["documents_edge"] == "BHB-PLT-0007"


def test_title_page_regex_fallback(response_small, ontology):
    response_small.document.name = "unknown.pdf"
    res = resolve_doc_id(response_small, ontology)
    assert (res.doc_id, res.source) == ("BHB-PLT-0007", "page1_regex")


def test_documents_edge_fallback(response_small, ontology):
    response_small.document.name = "unknown.pdf"
    _strip_page1_ids(response_small)
    res = resolve_doc_id(response_small, ontology)
    assert (res.doc_id, res.source) == ("BHB-PLT-0007", "documents_edge")


def test_unresolved_never_guesses_from_the_file_name(response_small, ontology):
    response_small.document.name = "Betriebshandbuch_Unbekannt.pdf"
    _strip_page1_ids(response_small)
    response_small.graph = None
    with pytest.raises(DocIdUnresolved, match="--doc-id"):
        resolve_doc_id(response_small, ontology)


def test_override_wins_and_disagreement_is_reported(response_small, ontology):
    res = resolve_doc_id(response_small, ontology, override="bhb-plt-0042")
    assert (res.doc_id, res.source) == ("BHB-PLT-0042", "override")
    assert any("disagrees" in w for w in res.warnings)


def test_ambiguous_title_page_is_ignored(response_small, ontology):
    response_small.document.name = "unknown.pdf"
    for c in response_small.chunks:
        if c.page_numbers == [1] and "BHB-PLT-0007" in c.text:
            c.text += " siehe auch BHB-VRF-0207"
    res = resolve_doc_id(response_small, ontology)
    assert res.source == "documents_edge"
    assert any("several document ids" in w for w in res.warnings)


def test_later_pages_do_not_count(response_small, ontology):
    # page 2 cites four other manuals; only page 1 may decide
    response_small.document.name = "unknown.pdf"
    res = resolve_doc_id(response_small, ontology)
    assert res.doc_id == "BHB-PLT-0007"
