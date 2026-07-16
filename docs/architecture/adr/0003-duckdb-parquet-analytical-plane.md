# ADR-0003: DuckDB and Parquet analytical plane

Status: Accepted  
Date: 2026-07-17

## Context

Feature building, historical backfills, training matrices, reproducibility, and local research need efficient columnar scans. Raw and derived versions must be portable and inexpensive; UFC-scale data does not justify a distributed engine.

## Decision

Store interim, canonical exports, processed feature snapshots, and split datasets as immutable/versioned Parquet manifests. Use DuckDB for local/offline SQL and Polars as the primary typed transformation engine. Keep PostgreSQL as the online/canonical transactional store.

## Rationale

Parquet is compressed, columnar, interoperable, and suitable for content-addressed/versioned object storage. DuckDB queries it locally without a server. This gives laptop reproducibility and cloud portability at far lower operational cost than Spark/lakehouse services.

## Consequences

Positive:

- fast local scans and simple sharing through manifests/object storage;
- immutable training inputs and easy checksum/versioning;
- avoids loading analytical computation onto PostgreSQL;
- no always-on analytical cluster.

Negative:

- dual representations require publication and parity tests;
- Parquet lacks cross-file transactions unless manifests are carefully atomic;
- concurrent updates are not its strength;
- partition/tiny-file mistakes can hurt performance.

Only complete manifests become visible; engine dtype/null parity and row hashes are tested.

## Alternatives

- PostgreSQL only: fewer stores, but poor wide snapshot portability/scans and production contention.
- Spark/Delta/Iceberg: stronger large-scale processing/table semantics, unjustified operational surface now.
- Pandas/CSV: familiar but weaker types, performance, compression, and schema evolution.

## Revisit

Adopt a lakehouse/distributed engine only when measured data/job concurrency exceeds single-node processing or transactional lake updates become necessary.

