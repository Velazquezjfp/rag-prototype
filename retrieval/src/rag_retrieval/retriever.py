"""``Retriever``: question → analysis → embedding → four channels in one msearch → RRF → (slow mode) 1-hop graph
expansion with facts, entity cards and provenance chunks as the fifth list → groups, citations, guardrail verdict.

Holds no per-request state: one instance serves many Streamlit sessions; ``reload_graph()`` swaps the in-memory
graph under a lock after a new manual was indexed (ADR-0005)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Collection, Mapping, Sequence
from functools import lru_cache
from typing import Any

from opensearch_index.client import make_client
from opensearch_index.mappings import IndexNames
from opensearch_index.ontology import Ontology, load_ontology

from . import facts as facts_mod
from . import search
from .embed import EmbeddingError, QuestionEmbedder
from .fusion import RawHit, group_hits, rrf, to_chunk_hits
from .graph import GraphStats, GraphStore
from .guardrail import decide
from .llm_http import LLMHTTPError
from .models import (
    Channel,
    ChannelStats,
    ChunkGroup,
    ChunkHit,
    Citation,
    Diagnostics,
    GraphFact,
    RetrievalResult,
    format_pages,
)
from .query import QueryPlan, analyze_question
from .settings import Settings, get_settings, redact_url

log = logging.getLogger(__name__)


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


class Retriever:
    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        embedder: QuestionEmbedder | None = None,
        graph: GraphStore | None = None,
        ontology: Ontology | None = None,
        relation_labels: Mapping[str, str] | None = None,
    ):
        self.settings = settings
        self.names = IndexNames(settings.index.prefix)
        self.client = client if client is not None else make_client(settings.opensearch)
        self.ontology = ontology if ontology is not None else load_ontology(settings.ontology.path)
        self.relation_labels: dict[str, str] = (
            dict(relation_labels)
            if relation_labels is not None
            else facts_mod.load_relation_labels(settings.ontology.path)
        )
        self.embedder = embedder if embedder is not None else QuestionEmbedder.from_settings(settings.embedding)
        self._lock = threading.Lock()
        self._graph = graph if graph is not None else self._load_graph()

    # ------------------------------------------------------------------ graph

    def _load_graph(self) -> GraphStore:
        docs = search.fetch_documents(self.client, self.names.documents, include_graph=True)
        store = GraphStore.from_documents(docs)
        st = store.stats()
        log.info("graph loaded: %s documents, %s node ids, %s edges", len(st.documents), st.node_ids, st.edge_ids)
        return store

    @property
    def graph(self) -> GraphStore:
        with self._lock:
            return self._graph

    def reload_graph(self) -> GraphStats:
        store = self._load_graph()
        with self._lock:
            self._graph = store
        return store.stats()

    # ------------------------------------------------------------------ retrieval

    def retrieve(
        self,
        question: str,
        *,
        use_graph: bool = True,
        k: int | None = None,
        doc_ids: Collection[str] | None = None,
    ) -> RetrievalResult:
        s = self.settings.retrieval
        graph = self.graph
        final_k = k or s.final_k
        k_channel = max(s.k_per_channel, final_k)
        timings: dict[str, int] = {}
        warnings: list[str] = []
        t_total = time.perf_counter()

        # 1. analyze (no I/O)
        t0 = time.perf_counter()
        plan = analyze_question(
            question,
            regexes=self.ontology.regexes,
            graph=graph,
            max_ngram=s.label_max_ngram,
            min_chars=s.label_min_chars,
            partial_min_tokens=s.partial_label_min_tokens,
            partial_max_nodes=s.partial_label_max_nodes,
        )
        label_nodes = plan.start_nodes  # exact label/alias matches: the guardrail's evidence
        timings["analyze"] = _ms(t0)

        # 2. embed
        t0 = time.perf_counter()
        vector: list[float] | None = None
        try:
            vector = self.embedder.embed(question)
        except (EmbeddingError, LLMHTTPError) as exc:
            warnings.append(f"knn channel skipped: {str(exc)[:200]}")
            log.warning("embedding failed, continuing without kNN: %s", exc)
        timings["embed"] = _ms(t0)
        self._check_embedding_model(graph, warnings)

        # 3. channels
        t0 = time.perf_counter()
        bodies: dict[Channel, dict[str, Any]] = {}
        if vector is not None:
            bodies["knn"] = search.knn_body(vector, k_channel, doc_ids)
        bodies["bm25"] = search.bm25_body(question, k_channel, doc_ids)
        if plan.identifiers:
            bodies["identifier"] = search.identifier_body(plan.identifiers, k_channel, doc_ids)
        if plan.label_terms:
            bodies["label"] = search.label_body(plan.label_terms, k_channel, doc_ids)
        responses = search.run_channels(self.client, self.names.chunks, bodies)
        timings["search"] = _ms(t0)

        lists: dict[str, list[RawHit]] = {}
        stats: list[ChannelStats] = []
        id_set = set(plan.identifiers)
        term_set = set(plan.label_terms)
        for ch, resp in responses.items():
            if resp.error:
                warnings.append(f"channel {ch} failed: {resp.error}")
            raw: list[RawHit] = []
            for h in resp.hits:
                src = h.get("_source") or {}
                via = None
                if ch == "identifier":
                    via = ", ".join(sorted(id_set & set(src.get("identifiers") or []))) or None
                elif ch == "label":
                    via = ", ".join(sorted(term_set & {lbl.lower() for lbl in src.get("node_labels") or []})) or None
                raw.append(RawHit(chunk_id=h["_id"], score=h.get("_score"), source=src, via=via))
            lists[ch] = raw
            stats.append(
                ChannelStats(
                    channel=ch,
                    requested_k=k_channel,
                    returned=len(raw),
                    took_ms=resp.took_ms,
                    query_terms=plan.identifiers if ch == "identifier" else plan.label_terms if ch == "label" else [],
                )
            )

        # 4. fuse the search channels; the guardrail judges these (the graph channel is seeded from them)
        t0 = time.perf_counter()
        fused = rrf(lists, rank_constant=s.rrf_rank_constant)
        titles = graph.titles
        hits = to_chunk_hits(fused, titles=titles)
        timings["fuse"] = _ms(t0)
        verdict = decide(
            enabled=self.settings.guardrail.enabled,
            hits=hits[:final_k],
            identifier_hits=len(lists.get("identifier", [])),
            label_nodes=len(label_nodes),
            bm25_returned=len(lists.get("bm25", [])),
            top_n=self.settings.guardrail.top_n,
            min_agreeing_channels=self.settings.guardrail.min_agreeing_channels,
        )

        # 5. graph channel
        facts: list[GraphFact] = []
        entities = []
        start_nodes: list[str] = []
        if use_graph and verdict.weak_evidence:
            warnings.append(f"graph expansion skipped: weak evidence ({verdict.reason})")
        elif use_graph:
            t0 = time.perf_counter()
            seed_ids: list[str] = [h.chunk_id for h in hits[: s.graph_seed_hits]]
            for ch in ("knn", "bm25", "identifier", "label"):
                for raw in lists.get(ch, [])[: s.graph_seed_per_channel]:
                    if raw.chunk_id not in seed_ids:
                        seed_ids.append(raw.chunk_id)
            by_id = {h.chunk_id: h for h in hits}
            seed_hits = [by_id[c] for c in seed_ids if c in by_id]
            boost_types = facts_mod.type_boost(question)
            start_nodes = facts_mod.select_start_nodes(
                graph,
                label_nodes=label_nodes,
                seed_hits=seed_hits,
                max_nodes=s.graph_max_start_nodes,
                partial_nodes=plan.partial_nodes,
                question_keys=plan.question_keys,
                boost_types=boost_types,
            )
            expanded = graph.expand(start_nodes, doc_ids=doc_ids)
            facts = facts_mod.build_facts(
                graph,
                expanded,
                start_nodes=start_nodes,
                label_nodes=[*label_nodes, *plan.partial_nodes],
                relation_labels=self.relation_labels,
                max_facts=s.graph_max_facts,
                boost=facts_mod.relation_boost(question),
            )
            reached: list[str] = []
            for f in facts:
                for nid in (f.source_id, f.target_id):
                    if nid not in start_nodes and nid not in reached:
                        reached.append(nid)
            matched_by: dict[str, Any] = {}
            id_keys = {i.lower() for i in plan.identifiers}
            partial_set = set(plan.partial_nodes)
            for nid in start_nodes:
                if nid in label_nodes:
                    forms = {f.lower() for f in graph.label_forms_of(nid)}
                    matched_by[nid] = "identifier" if forms & id_keys else "label"
                elif nid in partial_set:
                    matched_by[nid] = "label"
                else:
                    matched_by[nid] = "hit"
            entities = facts_mod.build_entity_cards(
                graph,
                [*start_nodes, *reached],
                matched_by=matched_by,
                doc_ids=doc_ids,
                max_entities=s.graph_max_entities,
                boost_types=boost_types,
            )
            graph_chunk_ids = facts_mod.graph_chunk_ids(
                facts, graph, label_nodes=label_nodes, neighbours=reached, limit=s.graph_max_chunks
            )
            fetched = search.fetch_chunks(self.client, self.names.chunks, graph_chunk_ids) if graph_chunk_ids else {}
            if doc_ids:
                fetched = {cid: src for cid, src in fetched.items() if src.get("doc_id") in set(doc_ids)}
            fact_by_chunk: dict[str, GraphFact] = {}
            for f in facts:
                for cid in f.chunk_ids:
                    fact_by_chunk.setdefault(cid, f)
            graph_raw: list[RawHit] = []
            for cid in graph_chunk_ids:
                src = fetched.get(cid)
                if not src:
                    continue
                f = fact_by_chunk.get(cid)
                via = f"{f.relation} from {f.via_start_node}" if f and f.via_start_node else ("node provenance" if not f else f.relation)
                graph_raw.append(RawHit(chunk_id=cid, score=None, source=src, via=via))
            lists["graph"] = graph_raw
            stats.append(
                ChannelStats(
                    channel="graph",
                    requested_k=s.graph_max_chunks,
                    returned=len(graph_raw),
                    query_terms=[graph.label(n) for n in start_nodes[:10]],
                )
            )
            fused = rrf(lists, rank_constant=s.rrf_rank_constant)
            hits = to_chunk_hits(fused, titles=titles)
            hits = _guarantee_graph_sources(hits, [r.chunk_id for r in graph_raw[: s.graph_min_sources]], final_k)
            timings["graph"] = _ms(t0)

        # 6. cut, group, cite
        hits = hits[:final_k]
        for i, h in enumerate(hits, start=1):
            h.rank = i
        groups = group_hits(hits)
        citations = _citations(groups, facts, titles)

        timings["total"] = _ms(t_total)

        info = list(graph.documents.values())
        diagnostics = Diagnostics(
            question=question,
            mode="slow" if use_graph else "fast",
            identifiers=plan.identifiers,
            label_candidates=plan.label_candidates,
            resolved_labels=[_forms(graph.label_forms(k)) for k in plan.label_candidates],
            partial_labels=[f"{graph.label(n)} ({graph.type_of(n)})" for n in plan.partial_nodes],
            start_nodes=[f"{graph.label(n)} ({graph.type_of(n)})" for n in start_nodes],
            channels=stats,
            timings_ms=timings,
            embedding_model=self.settings.embedding.model,
            indexed_embedding_models=sorted({d.embedding_model for d in info if d.embedding_model}),
            indexed_text_prefix=next((d.embedding_text_prefix for d in info if d.embedding_text_prefix is not None), None),
            warnings=warnings,
        )
        return RetrievalResult(
            question=question,
            mode="slow" if use_graph else "fast",
            chunks=hits,
            groups=groups,
            facts=facts,
            entities=entities,
            citations=citations,
            weak_evidence=verdict.weak_evidence,
            weak_evidence_reason=verdict.reason,
            diagnostics=diagnostics,
        )

    def _check_embedding_model(self, graph: GraphStore, warnings: list[str]) -> None:
        indexed = {d.embedding_model for d in graph.documents.values() if d.embedding_model}
        if indexed and self.settings.embedding.model not in indexed:
            warnings.append(
                f"query embedding model {self.settings.embedding.model!r} differs from the indexed {sorted(indexed)}"
            )
        prefixes = {d.embedding_text_prefix or "" for d in graph.documents.values()}
        if prefixes == {""} and self.settings.embedding.query_prefix:
            warnings.append("query_prefix is set but the chunks were embedded without a prefix")
        if "passage: " in prefixes and not self.settings.embedding.query_prefix:
            warnings.append('chunks were embedded with "passage: " but query_prefix is empty (e5 wants "query: ")')

    # ------------------------------------------------------------------ health

    def check(self) -> dict[str, Any]:
        """Aliases present, documents and their embedding model vs the configured one, embedding probe, LLM probe."""
        out: dict[str, Any] = {"opensearch": {"url": self.settings.opensearch.url, "aliases": {}}}
        ok = True
        for alias in (self.names.chunks, self.names.nodes, self.names.documents):
            try:
                present = bool(self.client.indices.exists_alias(name=alias))
            except Exception as exc:  # noqa: BLE001 - reported
                present = False
                out["opensearch"]["error"] = str(exc)[:200]
            out["opensearch"]["aliases"][alias] = present
            ok &= present
        graph = self.graph
        out["documents"] = [
            {
                "doc_id": d.doc_id,
                "title": d.title,
                "embedding_model": d.embedding_model,
                "embedding_text_prefix": d.embedding_text_prefix,
                "counts": dict(d.counts),
            }
            for d in graph.documents.values()
        ]
        if not out["documents"]:
            ok = False
        warnings: list[str] = []
        self._check_embedding_model(graph, warnings)
        probe = self.embedder.probe()
        out["embedding"] = {
            "configured": {
                **redact_url(self.settings.embedding.base_url, self.settings.embedding.api_key),
                "model": self.settings.embedding.model,
                "dim": self.settings.embedding.dim,
                "query_prefix": self.settings.embedding.query_prefix,
            },
            "probe": probe,
            "warnings": warnings,
        }
        ok &= bool(probe.get("ok")) and not warnings
        from .chat import ChatClient

        llm = ChatClient(self.settings.llm)
        try:
            llm_probe = llm.probe()
        finally:
            llm.close()
        out["llm"] = {
            **redact_url(self.settings.llm.base_url, self.settings.llm.api_key),
            "model": self.settings.llm.model,
            "probe": llm_probe,
        }
        ok &= llm_probe == "ok"
        out["graph"] = graph.stats().as_dict()
        out["ok"] = bool(ok)
        return out


def _guarantee_graph_sources(hits: list[ChunkHit], must_have: Sequence[str], final_k: int) -> list[ChunkHit]:
    """The provenance chunks of the best facts always make the final list: a graph-only hit scores 1/(k+1) in RRF
    and would lose against every chunk two search channels agree on. Promoted chunks replace the tail."""
    head_ids = {h.chunk_id for h in hits[:final_k]}
    missing = [cid for cid in must_have if cid not in head_ids]
    if not missing:
        return hits
    promoted = [h for h in hits if h.chunk_id in missing]
    keep = hits[: max(0, final_k - len(promoted))]
    rest = [h for h in hits if h not in keep and h not in promoted]
    return keep + promoted + rest


def _forms(forms: Collection[str]) -> str:
    """Spellings of one label key, case-insensitively deduplicated (``Keycloak`` and ``keycloak`` -> one)."""
    seen: dict[str, str] = {}
    for f in sorted(forms):
        seen.setdefault(f.lower(), f)
    return ", ".join(seen.values())


def _citations(groups: Sequence[ChunkGroup], facts: Sequence[GraphFact], titles: Mapping[str, str]) -> list[Citation]:
    by_key: dict[str, Citation] = {}

    def add(doc_id: str, pages: Sequence[int], *, chunk_ids: Sequence[str] = (), edge_ids: Sequence[str] = ()) -> None:
        key = f"{doc_id} S. {format_pages(pages)}"
        c = by_key.get(key)
        if c is None:
            c = by_key[key] = Citation(key=key, doc_id=doc_id, doc_title=titles.get(doc_id), pages=sorted(set(pages)))
        for cid in chunk_ids:
            if cid not in c.chunk_ids:
                c.chunk_ids.append(cid)
        for eid in edge_ids:
            if eid not in c.edge_ids:
                c.edge_ids.append(eid)

    for g in groups:
        add(g.doc_id, g.pages, chunk_ids=g.chunk_ids)
    for f in facts:
        for doc_id in f.doc_ids:
            add(doc_id, f.pages, chunk_ids=f.chunk_ids, edge_ids=[f.edge_id])
    return list(by_key.values())


@lru_cache(maxsize=1)
def default_retriever() -> Retriever:
    return Retriever(get_settings())


def retrieve(
    question: str,
    *,
    use_graph: bool = True,
    k: int | None = None,
    doc_ids: Collection[str] | None = None,
    retriever: Retriever | None = None,
) -> RetrievalResult:
    """SPEC §7.1 entry point over a process-wide default ``Retriever`` (settings from env/.env/config.yaml)."""
    r = retriever if retriever is not None else default_retriever()
    return r.retrieve(question, use_graph=use_graph, k=k, doc_ids=doc_ids)


__all__ = ["QueryPlan", "Retriever", "ChunkHit", "default_retriever", "retrieve"]
