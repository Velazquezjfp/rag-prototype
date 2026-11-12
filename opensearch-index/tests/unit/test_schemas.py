from opensearch_index.schemas import ProcessResponse


def test_fixture_validates(response_small):
    assert len(response_small.chunks) == 12
    assert response_small.graph is not None
    assert response_small.document.sha256.startswith("2bb722f565a0")
    assert response_small.chunks[0].chunk_id == "2bb722f565a0-0000"


def test_real_response_validates(real_response):
    assert len(real_response.chunks) == 112
    assert real_response.graph is not None
    assert len(real_response.graph.nodes) == 250
    assert len(real_response.graph.edges) == 154


def test_optional_parts_tolerated():
    resp = ProcessResponse.model_validate(
        {
            "document": {"name": "x.pdf", "format": "pdf", "sha256": "ab" * 32, "pages": 1, "tables": 0, "pictures": 0},
            "markdown": "",
            "chunks": [{"chunk_id": "abababababab-0000", "text": "t", "body_text": "t", "embedding": None}],
            "graph": None,
            "timings_s": {"convert": 1.0},
        }
    )
    assert resp.graph is None
    assert resp.chunks[0].embedding is None
    assert resp.degraded.graph is False


def test_unknown_fields_survive():
    resp = ProcessResponse.model_validate(
        {
            "document": {"name": "x.pdf", "sha256": "ab" * 32},
            "chunks": [],
            "graph": {"nodes": [], "edges": [{"source": "a", "target": "b", "type": "T", "future": 1}], "meta": {}},
        }
    )
    assert resp.graph.edges[0].model_dump()["future"] == 1
