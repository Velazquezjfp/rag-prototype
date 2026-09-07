from rag_retrieval.fusion import FusedHit, RawHit, group_hits, group_key_of, rrf, to_chunk_hits
from rag_retrieval.models import ChannelEvidence, ChunkHit


def _raw(cid, score=1.0, **src):
    return RawHit(chunk_id=cid, score=score, source={"chunk_id": cid, "doc_id": "D", **src})


def test_rrf_math_and_channel_union():
    lists = {"knn": [_raw("a"), _raw("b"), _raw("c")], "bm25": [_raw("b"), _raw("a")]}
    fused = rrf(lists, rank_constant=60)
    by_id = {f.chunk_id: f for f in fused}
    assert abs(by_id["a"].fused_score - (1 / 61 + 1 / 62)) < 1e-12
    assert abs(by_id["b"].fused_score - (1 / 62 + 1 / 61)) < 1e-12
    assert abs(by_id["c"].fused_score - 1 / 63) < 1e-12
    assert {c.channel for c in by_id["a"].channels} == {"knn", "bm25"}
    assert [f.chunk_id for f in fused][2] == "c"


def test_rrf_tie_breaks_more_channels_then_best_rank_then_id():
    # a: knn#1 only (1/61); b: bm25#1 only (1/61) -> tie on score and channel count -> best rank tie -> id
    fused = rrf({"knn": [_raw("b")], "bm25": [_raw("a")]})
    assert [f.chunk_id for f in fused] == ["a", "b"]
    # two channels beat one at equal score: x knn#1+bm25#3 vs y with an artificial single-list equal score
    fused = rrf({"knn": [_raw("x"), _raw("z")], "bm25": [_raw("q"), _raw("w"), _raw("x")]}, rank_constant=60)
    assert fused[0].chunk_id == "x" and len(fused[0].channels) == 2


def test_rrf_duplicates_within_a_list_count_once():
    fused = rrf({"knn": [_raw("a"), _raw("a"), _raw("b")]})
    assert [(f.chunk_id, f.channels[0].rank) for f in fused] == [("a", 1), ("b", 2)]


def test_rrf_keeps_the_richer_source_and_via():
    lists = {
        "identifier": [RawHit("a", 1.0, {"chunk_id": "a", "doc_id": "D", "text": "t"}, via="ZSDSUP-0247")],
        "knn": [RawHit("a", 0.9, {"chunk_id": "a"})],
    }
    f = rrf(lists)[0]
    assert f.source["text"] == "t"
    assert {c.channel: c.via for c in f.channels} == {"identifier": "ZSDSUP-0247", "knn": None}


def test_group_key_only_for_captioned_tables():
    assert group_key_of({"chunk_id": "c1", "doc_id": "D", "kind": "table", "caption": "Tabelle 4: X "}) == "D|table|Tabelle 4: X"
    assert group_key_of({"chunk_id": "c1", "doc_id": "D", "kind": "table", "caption": None}) == "c1"
    assert group_key_of({"chunk_id": "c1", "doc_id": "D", "kind": "text", "caption": "x"}) == "c1"


def test_to_chunk_hits_assigns_rank_title_and_limit():
    fused = [
        FusedHit("a", 0.5, [ChannelEvidence(channel="knn", rank=1)], {"chunk_id": "a", "doc_id": "D", "page_numbers": [8, 9], "token_count": 12}),
        FusedHit("b", 0.4, [ChannelEvidence(channel="bm25", rank=1)], {"chunk_id": "b", "doc_id": "D"}),
        FusedHit("c", 0.3, [], {}),
    ]
    hits = to_chunk_hits(fused, titles={"D": "Titel"}, limit=2)
    assert [h.chunk_id for h in hits] == ["a", "b"] and hits[0].rank == 1 and hits[1].rank == 2
    assert hits[0].doc_title == "Titel" and hits[0].cite == "D S. 8–9" and hits[0].channel_names == ["knn"]
    assert to_chunk_hits(fused)[-1].chunk_id == "b"  # the empty-source hit is skipped


def _hit(cid, rank, pages, caption=None, kind="text", score=0.1, tokens=10):
    return ChunkHit(
        chunk_id=cid, doc_id="BHB-PLT-0007", kind=kind, page_numbers=pages, caption=caption, token_count=tokens,
        rank=rank, fused_score=score, channels=[ChannelEvidence(channel="knn", rank=rank)],
        group_key=f"BHB-PLT-0007|table|{caption}" if caption and kind == "table" else cid,
    )


def test_group_hits_merges_table_parts_and_renumbers():
    hits = [
        _hit("x-0031", 1, [9], "Tabelle 5: Portmatrix", "table", 0.3),
        _hit("x-0010", 2, [4], None, "text", 0.2),
        _hit("x-0030", 3, [8, 9], "Tabelle 5: Portmatrix", "table", 0.1),
        _hit("x-0032", 5, [10], "Tabelle 5: Portmatrix", "table", 0.05),
    ]
    groups = group_hits(hits)
    assert [g.rank for g in groups] == [1, 2]
    table = groups[0]
    assert table.chunk_ids == ["x-0030", "x-0031", "x-0032"]  # document order inside the group
    assert table.pages == [8, 9, 10] and table.cite == "BHB-PLT-0007 S. 8–10"
    assert table.fused_score == 0.3 and table.token_count == 30 and table.channel_names == ["knn"]
    assert groups[1].chunk_ids == ["x-0010"]


def test_group_hits_on_fixture_batch(small_batch):
    """Two captioned tables in the fixture stay separate groups; every chunk lands in exactly one group."""
    from rag_retrieval.fusion import to_chunk_hits

    fused = [FusedHit(c["chunk_id"], 1.0 / (i + 1), [ChannelEvidence(channel="bm25", rank=i + 1)], c) for i, c in enumerate(small_batch.chunks)]
    groups = group_hits(to_chunk_hits(fused))
    assert sum(len(g.chunk_ids) for g in groups) == len(small_batch.chunks)
    captions = {g.caption for g in groups if g.kind == "table" and g.caption}
    assert captions == {"Tabelle 1: Änderungshistorie", "Tabelle 2: Verwandte Dokumente und Berührungspunkt"}
