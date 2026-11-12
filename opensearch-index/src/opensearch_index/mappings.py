"""Index names, settings and mappings (v1). A mapping change = bump ``MAPPING_VERSION``, create ``-v2``, reindex,
swap the alias; callers only ever use the alias names."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .settings import EmbeddingSettings, IndexSettings

MAPPING_VERSION = 1
KNN_ENGINE = "lucene"  # explicit: the default engine is faiss (2.19+/3.x); lucene = filter-during-search, no native memory
SPACE_TYPE = "cosinesimil"  # vectors are unit-norm; zero vectors are rejected before indexing

SCOPE_DOCUMENT = "document"  # per-document records (this module); "corpus" is reserved for the merge module


@dataclass(frozen=True)
class IndexNames:
    prefix: str

    @property
    def chunks(self) -> str:
        return f"{self.prefix}-chunks"

    @property
    def nodes(self) -> str:
        return f"{self.prefix}-nodes"

    @property
    def documents(self) -> str:
        return f"{self.prefix}-documents"

    @property
    def manifest(self) -> str:
        return f"{self.prefix}-manifest"

    @property
    def rrf_pipeline(self) -> str:
        return f"{self.prefix}-rrf"

    @property
    def aliases(self) -> list[str]:
        return [self.chunks, self.nodes, self.documents, self.manifest]

    @staticmethod
    def physical(alias: str, version: int = MAPPING_VERSION) -> str:
        return f"{alias}-v{version}"

    def verify_index(self, token: str) -> str:
        return f"{self.prefix}-verify-{token}"


def analysis_settings() -> dict[str, Any]:
    """German text analysis: light stemmer (technical German over-stems with the full ``german`` stemmer),
    umlaut normalization, stopwords; ``lc`` normalizer for case-robust keyword matching."""
    return {
        "filter": {
            "de_stop": {"type": "stop", "stopwords": "_german_"},
            "de_stem": {"type": "stemmer", "language": "light_german"},
        },
        "normalizer": {"lc": {"type": "custom", "filter": ["lowercase", "trim"]}},
        "analyzer": {
            "de_text": {
                "type": "custom",
                "tokenizer": "standard",
                "filter": ["lowercase", "de_stop", "german_normalization", "de_stem"],
            }
        },
    }


def index_settings(s: IndexSettings, *, knn: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {
        "index": {"number_of_shards": s.shards, "number_of_replicas": s.replicas},
        "analysis": analysis_settings(),
    }
    if knn:
        body["index"]["knn"] = True
    return body


def _kw() -> dict[str, Any]:
    return {"type": "keyword"}


def _text() -> dict[str, Any]:
    return {"type": "text", "analyzer": "de_text"}


def _text_kw(normalizer: str | None = None) -> dict[str, Any]:
    kw: dict[str, Any] = {"type": "keyword"}
    if normalizer:
        kw["normalizer"] = normalizer
    return {"type": "text", "analyzer": "de_text", "fields": {"keyword": kw}}


def _name_kw() -> dict[str, Any]:
    """Names (labels, aliases): standard analyzer (no stemming of person/system names) + normalized keyword."""
    return {"type": "text", "analyzer": "standard", "fields": {"keyword": {"type": "keyword", "normalizer": "lc"}}}


def _common(extra: dict[str, Any]) -> dict[str, Any]:
    return {"doc_id": _kw(), "doc_sha256": _kw(), "run_id": _kw(), "indexed_at": {"type": "date"}, **extra}


def chunks_mapping(emb: EmbeddingSettings, s: IndexSettings) -> dict[str, Any]:
    return {
        "_meta": {
            "mapping_version": MAPPING_VERSION,
            "embedding_dim": emb.dim,
            "embedding_model": emb.model,
            "knn_engine": KNN_ENGINE,
            "space_type": SPACE_TYPE,
        },
        "dynamic": "strict",
        "properties": _common(
            {
                "chunk_id": _kw(),
                "text": _text(),
                "body_text": _text(),
                "heading_breadcrumb": _text_kw(),
                "heading_level": {"type": "integer"},
                "kind": _kw(),
                "caption": _text_kw(),
                "page_numbers": {"type": "integer"},
                "dom_paths": {"type": "keyword", "index": False},
                "bboxes": {"type": "object", "enabled": False},
                "token_count": {"type": "integer"},
                "identifiers": _kw(),
                "node_ids": _kw(),
                "node_labels": {"type": "keyword", "normalizer": "lc"},
                "node_types": _kw(),
                "edge_ids": _kw(),
                "embedding": {
                    "type": "knn_vector",
                    "dimension": emb.dim,
                    "space_type": SPACE_TYPE,
                    "method": {
                        "name": "hnsw",
                        "engine": KNN_ENGINE,
                        "parameters": {"m": s.knn_m, "ef_construction": s.knn_ef_construction},
                    },
                },
                "embedding_model": _kw(),
            }
        ),
    }


def nodes_mapping() -> dict[str, Any]:
    return {
        "_meta": {"mapping_version": MAPPING_VERSION},
        "dynamic": "strict",
        "properties": _common(
            {
                "node_id": _kw(),
                "scope": _kw(),
                "type": _kw(),
                "label": _name_kw(),
                "aliases": _name_kw(),
                "identity": _kw(),
                "identity_norm": _kw(),
                "attributes": {"type": "flat_object"},
                "attributes_text": _text(),
                "quote": _text(),
                "identifiers": _kw(),
                "chunk_ids": _kw(),
                "pages": {"type": "integer"},
                "match": _kw(),
                "degree": {"type": "integer"},
                "provenance": {"type": "object", "enabled": False},
            }
        ),
    }


def documents_mapping() -> dict[str, Any]:
    return {
        "_meta": {"mapping_version": MAPPING_VERSION},
        "dynamic": "strict",
        "properties": _common(
            {
                "doc_id_source": _kw(),
                "scope": _kw(),
                "name": _kw(),
                "format": _kw(),
                "pages": {"type": "integer"},
                "tables": {"type": "integer"},
                "pictures": {"type": "integer"},
                "title": _text_kw(),
                "version": _kw(),
                "valid_from": _kw(),  # arrives unparsed ("22. Juli 2026", "04/2026")
                "classification": _kw(),
                "ci_id": _kw(),
                "root_system": _kw(),
                "related_doc_ids": _kw(),
                "markdown": {"type": "text", "index": False},
                "graph": {"type": "object", "enabled": False},  # node-link JSON incl. meta; edges carry "id"
                "degraded": {
                    "properties": {
                        "vlm": {"type": "boolean"},
                        "embeddings": {"type": "boolean"},
                        "graph": {"type": "boolean"},
                    }
                },
                "errors": {"type": "keyword", "index": False, "doc_values": False},
                "warnings": {"type": "keyword", "index": False, "doc_values": False},
                "timings_s": {"type": "object", "enabled": False},
                "versions": {"type": "object", "enabled": False},
                "counts": _counts(),
                "embedding_model": _kw(),
                "embedding_dim": {"type": "integer"},
                "embedding_text_prefix": {"type": "keyword", "index": False},
            }
        ),
    }


def _counts() -> dict[str, Any]:
    return {
        "properties": {
            "chunks": {"type": "integer"},
            "nodes": {"type": "integer"},
            "edges": {"type": "integer"},
            "documents": {"type": "integer"},
        }
    }


def manifest_mapping() -> dict[str, Any]:
    return {
        "_meta": {"mapping_version": MAPPING_VERSION},
        "dynamic": "strict",
        "properties": {
            "doc_id": _kw(),
            "status": _kw(),  # indexing | active | failed
            "run_id": _kw(),
            "previous_run_id": _kw(),
            "doc_sha256": _kw(),
            "doc_name": _kw(),
            "doc_id_source": _kw(),
            "owner": _kw(),
            "started_at": {"type": "date"},
            "finished_at": {"type": "date"},
            "counts": _counts(),
            "swept": _counts(),
            "embedding_model": _kw(),
            "mapping_version": {"type": "integer"},
            "indexer_version": _kw(),
            "error": {"type": "keyword", "index": False, "doc_values": False},
            "history": {"type": "object", "enabled": False},
        },
    }


def index_bodies(names: IndexNames, emb: EmbeddingSettings, s: IndexSettings) -> dict[str, dict[str, Any]]:
    """alias -> create-index body (settings, mappings, alias)."""
    return {
        names.chunks: {
            "settings": index_settings(s, knn=True),
            "mappings": chunks_mapping(emb, s),
            "aliases": {names.chunks: {}},
        },
        names.nodes: {"settings": index_settings(s), "mappings": nodes_mapping(), "aliases": {names.nodes: {}}},
        names.documents: {
            "settings": index_settings(s),
            "mappings": documents_mapping(),
            "aliases": {names.documents: {}},
        },
        names.manifest: {
            "settings": index_settings(s),
            "mappings": manifest_mapping(),
            "aliases": {names.manifest: {}},
        },
    }


def sweep_query(doc_id: str, keep_run_id: str) -> dict[str, Any]:
    """Everything of this document that does not belong to the run being finalized."""
    return {
        "query": {
            "bool": {
                "filter": [{"term": {"doc_id": doc_id}}],
                "must_not": [{"term": {"run_id": keep_run_id}}],
            }
        }
    }


def rrf_pipeline_body(rank_constant: int = 60) -> dict[str, Any]:
    return {
        "description": "Reciprocal rank fusion for the four-clause hybrid query (SPEC §7.2/7.5)",
        "phase_results_processors": [
            {"score-ranker-processor": {"combination": {"technique": "rrf", "rank_constant": rank_constant}}}
        ],
    }
