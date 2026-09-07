import pytest
from fake_search_client import FakeEmbedder

from rag_retrieval.embed import EmbeddingError
from rag_retrieval.retriever import Retriever, retrieve

CHUNK_TABLE1 = "2bb722f565a0-0009"  # Tabelle 1: Änderungshistorie (page 4)
CHUNK_TITLE = "2bb722f565a0-0000"


@pytest.fixture
def wired(settings, fake_client, graph_small, ontology, small_batch):
    vec = next(c["embedding"] for c in small_batch.chunks if c["chunk_id"] == CHUNK_TABLE1)
    embedder = FakeEmbedder(vec)
    r = Retriever(settings, client=fake_client, embedder=embedder, graph=graph_small, ontology=ontology, relation_labels={"RELATED_DOCUMENT": "verwandtes Dokument", "DOCUMENTS": "beschreibt"})
    return r, fake_client, embedder


def test_fast_mode_knn_and_bm25_agree_on_the_table(wired):
    r, client, embedder = wired
    res = r.retrieve("Änderungshistorie Version 2.3", use_graph=False)
    assert res.mode == "fast" and embedder.calls == ["Änderungshistorie Version 2.3"]
    assert res.chunks[0].chunk_id == CHUNK_TABLE1
    assert set(res.chunks[0].channel_names) >= {"knn", "bm25"}
    assert res.weak_evidence is False and res.facts == [] and res.entities == []
    assert [c.channel for c in res.diagnostics.channels] == ["knn", "bm25"]
    assert res.diagnostics.timings_ms.keys() >= {"analyze", "embed", "search", "fuse", "total"}
    assert "graph" not in res.diagnostics.timings_ms
    assert res.groups[0].cite == "BHB-PLT-0007 S. 4" and res.citations[0].key == "BHB-PLT-0007 S. 4"
    assert CHUNK_TABLE1 in res.citations[0].chunk_ids  # one citation per (doc, pages) collects all its chunks
    assert all(not hasattr(c, "embedding") for c in res.chunks)
    assert client.requests[0][0] == "msearch"


def test_identifier_and_label_channels(wired):
    r, _, _ = wired
    res = r.retrieve("Was war bei ZSDSUP-0247?", use_graph=False)
    chans = {c.channel: c for c in res.diagnostics.channels}
    assert chans["identifier"].query_terms == ["ZSDSUP-0247"] and chans["identifier"].returned >= 1
    assert "zsdsup-0247" in chans["label"].query_terms
    ident_hit = next(h for h in res.chunks if any(c.channel == "identifier" for c in h.channels))
    assert next(c.via for c in ident_hit.channels if c.channel == "identifier") == "ZSDSUP-0247"
    assert res.diagnostics.identifiers == ["ZSDSUP-0247"] and res.diagnostics.resolved_labels == ["ZSDSUP-0247"]


def test_slow_mode_adds_graph_channel_facts_and_entities(wired):
    r, client, _ = wired
    res = r.retrieve("Welche Dokumente sind mit BHB-PLT-0007 verwandt?", use_graph=True)
    assert res.mode == "slow" and res.facts, res.diagnostics
    assert res.diagnostics.identifiers == ["BHB-PLT-0007"] and res.diagnostics.resolved_labels == ["BHB-PLT-0007"]
    assert any(f.relation == "RELATED_DOCUMENT" and f.relation_de == "verwandtes Dokument" for f in res.facts)
    assert any(c.channel == "graph" for c in res.diagnostics.channels)
    assert any("graph" in h.channel_names for h in res.chunks)
    assert any(("mget", "bhb-chunks") == (m, i) for m, i, _ in client.requests)
    assert res.diagnostics.start_nodes and "graph" in res.diagnostics.timings_ms
    assert all(f.rendered.endswith("]") and f.chunk_ids for f in res.facts)
    cited_edges = {e for c in res.citations for e in c.edge_ids}
    assert cited_edges >= {f.edge_id for f in res.facts}


def test_best_fact_provenance_is_guaranteed_a_slot(wired):
    r, _, _ = wired
    res = r.retrieve("Welche Dokumente sind mit BHB-PLT-0007 verwandt?", use_graph=True, k=2)
    assert len(res.chunks) == 2 and res.facts
    graph_first = next(c for c in res.diagnostics.channels if c.channel == "graph")
    assert graph_first.returned >= 1
    top_fact_chunks = set(res.facts[0].chunk_ids)
    assert top_fact_chunks & {h.chunk_id for h in res.chunks}
    assert [h.rank for h in res.chunks] == [1, 2]
    r.settings.retrieval.graph_min_sources = 0
    assert len(r.retrieve("Welche Dokumente sind mit BHB-PLT-0007 verwandt?", use_graph=True, k=2).chunks) == 2


