# Terra implementation handoff

Status: architecture implementation contract  
Architecture date: 2026-07-17  
Implementation start gate: accepted by technical, data/ML, product, and source-policy owners

## 1. Non-negotiable contract

Terra must implement this architecture in the build order below. Do not redesign it opportunistically. Any change to a bounded-context owner, storage role, temporal invariant, fighter-orientation strategy, model separation/calibration, serving boundary, public probability semantics, or deployment topology requires:

1. a new ADR that supersedes the relevant accepted ADR;
2. rationale, trade-offs, migration/rollback and evidence;
3. updated requirements, API/database/ML contracts, risks, tests, and roadmap;
4. approval before dependent implementation continues.

Do not implement production features during the architecture phase. When implementation starts, preserve these invariants:

- raw source bytes are immutable and checksummed;
- no unresolved fighter identity enters a published modeling dataset;
- every feature is as-of correct and latest_source_timestamp is strictly before the target fight;
- same-fight stats, future ranks, and post-cutoff/closing odds are ineligible;
- pure and market-informed predictions are separate modes;
- fighter orientation is outcome-independent, trained both ways, and inferred both ways;
- splits are chronological/group-disjoint and fit transforms stay within authorized data;
- predictions, datasets, model artifacts, and frozen snapshots are immutable versions;
- observed and counterfactual values are different types and stores;
- probabilities are uncertain estimates, not betting advice.

## 2. Technology baseline

Use Python 3.12, uv-managed locked Python workspaces, Polars as the main transform engine, Pandas only for library interoperability, DuckDB, Parquet, PostgreSQL, SQLAlchemy 2, Alembic, Pydantic, Pandera, scikit-learn, CatBoost, XGBoost, Optuna, MLflow, SHAP, FastAPI, Redis, Celery, Next.js/React/TypeScript, pnpm workspaces, TanStack Query, Radix-based accessible primitives wrapped in packages/ui, Tailwind or an equivalent token-driven styling layer, and Recharts with D3 only when necessary.

uv and pnpm give fast deterministic workspaces and lockfiles; the trade-off is two package managers. Radix primitives reduce accessibility risk but must be wrapped to avoid vendor coupling. Dependency versions are selected and pinned during Milestone 1 after compatibility/security checks; do not use floating ranges in release artifacts.

## 3. Final repository tree

Markers:

- [C] committed source/config/documentation;
- [K] directory and README/.gitkeep committed, generated contents ignored;
- [I] entirely ignored runtime/cache content.

