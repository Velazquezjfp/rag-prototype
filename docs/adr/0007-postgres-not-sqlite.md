# ADR-0007: PostgreSQL and SQLAlchemy from day one

## Context
The plan specified SQLite for conversation storage. At 10 users a single replica is fine, and
the direct question was whether this becomes an impediment.

## Decision
Postgres in docker-compose from the first commit, SQLAlchemy + Alembic, database URL from env.
SQLite documented as the fallback.

## Rationale
SQLite *is* swappable if nothing SQLite-specific leaks in, and the swap is a connection string
plus migrations. But this project is explicitly a seed rather than a throwaway, so the migration
is scheduled rather than hypothetical, and doing it later means doing it under a deadline.

OpenSearch already runs as a container, so the marginal cost is one service in a compose file.
Dev/prod parity surfaces concurrency and type-affinity bugs locally instead of in the cluster.
An internal Postgres offering almost certainly already exists.

The usual SQLite leaks that make the migration painful: reliance on type affinity, datetimes
stored as text, `INTEGER PRIMARY KEY AUTOINCREMENT`, and treating JSON columns as if they had
JSONB semantics.

## Consequences
- Usage counters get a transactional home.
- SQLAlchemy makes reverting to SQLite a one-line change if provisioning becomes a fight.
