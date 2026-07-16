# UFC Predictor

UFC Predictor is a planned, production-quality sports analytics platform for generating reproducible pre-fight UFC predictions. It is designed to estimate:

- fight winner probabilities;
- KO/TKO, submission, and decision paths to victory;
- expected finishing round and fight duration;
- confidence, data sufficiency, and uncertainty;
- comparable historical matchups and bounded counterfactual scenarios.

The project is currently in the architecture and planning phase. It intentionally contains no production ingestion, model, API, or web implementation yet.

## Why this project exists

Fight prediction is easy to make look impressive and hard to make trustworthy. This project prioritizes temporal correctness, traceability, calibration, and honest uncertainty over headline accuracy. Every published prediction is intended to be reproducible from immutable source inputs, a defined information cutoff, a feature snapshot, and a versioned model bundle.

The platform is an analytics product, not a betting product. It will not make wagering recommendations, claim certainty, or conceal missing data behind confident-looking outputs.

## Core principles

- **Leakage resistance:** Features use only information available before both the prediction cutoff and target fight.
- **Immutable provenance:** Raw source bytes are preserved unchanged with checksums and ingestion metadata.
- **Fighter identity safety:** Canonical fighter IDs, aliases, reviewable collision handling, and no name-only merges.
- **Orientation symmetry:** Predictions cannot learn a winner column or red/blue ordering bias; training and inference evaluate both orientations.
- **Probability quality:** Calibration, Brier score, log loss, uncertainty, coverage, and subgroup behavior matter alongside accuracy.
- **Versioned outputs:** Dataset, feature, model, calibration, and prediction versions are returned together.
- **Explicit degradation:** Missing market data, unsupported cohorts, out-of-distribution matchups, and incomplete sources remain visible.
- **Responsible presentation:** Counterfactual inputs are clearly synthetic; explanations are non-causal; probabilities are uncertain estimates.

## Planned system

~~~text
External sources
      |
      v
Immutable raw objects and ingestion manifests
      |
      v
Canonical identities, events, fights, observations, and quality checks
      |
      v
Point-in-time feature snapshots in Parquet and PostgreSQL
      |
      +--------------------------+
      |                          |
      v                          v
Model training/evaluation    Approved online snapshots
      |                          |
      v                          v
MLflow/object artifacts --> FastAPI prediction runtime --> Next.js application
                                  |
                                  v
                         Background workers for simulation,
                         explanations, ingestion, and backfills
~~~

The intended stack is Python 3.12, Polars, Pandas, DuckDB, Parquet, PostgreSQL, scikit-learn, CatBoost, XGBoost, Optuna, MLflow, SHAP, FastAPI, Redis, Celery, Next.js, TypeScript, React, TanStack Query, Docker, and GitHub Actions.

## Model design

The architecture separates the following concerns:

| Model | Purpose |
|---|---|
| Model A | Pure statistical winner probability, with no market fields |
| Model B | Market-informed winner probability using timestamp-valid odds only |
| Model C | Six fighter-specific joint method paths: each fighter by KO/TKO, submission, or decision |
| Model D | Finishing-round and duration distributions using a discrete survival/hazard approach |
| Model E | Conditional decision and judging disagreement analysis, initially shadow-only until data support is proven |
| Model F | Confidence and uncertainty composition: calibration, OOD risk, missingness, debut/data sufficiency, and model disagreement |

Model A and Model B remain distinct products. The system will never label a pure-model fallback as market-informed.

## Architecture documentation

The full implementation contract is in [docs/architecture](docs/architecture).

Recommended starting points:

- [System overview](docs/architecture/SYSTEM_OVERVIEW.md)
- [Requirements](docs/architecture/REQUIREMENTS.md)
- [Data architecture](docs/architecture/DATA_ARCHITECTURE.md)
- [Feature engineering specification](docs/architecture/FEATURE_ENGINEERING_SPEC.md)
- [ML system design](docs/architecture/ML_SYSTEM_DESIGN.md)
- [API specification](docs/architecture/API_SPECIFICATION.md)
- [Database schema](docs/architecture/DATABASE_SCHEMA.md)
- [Implementation roadmap](docs/architecture/IMPLEMENTATION_ROADMAP.md)
- [Architecture decisions](docs/architecture/ADR_INDEX.md)
- [Terra implementation handoff](docs/architecture/TERRA_HANDOFF.md)

## Delivery roadmap

Implementation proceeds through gated milestones:

1. Repository foundation
2. Raw-data ingestion and source audit
3. Identity resolution and canonical data
4. Temporal feature engineering
5. Baseline modeling
6. Calibration and full evaluation
7. Database and FastAPI foundation
8. Prediction service
9. Frontend foundation
10. Core prediction experience
11. Simulation and similarity
12. Explainability
13. Testing and hardening
14. Deployment and observability

Each phase has acceptance criteria, required tests, risks, and an explicit stop/go condition in the [implementation roadmap](docs/architecture/IMPLEMENTATION_ROADMAP.md).

## Data policy

The platform is designed around data-source uncertainty:

- Source schemas and identifiers are not assumed stable.
- Raw datasets and trained model binaries must not be committed.
- A source may not enter published datasets until access, retention, schema, timestamp semantics, and quality are audited.
- Historical rankings and market features require dated, timestamped provenance.
- Source corrections append new observations; they do not rewrite historical knowledge.

See the [data source audit](docs/architecture/DATA_SOURCE_AUDIT.md) for the source-by-source validation plan.

## Repository status

This repository currently contains architecture documentation only. The intended future structure includes:

~~~text
apps/api              FastAPI modular monolith
apps/web              Next.js frontend
services/ml           Ingestion, feature, training, evaluation, inference package
packages/shared-types OpenAPI-generated TypeScript contracts
packages/ui           Shared accessible UI components
data                  Ignored raw/interim/processed data zones
models                Ignored model artifact zone
infrastructure        Local, staging, production, and monitoring configuration
tests                 Data, ML, API, web, contract, E2E, load, and security tests
~~~

## Responsible use

Predictions are analytical estimates conditioned on available historical information. They are not facts, guarantees, medical advice, financial advice, or betting recommendations. The product must communicate uncertainty, data limitations, model version, prediction cutoff, and source freshness alongside every result.

## Contributing

Before implementation begins, changes to the accepted architecture must be recorded through a new or superseding Architecture Decision Record. Do not bypass temporal, identity, split, orientation, provenance, or model-version invariants for convenience.

See [TERRA_HANDOFF.md](docs/architecture/TERRA_HANDOFF.md) for the implementation order, repository contract, migrations, endpoints, test gates, and unresolved decisions.

