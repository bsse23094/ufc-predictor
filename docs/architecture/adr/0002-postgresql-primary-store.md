# ADR-0002: PostgreSQL as production relational and serving store

Status: Accepted  
Date: 2026-07-17

## Context

The platform needs transactional canonical identities, bitemporal observations, event/fight relationships, odds/rank histories, governance, immutable predictions, jobs, authorization/audit, and read APIs. Data volume is moderate, but integrity and point-in-time queries are critical.

## Decision

Use PostgreSQL as the production relational system of record and online serving database, accessed through SQLAlchemy 2 and migrated with Alembic. Use managed PostgreSQL for public environments when affordable.

## Rationale

PostgreSQL provides strong transactions, constraints, temporal/query expressiveness, indexing, JSONB for bounded variable outputs, operational maturity, and broad hosting options. It can serve canonical and product data without an early distributed database.

## Consequences

Positive:

- one authoritative transactional store;
- enforceable foreign/unique/check constraints and audited migrations;
- capable point-in-time and product queries;
- optional future pgvector/read replicas.

Negative:

- analytical scans and wide training matrices are inefficient compared with columnar files;
- bitemporal queries need careful indexes and application discipline;
- write/compute workloads can contend if training queries hit production;
- managed service has nonzero cost.

Parquet/DuckDB isolate offline analytics; connection pooling, read models, and later replicas control load.

## Alternatives

- SQLite/DuckDB as production store: cheap but inadequate concurrent transactional/API workload and governance.
- Document database: flexible outputs but weaker relational integrity and temporal joins.
- Cloud warehouse/lakehouse only: good analytics, poor low-latency transactional product state and cost fit.

## Revisit

Revisit individual workloads after measured query/volume limits. PostgreSQL remains canonical unless a migration ADR includes consistency, lineage, and rollback design.

