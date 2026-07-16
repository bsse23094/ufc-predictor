# System overview

Status: approved architecture baseline  
Scope: architecture and planning only  
Audience: engineering, data science, product, operations

## Mission

The platform produces reproducible estimates for UFC fight winner, method, round, duration, uncertainty, and fighter-specific paths to victory. A prediction is an immutable, versioned analytical result, not a fact and not betting advice. The first release is a local-first public analytics product with no wagering, bet sizing, or bookmaker-call-to-action features.

## Architectural principles

1. **As-of correctness before model sophistication.** A feature is eligible only when its source was knowable before both the prediction cutoff and the target fight. This costs storage and pipeline complexity but prevents optimistic, unusable models.
2. **Immutable inputs, replaceable derivations.** Raw responses/files are retained byte-for-byte with checksums; canonical tables, features, and models are rebuilt from versioned code. Storage use rises, while auditability and recovery improve.
3. **One modular monolith before microservices.** FastAPI owns the public API and domain modules; ML jobs remain a separately packaged service/library and workers execute slow jobs. This keeps the MVP operable by a small team, at the cost of independent API-module scaling.
4. **Offline/online parity through snapshots.** The same feature builder writes training and inference snapshots. PostgreSQL serves approved snapshots online; Parquet and DuckDB support analytical builds. Duplication is accepted to avoid reimplementing features in the API.
5. **Explicit degradation.** Missing market data selects the pure model; it never triggers an imputed market prediction. Low-data and out-of-distribution cases remain visible in responses.
6. **Promotion, not replacement.** Datasets, feature sets, and models are immutable versions. Aliases such as champion point to an approved version and can be rolled back.
7. **Probability quality over headline accuracy.** Log loss, Brier score, calibration, coverage, and subgroup behavior are release gates alongside discrimination.

## Context and boundaries

Users browse fighters, events, historical fights, and model performance; request matchup predictions and bounded counterfactuals; and run Monte Carlo simulations. Administrators review ingestion quality, register datasets/models, and promote or roll back versions.

External systems are unstable data sources: UFCStats, ranking publishers, odds providers, scorecard/judging sources, and pre-UFC record providers. The platform does not treat scraped HTML as a canonical schema. It records provider terms, rate limits, parser version, timestamps, and source identifiers for every ingestion.

## Logical system

    External sources
          |
          v
    fetch -> immutable raw objects + ingestion manifest
          |
          v
    source parsers -> canonical validation -> identity resolution
          |
          +-> PostgreSQL canonical operational data
          +-> partitioned Parquet canonical history
                         |
                         v
                 temporal feature builder
                         |
              +----------+-----------+
              |                      |
       training snapshots      inference snapshots
              |                      |
       evaluation/calibration        +-> PostgreSQL online snapshot
              |
       MLflow metadata + object-store artifacts
              |
       promotion manifest / champion aliases
              |
        FastAPI model runtime <---- Redis
              |                    cache/jobs
              +-> Next.js web
              +-> Celery workers for simulation, SHAP, bulk work

## Major components

| Component | Responsibility | Persistent state | Scaling boundary |
|---|---|---|---|
| Next.js web | Pages, accessibility, visualization, query lifecycle | Minimal browser state | CDN and web replicas |
| FastAPI API | Validation, authorization, domain reads, low-latency inference | PostgreSQL, Redis | API replicas |
| ML service package | Ingestion, identity resolution, features, training, evaluation, batch inference | Parquet, PostgreSQL, MLflow/object store | Scheduled/ephemeral jobs |
| Celery workers | Backfills, explanation jobs, simulations, snapshot generation | Redis broker/results; durable outcomes in PostgreSQL | Queue-specific workers |
| PostgreSQL | Canonical entities, temporal facts, online features, predictions, governance | Managed/local volume | Vertical first, read replica later |
| DuckDB + Parquet | Local/offline analytical computation and reproducible datasets | Files/object storage | Partitioned jobs |
| MLflow + object storage | Experiment metadata, model registry, signed artifacts | Database + immutable blobs | Managed/object-store scaling |
| Redis | Short-lived cache, rate limits, task transport | Ephemeral with persistence appropriate to broker | Managed or single instance |

