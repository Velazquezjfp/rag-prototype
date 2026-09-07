import pytest

from rag_retrieval import search


def _excludes(body):
    return body["_source"]["excludes"]


def test_knn_body_sets_k_and_size_and_excludes():
    body = search.knn_body([0.1] * 8, 7)
    assert body["size"] == 7
    assert body["query"]["knn"]["embedding"]["k"] == 7
    assert "filter" not in body["query"]["knn"]["embedding"]
    assert set(_excludes(body)) == {"embedding", "bboxes"}


def test_knn_filter_goes_inside_the_knn_clause():
    body = search.knn_body([0.1] * 8, 5, doc_ids=["BHB-PLT-0007", "BHB-PLT-0001"])
    clause = body["query"]["knn"]["embedding"]
    assert clause["filter"] == {"terms": {"doc_id": ["BHB-PLT-0001", "BHB-PLT-0007"]}}
    assert "bool" not in body["query"]


def test_bm25_body_fields_and_filter():
    plain = search.bm25_body("Vault versiegelt", 20)
    assert plain["query"]["multi_match"]["fields"] == ["text^2", "body_text", "caption"]
    filtered = search.bm25_body("Vault", 20, doc_ids=["BHB-PLT-0007"])
    assert filtered["query"]["bool"]["filter"] == [{"terms": {"doc_id": ["BHB-PLT-0007"]}}]
    assert filtered["query"]["bool"]["must"][0]["multi_match"]["query"] == "Vault"


def test_identifier_and_label_bodies_use_should_terms():
    body = search.identifier_body(["ZSDSUP-0247", "CAASUP-0351"], 20)
    should = body["query"]["bool"]["should"]
    assert {"term": {"identifiers": "ZSDSUP-0247"}} in should and body["query"]["bool"]["minimum_should_match"] == 1
    lbl = search.label_body(["vault", "keycloak"], 20)
    assert {"term": {"node_labels": "vault"}} in lbl["query"]["bool"]["should"]


def test_run_channels_msearch_and_error_channel(fake_client):
    bodies = {
        "bm25": search.bm25_body("Änderungshistorie", 5),
        "identifier": search.identifier_body(["ZSDSUP-0247"], 5),
    }
    fake_client.fail_channels.add("identifiers")
    res = search.run_channels(fake_client, "bhb-chunks", bodies)
    assert set(res) == {"bm25", "identifier"}
    assert res["bm25"].hits and res["bm25"].error is None and res["bm25"].took_ms == 1
    assert res["identifier"].hits == [] and "boom" in res["identifier"].error
    method, _, sent = fake_client.requests[0]
    assert method == "msearch" and sent[0] == {"index": "bhb-chunks"} and len(sent) == 4


def test_run_channels_empty():
    assert search.run_channels(None, "x", {}) == {}


def test_fetch_chunks_mget_excludes_embedding(fake_client):
    got = search.fetch_chunks(fake_client, "bhb-chunks", ["2bb722f565a0-0009", "missing"])
    assert set(got) == {"2bb722f565a0-0009"}
    assert "embedding" not in got["2bb722f565a0-0009"] and "text" in got["2bb722f565a0-0009"]
    assert search.fetch_chunks(fake_client, "bhb-chunks", []) == {}


def test_fetch_documents_with_and_without_graph(fake_client):
    docs = search.fetch_documents(fake_client, "bhb-documents", include_graph=False)
    assert [d["doc_id"] for d in docs] == ["BHB-PLT-0007"] and "graph" not in docs[0] and "markdown" not in docs[0]
    with_graph = search.fetch_documents(fake_client, "bhb-documents", include_graph=True)
    assert with_graph[0]["graph"]["edges"][0]["id"]


@pytest.mark.parametrize("fn", [search.knn_body, search.bm25_body])
def test_every_body_excludes_vectors(fn):
    arg = [0.0] * 8 if fn is search.knn_body else "x"
    assert "embedding" in _excludes(fn(arg, 3))