~~~text
ufc-predictor/
├── .github/ [C]
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   └── workflows/
│       ├── ci.yml
│       ├── nightly.yml
│       ├── data-validation.yml
│       ├── model-evaluation.yml
│       └── release.yml
├── apps/
│   ├── api/ [C]
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   ├── alembic.ini
│   │   ├── migrations/
│   │   │   ├── env.py
│   │   │   ├── script.py.mako
│   │   │   └── versions/0001...0009
│   │   └── src/ufc_api/
│   │       ├── main.py
│   │       ├── worker.py
│   │       ├── core/
│   │       │   ├── config.py
│   │       │   ├── errors.py
│   │       │   ├── logging.py
│   │       │   ├── metrics.py
│   │       │   ├── middleware.py
│   │       │   ├── security.py
│   │       │   └── lifespan.py
│   │       ├── db/
│   │       │   ├── base.py
│   │       │   ├── session.py
│   │       │   ├── types.py
│   │       │   └── pagination.py
│   │       ├── auth/
│   │       ├── fighters/
│   │       ├── events/
│   │       ├── fights/
│   │       ├── predictions/
│   │       ├── explanations/
│   │       ├── simulations/
│   │       ├── similarity/
│   │       ├── models/
│   │       ├── data/
│   │       ├── jobs/
│   │       └── admin/
│   │           (each domain contains router.py, schemas.py,
│   │            service.py, repository.py, models.py as needed)
│   └── web/ [C]
│       ├── package.json
│       ├── next.config.ts
│       ├── tsconfig.json
│       ├── postcss.config.*
│       ├── Dockerfile
│       ├── public/
│       ├── app/
│       │   ├── layout.tsx
│       │   ├── page.tsx
│       │   ├── error.tsx
│       │   ├── not-found.tsx
│       │   ├── events/
│       │   ├── fights/
│       │   ├── fighters/
│       │   ├── compare/
│       │   ├── simulator/
│       │   ├── simulations/
│       │   ├── history/
│       │   ├── models/
│       │   ├── methodology/
│       │   ├── data-transparency/
│       │   └── admin/
│       └── src/
│           ├── components/
│           ├── features/
│           │   ├── fighters/
│           │   ├── events/
│           │   ├── predictions/
│           │   ├── explanations/
│           │   ├── simulations/
│           │   ├── similarity/
│           │   └── performance/
│           ├── lib/
│           │   ├── api/
│           │   ├── auth/
│           │   ├── query/
│           │   ├── schemas/
│           │   ├── format/
│           │   └── telemetry/
│           └── styles/
├── services/
│   └── ml/ [C]
│       ├── pyproject.toml
│       ├── Dockerfile
│       ├── configs/
│       │   ├── sources/
│       │   ├── features/
│       │   ├── splits/
│       │   └── models/
│       └── src/ufc_predictor/
│           ├── cli.py
│           ├── config.py
│           ├── ingestion/
│           │   ├── base.py
│           │   ├── registry.py
│           │   ├── raw_store.py
│           │   ├── rate_limit.py
│           │   ├── runner.py
│           │   ├── validation.py
│           │   └── adapters/
│           ├── canonical/
│           │   ├── mappers.py
│           │   ├── taxonomy.py
│           │   ├── publisher.py
│           │   └── validation.py
│           ├── identity/
│           │   ├── normalize.py
│           │   ├── candidates.py
│           │   ├── scorer.py
│           │   ├── resolver.py
│           │   └── review.py
│           ├── datasets/
│           │   ├── manifest.py
│           │   ├── builder.py
│           │   ├── splits.py
│           │   └── validation.py
│           ├── features/
│           │   ├── registry.py
│           │   ├── definitions.py
│           │   ├── targets.py
│           │   ├── point_in_time.py
│           │   ├── rolling.py
│           │   ├── ratings.py
│           │   ├── opponent_adjustment.py
│           │   ├── pairwise.py
│           │   ├── market.py
│           │   ├── missingness.py
│           │   ├── lineage.py
│           │   ├── builder.py
│           │   └── publisher.py
│           ├── training/
│           │   ├── runner.py
│           │   ├── pipelines.py
│           │   ├── baselines.py
│           │   ├── tuning.py
│           │   └── registry.py
│           ├── models/
│           │   ├── winner.py
│           │   ├── market.py
│           │   ├── method.py
│           │   ├── duration.py
│           │   ├── judging.py
│           │   ├── calibration.py
│           │   ├── reconcile.py
│           │   └── uncertainty.py
│           ├── evaluation/
│           │   ├── metrics.py
│           │   ├── cohorts.py
│           │   ├── calibration.py
│           │   ├── plots.py
│           │   ├── report.py
│           │   └── promotion.py
│           ├── inference/
│           │   ├── bundle.py
│           │   ├── runtime.py
│           │   ├── predictor.py
│           │   └── schemas.py
│           ├── explain/
│           ├── simulation/
│           │   ├── counterfactual.py
│           │   ├── monte_carlo.py
│           │   └── schemas.py
│           ├── similarity/
│           │   ├── vectors.py
│           │   ├── index.py
│           │   └── explain.py
│           └── observability/
├── packages/
│   ├── shared-types/ [C]
│   │   ├── package.json
│   │   ├── openapi.json
│   │   └── src/
│   │       ├── generated.ts
│   │       ├── client.ts
│   │       └── index.ts
│   └── ui/ [C]
│       ├── package.json
│       └── src/
│           ├── tokens.css
│           ├── primitives/
│           ├── feedback/
│           └── index.ts
├── data/ [K]
│   ├── README.md
│   ├── raw/.gitkeep
│   ├── quarantine/.gitkeep
│   ├── interim/.gitkeep
│   └── processed/.gitkeep
├── models/ [K]
│   ├── README.md
│   └── .gitkeep
├── infrastructure/ [C]
│   ├── docker/
│   ├── environments/
│   │   ├── local/
│   │   ├── staging/
│   │   └── production/
│   ├── modules/
│   └── monitoring/
│       ├── dashboards/
│       ├── alerts/
│       └── otel/
├── scripts/ [C]
│   ├── bootstrap.*
│   ├── generate-openapi.*
│   ├── generate-types.*
│   ├── check-architecture.*
│   ├── smoke-model.*
│   ├── backup-restore-drill.*
│   └── deploy.*
├── tests/ [C]
│   ├── architecture/
│   ├── data/
│   ├── ml/
│   ├── api/
│   ├── web/
│   ├── contracts/
│   ├── e2e/
│   ├── load/
│   ├── security/
│   └── fixtures/
├── docs/ [C]
│   ├── architecture/
│   ├── runbooks/
│   ├── model-cards/
│   └── data-dictionaries/
├── .env.example [C]
├── .gitignore [C]
├── .editorconfig [C]
├── .pre-commit-config.yaml [C]
├── pyproject.toml [C]
├── uv.lock [C]
├── package.json [C]
├── pnpm-workspace.yaml [C]
├── pnpm-lock.yaml [C]
├── compose.yaml [C]
├── justfile [C]
├── README.md [C]
├── CONTRIBUTING.md [C]
└── SECURITY.md [C]
~~~

