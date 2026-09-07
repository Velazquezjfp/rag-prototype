from rag_retrieval.guardrail import decide
from rag_retrieval.models import ChannelEvidence, ChunkHit


def _hit(rank, *channels):
    return ChunkHit(chunk_id=f"c{rank}", doc_id="D", rank=rank, fused_score=1.0, group_key=f"c{rank}", channels=[ChannelEvidence(channel=c, rank=rank) for c in channels])


def test_disabled_never_weak():
    assert decide(enabled=False, hits=[], identifier_hits=0, label_nodes=0, bm25_returned=0).weak_evidence is False


def test_exact_channels_are_strong_evidence():
    assert decide(enabled=True, hits=[_hit(1, "knn")], identifier_hits=1, label_nodes=0, bm25_returned=0).weak_evidence is False
    assert decide(enabled=True, hits=[_hit(1, "knn")], identifier_hits=0, label_nodes=2, bm25_returned=0).weak_evidence is False


def test_no_hits_is_weak():
    v = decide(enabled=True, hits=[], identifier_hits=0, label_nodes=0, bm25_returned=0)
    assert v.weak_evidence and "no chunk" in v.reason


def test_bm25_empty_is_weak():
    v = decide(enabled=True, hits=[_hit(1, "knn"), _hit(2, "knn")], identifier_hits=0, label_nodes=0, bm25_returned=0)
    assert v.weak_evidence and "lexical" in v.reason


def test_single_channel_top_hits_are_weak_even_with_graph():
    hits = [_hit(1, "knn", "graph"), _hit(2, "bm25"), _hit(3, "knn"), _hit(4, "knn", "bm25")]
    v = decide(enabled=True, hits=hits, identifier_hits=0, label_nodes=0, bm25_returned=5, top_n=3)
    assert v.weak_evidence and "single channel" in v.reason and "graph" not in v.reason


def test_agreement_in_top_n_is_strong():
    hits = [_hit(1, "knn"), _hit(2, "knn", "bm25"), _hit(3, "bm25")]
    assert decide(enabled=True, hits=hits, identifier_hits=0, label_nodes=0, bm25_returned=5).weak_evidence is False
    assert decide(enabled=True, hits=hits, identifier_hits=0, label_nodes=0, bm25_returned=5, top_n=1).weak_evidence is True
