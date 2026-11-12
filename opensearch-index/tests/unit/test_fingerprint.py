import copy

from opensearch_index.identity import run_fingerprint
from opensearch_index.transform import compute_edge_ids

KW = {"ontology_fingerprint": "ont", "embedding_model": "m", "embedding_dim": 8, "mapping_version": 1}


def fp(resp, **over):
    kw = {**KW, **over}
    return run_fingerprint(resp, compute_edge_ids(resp.graph), **kw)


def test_deterministic(response_small):
    assert fp(response_small) == fp(copy.deepcopy(response_small))


def test_order_invariant(response_small):
    other = copy.deepcopy(response_small)
    other.chunks.reverse()
    other.graph.nodes.reverse()
    other.graph.edges.reverse()
    assert fp(other) == fp(response_small)


def test_float_noise_ignored_but_real_change_counts(response_small):
    noisy = copy.deepcopy(response_small)
    noisy.chunks[0].embedding[0] += 1e-6
    assert fp(noisy) == fp(response_small)
    changed = copy.deepcopy(response_small)
    changed.chunks[0].embedding[0] += 1e-2
    assert fp(changed) != fp(response_small)


def test_graph_and_text_changes_count(response_small):
    e = copy.deepcopy(response_small)
    e.graph.edges[0].quote = "anders"
    assert fp(e) != fp(response_small)
    n = copy.deepcopy(response_small)
    n.graph.nodes[0].label = "anders"
    assert fp(n) != fp(response_small)
    t = copy.deepcopy(response_small)
    t.chunks[3].text += " x"
    assert fp(t) != fp(response_small)


def test_timing_meta_ignored_but_schema_hash_counts(response_small):
    m = copy.deepcopy(response_small)
    m.graph.meta["materialize_s"] = 99.0
    assert fp(m) == fp(response_small)
    m.graph.meta["template_schema_hash"] = "ffff"
    assert fp(m) != fp(response_small)


def test_config_changes_count(response_small):
    base = fp(response_small)
    assert fp(response_small, embedding_model="other") != base
    assert fp(response_small, mapping_version=2) != base
    assert fp(response_small, ontology_fingerprint="x") != base