Ignored patterns must include data/raw/**, data/quarantine/**, data/interim/**, data/processed/** except README/.gitkeep; models/** except README/.gitkeep; *.duckdb and sidecars; MLflow local state; object-store volumes; .env and environment secrets; model binary formats; coverage/build/cache/node_modules; browser/test artifacts as policy dictates. CI rejects large or recognized raw/model files. Do not ignore manifests intentionally stored under docs/model-cards or test fixtures.

## 4. Build order

Implement in this strict dependency sequence:

1. repository/toolchain/CI and local dependencies;
2. governance/raw storage schema and source audit;
3. ingestion adapter contract and initial permitted source;
4. canonical schema, identity, outcome taxonomy and publisher;
5. immutable dataset manifests;
6. temporal feature registry, builder, ratings and split manifests;
7. deterministic baselines and Model A;
8. calibration, Models B/C/D/F, Model E feasibility, evaluation/registry;
9. API core and catalog repositories/endpoints;
10. model runtime, prediction snapshots, workers and admin promotion;
11. web design foundation and typed contracts;
12. core event/fighter/fight/performance experience;
13. counterfactual, Monte Carlo and similarity;
14. explanations;
15. full hardening, staging and production launch.

Database work may be prepared ahead, but no downstream domain may publish before its upstream gate. Frontend mocks may proceed after schemas stabilize; they must regenerate from actual OpenAPI before integration.

## 5. File-by-file implementation map

### Root and automation

| File | Contract |
|---|---|
| README.md | Product scope, responsible-use warning, quick start, architecture links, no claims about unavailable data |
| CONTRIBUTING.md | branch/review/ADR/migration/test/data policies |
| SECURITY.md | reporting channel and supported security policy |
| pyproject.toml | uv workspace, shared Ruff/mypy/pytest configuration; no application dependency dumping |
| package.json / pnpm-workspace.yaml | workspace scripts and package boundaries |
| justfile | canonical commands in Section 12, with PowerShell-compatible underlying scripts |
| compose.yaml | local PostgreSQL, Redis, optional MinIO/MLflow profiles and health checks |
| .env.example | all non-secret names/descriptions; safe local placeholders only |
| .gitignore | exact ignored data/artifact/secret/cache policy above |
| .github/workflows/ci.yml | PR quality, unit, integration, contracts, web build/axe |
| nightly.yml | extended source fixtures, security, browser, serialization |
| data-validation.yml | scheduled/manual version validation; no automatic publish on failure |
| model-evaluation.yml | controlled candidate evaluation and artifact upload |
| release.yml | build once, SBOM/scan/sign, staging gate, approved production digest |

### API core

| File | Contract |
|---|---|
| main.py | application factory, routers, OpenAPI metadata, root probes; no business logic |
| worker.py | Celery application/queue routing; no task bodies with domain logic |
| core/config.py | strict environment settings, secret types/redacted repr, fail-closed production validation |
| core/errors.py | stable domain-to-HTTP error types and common response |
| core/logging.py / metrics.py | structured redacted logging and bounded metrics from OBSERVABILITY_PLAN |
| core/middleware.py | request ID, timing, CORS/security headers, rate/auth context |
| core/security.py | JWT/OIDC validation, principals/roles, CSRF helpers as applicable |
| core/lifespan.py | database/cache/runtime startup and graceful shutdown/readiness |
| db/base.py / session.py | metadata/naming conventions, async engine/session/transaction dependencies |
| db/types.py | UTC/immutable JSON/content-hash helpers with tests |
| db/pagination.py | opaque signed/encoded keyset cursor and limit policy |

Each domain directory uses:

- models.py for SQLAlchemy persistence owned by that context;
- schemas.py for strict Pydantic public/internal schemas;
- repository.py for named queries only;
- service.py for use-case transaction/policy orchestration;
- router.py for HTTP mapping/dependencies only.

Do not create all five when a domain does not need one; do not put shared business logic in routers.

### ML ingestion/canonical/identity

| File | Contract |
|---|---|
| ingestion/base.py | SourceAdapter protocols and typed work/fetch/parse results |
| ingestion/registry.py | enabled source/version/policy lookup; no credentials in config files |
| ingestion/raw_store.py | persist-before-parse, SHA-256, manifest/object abstraction |
| ingestion/rate_limit.py | per-host concurrency/token policy, Retry-After/jitter |
| ingestion/runner.py | idempotent run/checkpoint/retry/row accounting |
| ingestion/validation.py | transport/schema/source record reports and quarantine |
| ingestion/adapters/* | source-specific discovery/fetch/fingerprint/parse only |
| canonical/mappers.py | source-shaped to canonical observations without guessed fields |
| canonical/taxonomy.py | versioned result/method/division mappings derived from audited labels |
| canonical/publisher.py | transactionally publish validated current facts and immutable history |
| canonical/validation.py | relational/semantic/conflict gates |
| identity/normalize.py | candidate-only text normalization preserving original |
| identity/candidates.py | conservative candidate generation from audited evidence |
| identity/scorer.py | versioned score/threshold, no silent auto-link |
| identity/resolver.py | resolution state/merge/split/referential behavior |
| identity/review.py | review queue commands/contracts and audit |

### Dataset/features

| File | Contract |
|---|---|
| datasets/manifest.py | content-addressed approved manifest/schema and status transition |
| datasets/builder.py | canonical export/partition assembly and row/exclusion accounting |
| datasets/splits.py | immutable event-chronological group split and walk-forward folds |
| datasets/validation.py | referential/temporal/duplicate/distribution publication gates |
| features/registry.py | feature definition schema/version/diff/allow-list |
| features/definitions.py | registered fighter/context/pair/interaction/quality definitions only |
| features/targets.py | target grid/cutoff/participant orientation independent of outcomes |
| features/point_in_time.py | only legal temporal join primitive and lineage max checks |
| features/rolling.py | previous 1/3/5/10, EWM, career/form/streak/activity calculations |
| features/ratings.py | sequential pre/post Elo/Glicko with uncertainty |
| features/opponent_adjustment.py | fold/out-of-fold train-safe adjustment |
| features/pairwise.py | swap-aware differences/interactions/dual rows and weights |
| features/market.py | Model B namespace, quote cutoff/de-vig/version; inaccessible to A |
| features/missingness.py | reason taxonomy, support counts, completeness |
| features/lineage.py | required lineage fields/source-set hashes/direct high-risk refs |
| features/builder.py | common training/scheduled/ad hoc orchestration |
| features/publisher.py | immutable Parquet manifest and exact online snapshot publication |

### Training/models/evaluation/inference

| File | Contract |
|---|---|
| training/runner.py | one config/manifest-driven reproducible entry point |
| training/pipelines.py | training-only preprocessing and signatures |
| training/baselines.py | empirical, rating and logistic required baselines |
| training/tuning.py | bounded seeded Optuna on walk-forward data only |
| training/registry.py | MLflow runs/artifacts/digests/cards/status; no promotion policy bypass |
| models/winner.py | Model A estimator target/feature policy |
| models/market.py | distinct Model B with strict market availability |
| models/method.py | six joint fighter-method paths |
| models/duration.py | discrete hazard/survival and baseline adapters |
| models/judging.py | conditional experimental/shadow Model E |
| models/calibration.py | task-specific calibrators fit only calibration IDs |
| models/reconcile.py | constrained coherent probabilities and diagnostics |
| models/uncertainty.py | entropy, sufficiency, OOD, missing, disagreement, tier/unsupported |
| evaluation/metrics.py | trusted metric implementations/interval utilities |
| evaluation/cohorts.py | predeclared cohort/horizon definitions and support |
| evaluation/calibration.py | reliability/ECE/slope/intercept/risk coverage |
| evaluation/plots.py | deterministic report graphics, not notebook-only |
| evaluation/report.py | immutable complete model card/report/exclusion accounting |
| evaluation/promotion.py | precommitted gates and paired champion comparison |
| inference/bundle.py | typed immutable estimator/preprocess/calibrator/reconciler/OOD bundle |
| inference/runtime.py | trusted digest load, compatibility/golden/swap, atomic cache/swap |
| inference/predictor.py | dual inference, remap/average, reconcile, confidence/result |
| inference/schemas.py | internal version-complete request/result independent of FastAPI |

### Simulation, similarity, explainability

| File | Contract |
|---|---|
| simulation/counterfactual.py | observed/modified separation, allow-list/bounds, dependency recompute, OOD |
| simulation/monte_carlo.py | seeded vectorized sampling, joint coherence, MC error/quantiles |
| similarity/vectors.py | training-reference standardized, weight/style/context groups |
| similarity/index.py | strictly historical, swap-aware exact neighbors initially |
| similarity/explain.py | distance group reasons and material differences |
| explain/* | versioned global/local grouped SHAP, background manifest, non-causal output |

### Web

| Area/file | Contract |
|---|---|
| app/layout.tsx | semantic shell, metadata, fonts, providers, skip link, responsible-use footer |
| app/page.tsx | landing and upcoming/freshness entry; robust no-event state |
| app/events/upcoming/page.tsx | upcoming list/card completeness/timezone |
| app/events/[event_id]/[slug]/page.tsx | event card plus stored prediction summaries |
| app/fights/[fight_id]/page.tsx | historical fight detail |
| app/fights/[fight_id]/prediction/page.tsx | full versioned prediction hierarchy |
| app/fighters/page.tsx | accessible directory/search/pagination |
| app/fighters/[fighter_id]/[slug]/page.tsx | profile/history/trends/coverage |
| app/compare/page.tsx | URL-owned symmetric comparison |
| app/simulator/page.tsx | base matchup and synthetic controls |
| app/simulations/[simulation_id]/page.tsx | immutable counterfactual/Monte Carlo result |
| app/history/page.tsx | filters and actual versus frozen prediction |
| app/models/page.tsx / [model_id]/page.tsx | cards and cohort/calibration performance |
| app/methodology/page.tsx | methodology/limitations/non-causal/no-betting |
| app/data-transparency/page.tsx | per-source freshness/gaps/versions |
| app/admin/* | role protected, lazy loaded, audited confirmation workflows |
| src/lib/api/* | generated client wrapper, request ID/idempotency/error mapping |
| src/lib/query/* | stable keys/defaults/hydration/job polling |
| src/lib/schemas/* | URL/form parsing aligned with OpenAPI |
| src/features/* | domain components/hooks, no cross-feature hidden global state |
| packages/ui | tokens and accessible generic primitives only; no API/domain fetch |

## 6. Database migration sequence

Never combine all schema into one unreviewable migration. Required initial sequence:

1. **0001_extensions_governance**
   - migration metadata/naming; permitted extensions such as pg_trgm after environment support check;
   - data_sources, audit_events foundation;
   - database roles/grants documented separately.
2. **0002_ingestion_raw_quality**
   - ingestion_runs, raw_objects/raw_retrievals, data_quality_issues;
   - idempotency/checksum/status indexes and transition constraints.
3. **0003_catalog_identity**
   - promotions, divisions, fighters, aliases, attribute observations;
   - events/source refs/observations, identity resolution decisions;
   - merge/self/collision constraints.
4. **0004_fights_performance_judging**
   - fights, participants, results, rounds, statistic definitions/statistics;
   - judges/aliases, scorecards/round scores;
   - deferred same-fight and result consistency triggers.
5. **0005_rankings_odds_ratings**
   - ranking observations, odds snapshots, rating system versions/fighter ratings;
   - bitemporal/current partial indexes and probability checks.
6. **0006_datasets_features**
   - dataset_versions, feature_set metadata, feature_snapshots/lineage refs;
   - strict timestamp/content/semantic-key constraints.
7. **0007_models_predictions**
   - model_versions, aliases, promotions;
   - predictions and explanations with immutable/version indexes.
8. **0008_jobs_simulations_auth**
   - durable jobs, simulations, optional user/principal mappings;
   - idempotency, scope, retention indexes.
9. **0009_read_models_integrity**
   - read views/materialized aggregate foundations, search indexes;
   - immutability/state transition triggers and public grants;
   - concurrent indexes are isolated appropriately.

For each migration: test clean upgrade, upgrade from previous production, representative backfill, constraints, lock/duration in staging, old/new application compatibility, and backup/rollback plan. Use a later expand/backfill/contract migration rather than editing an applied revision.

## 7. API endpoint implementation sequence

1. Root GET /health and GET /readiness; common error/request ID/OpenAPI.
2. GET /api/v1/data/freshness with ingestion/quality data.
3. GET /api/v1/fighters, /fighters/{id}, /fighters/{id}/history.
4. GET /api/v1/events, /events/upcoming, /events/{id}.
5. GET /api/v1/fights/{id}.
6. GET /api/v1/models and /models/{id}/metrics using published metadata.
7. POST /api/v1/predictions/matchup and GET /predictions/fights/{id}.
8. GET /api/v1/predictions/{id}/explanation and GET /jobs/{id}.
9. POST /api/v1/simulations/counterfactual.
10. POST /api/v1/simulations/monte-carlo.
11. GET /api/v1/similar-matchups.
12. Administrative ingestion, quality, stage/promote/rollback endpoints.

At every step implement success schema, validation, typed errors, authorization, cache headers/key, database query budget, observability, contract tests, expected latency test, and generated TS client before proceeding. Exact contracts are in API_SPECIFICATION.

## 8. Data pipeline sequence

For every source/run:

1. load enabled source policy and bounded work/checkpoint;
2. acquire distributed/local per-host rate permission;
3. fetch with timeout/retry/redirect/size/content policy;
4. persist raw bytes and retrieval metadata; compute/verify SHA-256;
5. fingerprint source schema;
6. known parser emits source-shaped records with raw references;
7. validate types/semantics and balance accepted/quarantined/filtered counts;
8. resolve canonical source references and identities;
9. append bitemporal canonical observations, never rewrite history;
10. run relational/conflict/freshness checks;
11. create candidate dataset manifest and canonical Parquet export;
12. apply full dataset/temporal/identity/duplicate gates;
13. approve/publish dataset alias through audited compare-and-set;
14. advance ingestion checkpoint only after durable publication;
15. invalidate/rebuild affected downstream snapshots by lineage, preserving frozen predictions.

For a target feature build:

1. create event-group target grid/cutoff and canonical outcome-free orientation;
2. select approved dataset and feature definitions;
3. filter eligible observations before aggregation;
4. compute sequential ratings and fighter rolling/EW/career features;
5. compute train-safe opponent adjustment;
6. add context, pairwise/interactions, quality, and eligible Model B market namespace;
7. generate both orientations/same group;
8. validate lineage max/same-fight/feature allow-list/symmetry/row accounting;
9. hash/write immutable Parquet manifest;
10. publish exact online snapshot where required.

## 9. Model training sequence

1. Select approved dataset/feature/split manifests and locked container.
2. Verify chronology, group disjointness, leakage/poison tests, row/exclusion accounting.
3. Fit fold-specific preprocessing, ratings hyperparameters/adjusters only on authorized training rows.
4. Run empirical, rating, and logistic baselines.
5. Tune CatBoost/XGBoost candidates through bounded seeded walk-forward validation.
6. Freeze feature/model/hyperparameter/calibration selection policy.
7. Fit Model A estimator on authorized pre-calibration data.
8. Fit Model B separately on eligible market rows; retain matched-coverage evaluation.
9. Fit six-path Model C, discrete hazard Model D, and shadow Model E if supported.
10. Fit calibrators only on the calibration split.
11. Fit/version OOD and confidence policy on authorized reference/calibration data.
12. Build reconciliation and complete bundle with signature/environment/digest.
13. Open final test once; produce full cohort/horizon/performance/latency/security report.
14. Register candidate in MLflow/product registry; never auto-promote from training.
15. Stage, load golden/swap vectors, shadow compare, human approve, atomically promote alias.
16. Retain prior champion and verify rollback.

Training aborts on any leakage, split, probability, artifact, or reproducibility failure. A failed final test starts a new model cycle and future holdout policy; it is not tuned against repeatedly.

## 10. Frontend page sequence

1. App shell, tokens/primitives, providers, shared states, typed API client.
2. Landing and methodology/data-transparency pages.
3. Fighter directory/profile.
4. Upcoming events/event detail/historical fight detail.
5. Fight prediction and required charts/tables/warnings/version metadata.
6. Fighter comparison with swap/URL state.
7. Historical exploration.
8. Model list/performance/cohort pages.
9. Matchup simulator and stored simulation results/job polling.
10. Similar matchups and explanation detail.
11. Protected admin dashboard.

Every page is complete only with loading, empty, stale, unsupported, error, and narrow/wide responsive states; keyboard/axe/table alternatives; request ID support; pure/market and conditioning labels. Do not delay accessibility or uncertainty copy to a polish phase.

## 11. Shared type definitions

The FastAPI OpenAPI document is authoritative. Commit a reviewed snapshot and generated TypeScript output; CI fails when generation produces a diff. Define at minimum:

### Primitives and envelopes

- FighterId, EventId, FightId, PredictionId, ModelVersionId, DatasetVersionId, FeatureSnapshotId, SimulationId, JobId as branded/opaque client types;
- UtcTimestamp and LocalDate strings;
- Probability with runtime bounds at API/form edges;
- CursorPage<T>;
- ApiError, ErrorDetail;
- Freshness, ProvenanceSummary, DataQualitySummary.

### Catalog

- FighterSummary, FighterDetail, FighterObservation, FighterHistoryResponse;
- EventSummary, EventDetail;
- FightSummary, FightDetail, ParticipantSummary, ResultSummary, RoundSummary;
- actual outcome types include draw/no-contest/overturned/unknown rather than coercion.

### Prediction

- PredictionMode = pure | market;
- InputCompleteness with per-family counts/ratio/reasons;
- Confidence with supported, tier and decomposed components/reasons;
- FighterWinProbability;
- FighterPathProbabilities for KO/TKO, submission, decision;
- MethodMarginals;
- RoundDistribution and DurationDistribution with conditioning and scheduled bounds;
- ExplanationMetadata and Explanation;
- PredictionVersionTuple;
- Prediction and PredictionSet;
- MatchupContext and MatchupPredictionRequest.

### Simulation/similarity

- FeatureValue with observed_value, effective_value, is_counterfactual, source status;
- CounterfactualModification/Request/Result;
- MonteCarloRequest/Result, DistributionEstimate, MonteCarloError;
- SimilarMatchupQuery/Result/Item/SimilarityReason;
- Job and terminal/error state union.

### Models/operations/admin

- PublicModelCard, EvaluationSummary, MetricEstimate with support/interval;
- DataFreshnessResponse and SourceFreshness;
- DataQualityIssue;
- IngestionRunRequest/Summary;
- ModelPromotionRequest/Promotion;

Use discriminated unions for job and outcome states. Do not represent unsupported/unknown as zero or empty strings. Do not hand-maintain duplicate TS interfaces; web-only view models wrap generated types.

## 12. Environment variable contract

Names below are stable; implementation may add a variable only with .env.example and configuration tests. Secret values never enter Git.

### Common/runtime

- APP_ENV = local | test | staging | production
- RELEASE_SHA and IMAGE_DIGEST
- LOG_LEVEL and LOG_FORMAT
- SENTRY_DSN (secret/optional locally)
- OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME, OTEL_SAMPLE_RATIO
- REQUEST_ID_HEADER

### API/database/cache

- API_HOST, API_PORT, API_WORKERS
- DATABASE_URL (secret), DATABASE_POOL_SIZE, DATABASE_MAX_OVERFLOW, DATABASE_STATEMENT_TIMEOUT_MS
- REDIS_URL (secret), REDIS_CACHE_PREFIX
- CORS_ALLOWED_ORIGINS (explicit list)
- PUBLIC_API_BASE_URL
- RATE_LIMIT_PUBLIC, RATE_LIMIT_PREDICTION, RATE_LIMIT_SIMULATION
- MAX_REQUEST_BYTES, MAX_PAGE_SIZE

### Authentication/security

- OIDC_ISSUER_URL, OIDC_AUDIENCE, OIDC_JWKS_URL
- JWT_REQUIRED_ALGORITHMS
- AUTH_COOKIE_NAME, CSRF_COOKIE_NAME
- MODEL_ARTIFACT_REQUIRE_SIGNATURE
- MODEL_ARTIFACT_TRUSTED_PREFIXES
- AUDIT_IP_HASH_KEY (secret)

### Object storage and registry

- OBJECT_STORE_ENDPOINT (optional for cloud default)
- OBJECT_STORE_REGION
- OBJECT_STORE_ACCESS_KEY_ID and OBJECT_STORE_SECRET_ACCESS_KEY (local/static only; secrets)
- RAW_BUCKET, DATA_BUCKET, MODEL_BUCKET
- OBJECT_STORE_FORCE_PATH_STYLE
- MLFLOW_TRACKING_URI, MLFLOW_REGISTRY_URI
- MODEL_CACHE_DIR
- MODEL_ALIAS_PURE, MODEL_ALIAS_MARKET, MODEL_ALIAS_METHOD, MODEL_ALIAS_DURATION, MODEL_ALIAS_JUDGING
- MODEL_ALIAS_POLL_SECONDS, MODEL_ROLLBACK_CACHE_COUNT

### Workers and schedules

- CELERY_BROKER_URL (secret), CELERY_RESULT_BACKEND only if used transiently
- CELERY_DEFAULT_QUEUE, CELERY_WORKER_CONCURRENCY
- JOB_RESULT_RETENTION_DAYS, ANONYMOUS_SIMULATION_RETENTION_DAYS
- MONTE_CARLO_DEFAULT_ITERATIONS, MONTE_CARLO_MAX_ITERATIONS
- MAX_CONCURRENT_SIMULATIONS_PER_PRINCIPAL
- SCHEDULE_TIMEZONE = UTC

### Data ingestion

- ENABLED_SOURCES (non-secret allow-list)
- SOURCE_USER_AGENT
- SOURCE_CONTACT
- SOURCE_DEFAULT_REQUESTS_PER_MINUTE and SOURCE_MAX_CONCURRENCY (source config may lower)
- SOURCE_REQUEST_TIMEOUT_SECONDS, SOURCE_MAX_RESPONSE_BYTES
- INGESTION_RAW_ROOT (local only)
- DATA_INTERIM_ROOT, DATA_PROCESSED_ROOT, DUCKDB_PATH (local only)
- source-specific credentials use SOURCE_<KEY>_<NAME> and secret storage; never generic payload blobs.

### Web

- NEXT_PUBLIC_API_BASE_URL (public)
- NEXT_PUBLIC_APP_ENV
- NEXT_PUBLIC_SENTRY_DSN if client monitoring is used
- NEXT_PUBLIC_RELEASE_SHA
- INTERNAL_API_BASE_URL for server-side calls where needed
- AUTH session secrets remain server-only and never use NEXT_PUBLIC prefix.

Production configuration must fail readiness for wildcard credentialed CORS, missing OIDC/admin security, untrusted artifact prefixes, writable broad model paths, default secrets, or local filesystem as authoritative object storage.

## 13. Canonical commands

Implement these just targets; underlying scripts must work on PowerShell and CI without unsafe shell interpolation:

~~~text
just bootstrap                 # install pinned uv/pnpm toolchains and dependencies
just infra-up                  # start postgres/redis; optional profile documented
just infra-down                # stop local services without deleting volumes
just migrate                   # Alembic upgrade to head
just seed-test-data            # synthetic/local fixtures only
just dev-api                   # FastAPI reload
just dev-worker                # local Celery queues
just dev-web                   # Next development server
just dev                       # documented multi-process local start
just lint
just format-check
just typecheck
just test-unit
just test-integration
just test-contract
just test-e2e
just test-accessibility
just test-load-smoke
just test-security
just test                       # required PR suite
just openapi
just generate-types
just check-generated
just ingest SOURCE MODE RANGE  # validated args; no unbounded accidental backfill
just build-dataset CONFIG
just build-features CONFIG
just train MODEL_CONFIG
just evaluate RUN_ID
just model-smoke MODEL_VERSION
just snapshot-event EVENT_ID AS_OF MODE
just docs-check
just build-images
just staging-smoke
just restore-drill ENV         # explicit nonproduction target validation
~~~

Destructive volume reset, production backfill, promotion, rollback, and restore are not convenient default targets. They require explicit environment, exact target, confirmation/approval/audit, and documented runbooks.

Direct equivalents for automation:

- uv run alembic upgrade head in apps/api;
- uv run pytest with configured markers;
- uv run ufc-predictor <subcommand>;
- uv run uvicorn ufc_api.main:create_app --factory;
- uv run celery -A ufc_api.worker worker with declared queues;
- pnpm --filter web dev/build/test;
- pnpm generate:types.

The exact executable entry points are created in M1 and must match README/CI.

## 14. Milestone acceptance and mandatory stop/go tests

| Milestone | Acceptance before continuing | Tests/evidence required |
|---|---|---|
| 1 Foundation | clean clone bootstrap/build/local dependencies; ignored data/model/secrets; CI green | import/build/config, Compose health, docs links, secret/large-file/SCA |
| 2 Ingestion | permitted initial source raw bytes/manifests/checkpoints replay idempotently; unknown schema quarantines | source fixtures, retry/429/timeouts, checksum, row accounting, parser security, terms audit |
| 3 Identity/canonical | all modeled rows resolve identities; no silent joins/loss; taxonomy based on observed labels | collision/merge/split, referential/semantic, correction/bitemporal, duplicate tests |
| 4 Temporal features | full approved snapshot has zero temporal/same-fight violations and deterministic hashes/symmetry | future-poison, future rank/current record/closing odds, rolling/rating, missing, split group, parity |
| 5 Baselines | empirical/rating/logistic/CatBoost flow reproducible and compared walk-forward | fit-scope, split disjoint, seed, swap, probability, metric, serialize/load |
| 6 Calibrated models | A-D/F coherent/calibrated; B/E only if supported; complete untouched report and artifact integrity | calibration isolation, method reconciliation, survival bounds, cohort/support, OOD, tamper/golden |
| 7 API foundation | catalog/freshness OpenAPI stable, migrations safe, auth/cache/latency pass | clean/previous migration, constraints, endpoint cases, authz/CORS, Redis degrade, query/load smoke |
| 8 Prediction service | version-complete frozen predictions meet p95, routing/swap/rollback correct | bundle compatibility, dual inference, cache/idempotency, jobs, concurrent hot swap, old snapshot GET |
| 9 Web foundation | typed accessible responsive system with all shared states | generated diff, unit/MSW, axe/keyboard, 360/tablet/desktop visuals, build |
| 10 Core experience | end-to-end event/fighter/fight/compare/history/performance is auditable and non-gambling | Playwright journeys, API contracts, mode/conditioning/version copy, screen-reader/manual, fan-out |
| 11 Simulation/similarity | bounded synthetic controls, reproducible MC, historical explainable neighbors | bound/non-write/OOD, sampling/error, quota/job, strict time/swap distance, E2E |
| 12 Explainability | versioned non-causal accessible local/global factors within budget | additivity/stability/swap, async/cache, baseline/version, UI table/copy/axe |
| 13 Hardening | zero critical leakage/integrity/auth findings; restore/rollback/load/accessibility pass | full TESTING_STRATEGY release suite, scans/SBOM, drills, traceability |
| 14 Launch | same signed digest works staging/production; SLO/freshness/alerts/backups/rollback operational | synthetic/golden, migration, security, load smoke, alert/rollback/restore/schedule failure drills |

Stop immediately and do not publish/continue downstream if:

- source access is not approved;
- schema is unknown or row accounting does not balance;
- identity is ambiguous in modeled rows;
- any temporal/same-fight/outcome/market leakage test fails;
- split/fit contamination is detected;
- probability coherence or swap invariance fails;
- artifact digest/signature/compatibility fails;
- migration, authorization, or backup/rollback critical test fails.

Hard tasks are not blockers by themselves. Resolve or formally change scope through ADR/gate evidence.

## 15. Version tuple and immutable manifests

Every prediction must bind:

~~~text
prediction_id
request_hash and feature_snapshot_hash
prediction_timestamp and prediction_as_of
target_fight_timestamp and horizon_seconds
mode and orientation_policy_version
dataset_version
pipeline_version
feature_set_version
model bundle/component versions
calibration/reconciliation/OOD/confidence policy versions
simulation/explanation/index version when applicable
release/image digest
~~~

Dataset manifest includes source raw/canonical partition hashes, knowledge cutoff, schema/parser/pipeline code, exclusion/identity/taxonomy policy, quality report, and split manifest where used. Model bundle includes ordered feature signature, transforms, estimator, calibrator, reconciler, OOD/confidence references, environment, model card/evaluation and digest. Promotion changes an alias, never an artifact.

## 16. Known risks and unresolved decisions

Implementation must not guess:

- source URLs, fields, licenses, retention, rate ceilings, or historic coverage;
- whether historical rankings and timestamped odds are adequate;
- provider timestamp precision and target bout-time fallback;
- source method/outcome/division labels and mapping;
- fighter identity auto-link threshold;
- exact chronological split dates, minimum cohort support, and promotion thresholds;
- valid definitions for short notice, cardio, pressure, and other experimental proxies;
- Model E product readiness;
- counterfactual empirical ranges;
- hosting vendor, IaC product, public budget, and data residency;
- whether model service/vector search extraction will ever be needed.

Resolve source/taxonomy/identity items in M2-M4 audit artifacts; split/model thresholds before final evaluation; product/infrastructure choices at their roadmap gates. Record material choices in new ADRs. Relevant active risks are R-001 through R-035, with the immediate critical set identified in RISK_REGISTER.

## 17. Implementation review checklist

At each pull request, reviewers ask:

- Does this write to the owning bounded context only?
- Is source provenance and row accounting retained?
- Is every timestamp's meaning and timezone explicit?
- Can a current/future/target value enter a pre-fight row?
- Can an unresolved identity or missing value be silently accepted?
- Are both orientations/split group/weights correct?
- Is pure versus market mode explicit?
- Are fit artifacts restricted to the authorized split?
- Are schemas, migrations, types, tests, metrics, and docs updated together?
- Can the change be rolled back without mutating frozen results?
- Are logs/metrics bounded and redacted?
- Does UI copy communicate uncertainty, conditioning, synthetic data, and non-betting use?
- Does the change alter an accepted decision and therefore require an ADR?

## 18. Completion definition

Terra's work is complete only when all fourteen milestone gates pass, every requirement has test evidence, the public system exposes current data/model versions and freshness, a frozen prediction is reproducible from retained inputs, the model/data/application can be rolled back independently, and no unresolved Critical risk is accepted without owner/expiry/contingency.

An implementation that predicts fights but cannot prove its cutoff, lineage, identity, split, calibration, and artifact version is not this system.

