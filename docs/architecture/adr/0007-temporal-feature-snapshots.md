# ADR-0007: Immutable point-in-time feature snapshots

Status: Accepted  
Date: 2026-07-17

## Context

The primary system invariant is that no feature may know the target fight or any future fact. Sources revise schedules, profiles, rankings, odds, results, and statistics. Recomputing from current state cannot reproduce an old prediction.

## Decision

Represent source facts bitemporally and build immutable feature snapshots through a single PointInTimeJoiner. A snapshot is keyed by target/matchup, prediction_as_of, target timestamp, orientation, dataset, pipeline, and feature-set versions. It records latest source timestamp, lineage/content hashes, missing/imputation metadata, and must satisfy:

    latest_source_timestamp < target_fight_timestamp
    latest_source_timestamp < conservative prediction cutoff
    source_fight_id != target_fight_id

Use Parquet/manifests offline and publish exact approved online snapshots to PostgreSQL. Do not implement an external feature-store product initially.

## Rationale

Snapshots make training/serving parity, audits, frozen predictions, corrections, and rollback explicit. Bitemporal storage preserves what was known before a later correction.

## Consequences

Positive:

- reproducible as-of training/inference;
- independent leakage validation and lineage invalidation;
- no feature logic scattered in API queries.

Negative:

- additional storage and version proliferation;
- bitemporal joins and incremental recomputation are complex;
- per-cell lineage can be expensive.

Feature-family lineage/source-set hashes control size, with direct lineage for high-risk rankings/odds. Publication gates and retention policies manage versions.

## Alternatives

- Compute current features on request: simpler but unreproducible and leakage-prone.
- External feature store: point-in-time tooling but added cost/vendor complexity and still requires correct source times.
- One mutable feature table: easy serving but destroys historical knowledge.

## Revisit

Adopt a feature-store service if online write/lookup scale or many consuming teams justify it. The temporal and snapshot contract must remain.

