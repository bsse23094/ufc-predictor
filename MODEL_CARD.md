# Model card

## Status

An accepted **local pure winner model** exists in the immutable M4 champion
bundle for M3 generation `m3-74eeb9b7f49b5adca45e461a`. The current champion
is `overall_elo_plus_recent_adjusted__phase3a_shallow_xgboost` with training
cutoff `2023-11-11`. Its bundle reports a 1,337-row inspected benchmark:
ROC-AUC 0.6602, Brier score 0.2312, and log loss 0.6544. These are historical
benchmark values, not current-card accuracy guarantees. The bundle and data
are local ignored artifacts, so a clean checkout cannot serve predictions
until they are reproduced.

Only symmetric win probability is accepted for inference. Method, round,
duration, market, and full uncertainty outputs have no accepted model bundle.
The runtime rejects pairs or dates without an accepted strict-date pre-fight
materialization. See [the implementation audit](docs/IMPLEMENTATION_AUDIT_2026-10-08.md).

## Intended use

The platform provides uncertain pre-fight UFC winner estimates with model and
feature provenance. It does not provide wagering recommendations or guarantees.

## Required before a full product model card and release

- accepted models for method, duration, uncertainty, and any market-informed mode;
- full cohort and horizon evaluation with supported sample counts;
- durable model registry, human promotion approval, and rollback target;
- verified service latency, deployment, and monitoring gates.

The required structure and metrics are defined in [ML_SYSTEM_DESIGN.md](docs/architecture/ML_SYSTEM_DESIGN.md) and [MODEL_EVALUATION_PLAN.md](docs/architecture/MODEL_EVALUATION_PLAN.md).
