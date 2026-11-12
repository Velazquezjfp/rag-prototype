# Architecture Decision Records

All decisions agreed 2026-08-26 from the design interview. Each records the alternative that
was rejected, because these are the decisions most likely to be re-litigated later.

| ADR | Decision |
|---|---|
| [0001](0001-real-typed-edges.md) | Graph has real typed edges from mandated sections; no synthetic root |
| [0002](0002-normative-bespoke-ontology.md) | Ontology stays bespoke and normative; OWL is generated; LinkML rejected |
| [0003](0003-deterministic-entity-resolution.md) | Entity resolution from ontology identity keys; no LLM canonicalization |
| [0004](0004-no-agent-framework.md) | Retrieval is a pure function with fast/slow modes; no agent framework |
| [0005](0005-no-graph-database.md) | In-memory NetworkX persisted in OpenSearch; no graph database |
| [0006](0006-rrf-over-reranker.md) | Reciprocal Rank Fusion; cross-encoder reranker deferred |
| [0007](0007-postgres-not-sqlite.md) | Postgres + SQLAlchemy from day one |
| [0008](0008-auth-at-ingress.md) | oauth2-proxy at ingress behind a single AuthContext seam |
| [0009](0009-multilingual-e5-large.md) | multilingual-e5-large; its 512-token cap drives chunking |
| [0010](0010-figures-confirm-never-create.md) | Figures may confirm edges, never create them |
| [0011](0011-no-compaction.md) | No compaction; hard turn cap plus query rewriting |
| [0012](0012-split-evaluation.md) | Split evaluation: deterministic metrics on target, Claude judge externally |
| [0013](0013-dual-corpus-honesty.md) | Coverage measured against deliberately degraded input (amended) |
| [0014](0014-local-dev-topology.md) | Local dev runs a small stand-in; GPU workloads sequenced, not concurrent |
