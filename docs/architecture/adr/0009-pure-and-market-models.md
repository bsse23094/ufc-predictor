# ADR-0009: Separate pure and market-informed winner models

Status: Accepted  
Date: 2026-07-17

## Context

Market information can improve probability forecasts but is unavailable at some horizons and can conceal the contribution of sporting features. Incorrect quote timestamps cause severe leakage. The product must offer both statistical and market-informed estimates.

## Decision

Train and register Model A (pure) and Model B (market-informed) as separate estimators and product modes with disjoint feature policies. Model A rejects all market lineage. Model B requires eligible timestamped quotes and exposes provider/cutoff/horizon/completeness. Never silently impute or label a pure fallback as market-informed.

## Rationale

Separation makes leakage audits, coverage, scientific baseline, and incremental market value visible. It also guarantees a useful product when licensed/timestamped market data is absent.

## Consequences

Positive:

- clear provenance and user semantics;
- honest matched-row A/B evaluation;
- independent calibration/promotion/rollback;
- market dependency cannot contaminate the pure model.

Negative:

- duplicate training/serving artifacts;
- UI/API need explicit mode behavior;
- different coverage complicates comparison;
- Model B may repeat structure learned by A.

## Alternatives

- One model with missing market fields: fewer artifacts but opaque fallback and training selection effects.
- Stack Model B on Model A output: potentially efficient, but requires strict out-of-fold A predictions and adds dependency; deferred.
- Market-only model: useful benchmark, not a complete sports model.

## Revisit

Consider out-of-fold stacking only after separate models establish stable baselines. Wagering/ROI optimization remains outside scope regardless of architecture.