## Data planes

- **Raw plane:** immutable bytes and manifests. Never edited or used directly by the web API.
- **Canonical plane:** normalized source facts with source time, ingestion time, validity, provenance, and identity status.
- **Feature plane:** point-in-time snapshots keyed by target fight, fighter orientation, prediction cutoff, feature-set version, and dataset version.
- **Model plane:** registered artifacts, signatures, dependencies, calibration objects, evaluation reports, and aliases.
- **Product plane:** frozen predictions, explanations, simulations, freshness summaries, and performance aggregates.

## Key workflows

### Historical backfill

An idempotent run fetches or imports source objects, validates checksums, detects schema, parses into staging, resolves identities, applies canonical constraints, and publishes a new dataset version only if quality gates pass. Failed runs preserve raw input and diagnostics but cannot become current.

### Upcoming prediction

A scheduler records an event card as known at a cutoff, builds point-in-time features, routes to the pure or market-informed champion according to explicit availability rules, performs swapped-orientation inference, calibrates and reconciles outputs, stores a frozen prediction snapshot, and exposes the result with its complete version tuple.

### Ad hoc matchup

The API validates fighter/context inputs, loads the promoted model bundle in process, obtains or builds an approved feature snapshot, and returns a synchronous result when cached or cheap. Slow feature builds, SHAP calculations, and large simulations are queued and represented by a job resource.

### Model promotion

Training writes a candidate with a model card. Automated gates compare it with the active champion on untouched and subgroup evaluations. A privileged administrator promotes an alias only after approval. API replicas poll the signed manifest, warm the candidate, run a smoke prediction, then switch atomically; the previous bundle stays warm for rollback.

## Reproducibility contract

Every externally visible prediction records:

- prediction_id and prediction_timestamp;
- target fight and scheduled timestamp, or an explicit hypothetical matchup;
- prediction_as_of and horizon_seconds;
- ordered input fighter IDs plus orientation policy version;
- source cutoff and input completeness;
- dataset_version, feature_set_version, pipeline_version;
- model bundle and calibration versions;
- raw input hash and feature snapshot hash;
- output probabilities, uncertainty components, and explanation availability;
- request mode: pure, market-informed, counterfactual, or simulation.

Given retained raw objects, the code revision/container digest, configuration, seed, and version tuple, an authorized operator can reproduce the snapshot within declared numerical tolerances.

## Reliability targets for the MVP

| Objective | Initial target | Measurement |
|---|---:|---|
| Public read availability | 99.5% monthly | Synthetic and server metrics |
| Cached read p95 | under 250 ms | API histogram |
| Uncached synchronous prediction p95 | under 1.5 s | API histogram |
| Queue acknowledgement p95 | under 500 ms | API histogram |
| Standard simulation completion | under 30 s | Worker histogram |
| Freshness | published per source, not hidden behind one value | Freshness endpoint |
| Recovery point | PostgreSQL 24 h MVP; object versions immutable | Restore drill |
| Recovery time | 4 h MVP | Restore drill |

Targets are service objectives, not contractual SLAs. They should be tightened only after production traffic establishes a baseline.

## Deliberately deferred

- Live round-by-round prediction, event streaming, and sub-minute latency.
- A separate inference microservice, feature streaming platform, and online vector database.
- Bayesian round-state simulation and judge-specific live scoring.
- User wagering features, personalized recommendations, or financial outcome language.
- Automated promotion without a human gate.

These deferrals reduce operational and ethical risk. Their trade-off is less flexibility at very high traffic and fewer real-time capabilities.

## Related documents

- [Requirements](REQUIREMENTS.md)
- [Data architecture](DATA_ARCHITECTURE.md)
- [ML design](ML_SYSTEM_DESIGN.md)
- [Backend architecture](BACKEND_ARCHITECTURE.md)
- [Deployment](DEPLOYMENT_ARCHITECTURE.md)
- [Implementation contract](TERRA_HANDOFF.md)