def test_doc_filter_reaches_every_body_and_graph(wired):
    r, client, _ = wired
    res = r.retrieve("Keycloak Vollausfall", use_graph=True, doc_ids=["OTHER-DOC"])
    assert res.chunks == [] and res.facts == []
    bodies = client.requests[0][2]
    knn = bodies[1]["query"]["knn"]["embedding"]
    assert knn["filter"] == {"terms": {"doc_id": ["OTHER-DOC"]}}
    assert bodies[3]["query"]["bool"]["filter"] == [{"terms": {"doc_id": ["OTHER-DOC"]}}]


def test_embedding_failure_degrades_to_lexical_channels(settings, fake_client, graph_small, ontology):
    r = Retriever(settings, client=fake_client, embedder=FakeEmbedder([0.0] * 8, fail=EmbeddingError("down")), graph=graph_small, ontology=ontology, relation_labels={})
    res = r.retrieve("Änderungshistorie", use_graph=False)
    assert [c.channel for c in res.diagnostics.channels] == ["bm25"]
    assert any(w.startswith("knn channel skipped") for w in res.diagnostics.warnings)
    assert res.chunks and res.chunks[0].chunk_id == CHUNK_TABLE1


def test_weak_evidence_skips_graph_expansion(wired):
    r, client, _ = wired
    res = r.retrieve("Apfelkuchen backen Rezept", use_graph=True)
    assert res.weak_evidence and "lexical" in res.weak_evidence_reason
    assert res.facts == [] and res.entities == []
    assert any("graph expansion skipped" in w for w in res.diagnostics.warnings)
    assert not any(m == "mget" for m, _, _ in client.requests)


def test_embedding_model_mismatch_is_a_warning_not_an_error(wired):
    r, _, _ = wired
    r.settings.embedding.model = "intfloat/multilingual-e5-large"
    r.settings.embedding.query_prefix = "query: "
    res = r.retrieve("Änderungshistorie", use_graph=False)
    assert any("differs from the indexed ['test-8d']" in w for w in res.diagnostics.warnings)
    assert any("query_prefix is set" in w for w in res.diagnostics.warnings)
    assert res.diagnostics.indexed_embedding_models == ["test-8d"] and res.diagnostics.embedding_model == "intfloat/multilingual-e5-large"


def test_k_override_and_channel_k(wired):
    r, client, _ = wired
    res = r.retrieve("Änderungshistorie", use_graph=False, k=2)
    assert len(res.chunks) == 2 and [h.rank for h in res.chunks] == [1, 2]
    assert client.requests[0][2][1]["size"] == r.settings.retrieval.k_per_channel


def test_reload_graph_and_module_level_retrieve(wired):
    r, _, _ = wired
    st = r.reload_graph()
    assert st.node_ids == 59 and r.graph.title("BHB-PLT-0007") == "Betriebshandbuch ZSD - Zentrale Sicherheitsdienste"
    res = retrieve("Änderungshistorie", use_graph=False, retriever=r)
    assert res.chunks[0].chunk_id == CHUNK_TABLE1
    assert res.chunks[0].doc_title == "Betriebshandbuch ZSD - Zentrale Sicherheitsdienste"


def test_check_report(wired, monkeypatch):
    from fake_search_client import FakeLLM

    import rag_retrieval.chat as chat_mod

    r, _, _ = wired
    monkeypatch.setattr(chat_mod, "ChatClient", lambda settings: FakeLLM())
    report = r.check()
    assert report["opensearch"]["aliases"] == {"bhb-chunks": True, "bhb-nodes": True, "bhb-documents": True}
    assert report["documents"][0]["doc_id"] == "BHB-PLT-0007" and report["documents"][0]["embedding_model"] == "test-8d"
    assert report["embedding"]["probe"]["ok"] and report["embedding"]["configured"]["api_key"] == "***"
    assert report["llm"]["probe"] == "ok" and report["graph"]["node_ids"] == 59 and report["ok"] is True


def test_check_fails_on_model_mismatch(wired, monkeypatch):
    from fake_search_client import FakeLLM

    import rag_retrieval.chat as chat_mod

    r, _, _ = wired
    monkeypatch.setattr(chat_mod, "ChatClient", lambda settings: FakeLLM())
    r.settings.embedding.model = "other"
    report = r.check()
    assert report["ok"] is False and report["embedding"]["warnings"]
