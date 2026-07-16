# ADR-0008: Dedicated chronological model calibration

Status: Accepted  
Date: 2026-07-17

## Context

The product exposes probabilities and confidence, so raw classifier ranking is insufficient. Calibration fitted on training/test or selected repeatedly against the final test creates contamination. UFC data is modest, making flexible calibrators unstable.

## Decision

Reserve a chronological calibration split after model validation and before the final untouched test. Store the calibrator as a separately versioned component in the model bundle. Prefer robust parametric calibration for winner and regularized multiclass calibration for paths; allow isotonic only when support and walk-forward evidence justify it. Report raw and calibrated behavior by cohort/horizon.

## Rationale

A dedicated later-period split estimates mapping under realistic temporal shift without consuming final-test evidence. Separate artifacts allow recalibration/rollback without pretending the estimator changed.

## Consequences

Positive:

- honest probability quality and explicit lineage;
- supports Brier/log loss/ECE and confidence policy;
- calibration changes are auditable.

Negative:

- reduces data available to fit the estimator;
- one global calibrator may miss subgroup differences while subgroup calibrators may overfit;
- repeated recalibration needs new version/report.

Use intervals/support labels and avoid segmentation without evidence.

## Alternatives

- No calibration: simpler but unreliable probability semantics.
- Cross-validated calibration on all pretest data: more data, more complex dependency and still needs final chronological validation.
- Calibrate on final test: invalidates final estimate.

## Revisit

Review calibration family/rolling policy after sufficient out-of-time predictions and labels. Changes require predeclared evaluation and a new bundle version.

