# ADR-0006: Fighter orientation symmetry

Status: Accepted  
Date: 2026-07-17

## Context

Fight datasets may place winners, red corners, favorites, or source-first participants in a consistent column. A flexible model can learn column position rather than matchup skill. Random orientation alone reduces but does not guarantee symmetry.

## Decision

Use all of:

1. outcome-independent deterministic canonical participant order;
2. split assignment at original fight group before augmentation;
3. both A/B orientations in training with remapped labels and half weights;
4. symmetric/antisymmetric pairwise features where appropriate;
5. both orientations at inference with remapped probability averaging;
6. mandatory swap property tests for winner, method paths, duration/context, and UI.

Source red/blue is retained for history/display only and excluded from model allow-lists unless a future evidence-backed contextual feature receives its own ADR.

## Rationale

Dual inference mathematically removes residual directional output after averaging, while dual training teaches useful symmetry and exposes bugs. The compute doubles, but UFC-scale tabular work makes that inexpensive compared with the leakage risk.

## Consequences

Positive:

- testable prediction invariance and unbiased fighter columns;
- compatible with CatBoost/XGBoost/logistic models;
- clear remapping for fighter-specific paths.

Negative:

- doubles augmented training rows and inference calls;
- requires group-aware weights/splits/metrics;
- method/path remapping and cache keys are more complex;
- does not impose true internal antisymmetric constraints.

## Alternatives

- Random red/blue only: cheaper but seed-dependent and no per-request guarantee.
- Symmetric differences only: strong but may lose nonlinear information from paired raw features.
- Hard antisymmetric model architecture: elegant, but poor fit with selected mature tabular libraries and higher custom risk.

## Revisit

Revisit hard constraints only if swap averaging latency becomes material or a validated architecture improves out-of-time probability quality without sacrificing auditability.

