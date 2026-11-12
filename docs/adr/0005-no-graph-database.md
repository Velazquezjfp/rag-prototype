# ADR-0005: In-memory NetworkX persisted in OpenSearch; no graph database

## Context
docling-graph emits a NetworkX `DiGraph`, an in-process object rather than a database. The plan
mentioned storing the graph as JSONB, which is Postgres terminology, in OpenSearch.

## Decision
Serialize the merged graph to node-link JSON, store it as one OpenSearch document, load it into
memory at app startup, traverse with NetworkX. Each node carries the list of chunk IDs that
mention it, so graph-to-chunks is a dictionary lookup.

## Rationale
Five documents now, ~30 later, on the order of 1,500 nodes. That is three orders of magnitude
below where a graph database earns its keep. NetworkX traversal at this scale is microseconds.
OpenSearch stays the single persistence layer, so no extra service and no extra volume.

Neo4j or ArangoDB would mean a new enterprise dependency, a provisioning request and an
operational surface for 1,500 nodes. Not defensible. This ADR exists so the answer is ready
when someone proposes it.

## Consequences
- **Accepted limitation:** a graph update requires an app restart or a reload endpoint.
  Acceptable because ingestion is manual and there is no ingestion API in the prototype.
- This is also why `ingestion/` runs as a separate process from the serving app.
- OpenSearch object filtering remains available for entity-match style queries.
