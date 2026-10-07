# Implementation roadmap

> Status note (2026-10-08): Milestone descriptions below are acceptance targets.
> The older M3 "in progress" paragraph and the M7–M14 "complete" claims in
> `../CURRENT_PROGRESS.md` are stale or overbroad. Consult
> [the implementation audit](../IMPLEMENTATION_AUDIT_2026-10-08.md) for verified
> current behavior and open release gates.

## Delivery rules

Milestones are ordered gates, not parallel feature wishes. A milestone closes only when its acceptance criteria and tests pass and required evidence is stored. Later exploratory spikes may begin early, but they cannot bypass dependency gates. Complexity is relative:

- S: focused change, limited cross-module risk;
- M: several modules/integrations;
- L: major domain/pipeline slice;
- XL: highest-risk, cross-cutting and data-dependent.

Estimates intentionally avoid calendar promises until team size, source access, and actual schemas are known.

## Milestone 1: repository foundation

**Goal:** Create a reproducible monorepo skeleton and quality gates without product functionality.

**Deliverables**

- Python 3.12 and Node/TypeScript workspaces with locked dependencies.
- apps/api, apps/web, services/ml, packages/shared-types, packages/ui skeletons.
- Docker Compose dependencies, environment validation, task runner commands.
- CI for lint, type, unit, docs links, secrets/dependencies, builds.
- Architecture docs/ADR policy and ignored data/model/artifact directories.

**Dependencies:** approved architecture only.  
**Acceptance criteria:** clean clone can install, start PostgreSQL/Redis, run placeholder health/build checks and all CI; no raw/model bytes tracked.  
**Tests:** configuration, import/build, migration bootstrap, Compose health, secret/large-file and docs-link checks.  
**Risks:** toolchain complexity, cross-platform path behavior, dependency conflicts.  
**Complexity:** M.  
**Files/modules:** root pyproject.toml, package.json, workspace/lock files, Makefile or justfile, .gitignore, .env.example, compose.yaml, apps/* skeleton, services/ml/pyproject.toml, infrastructure/docker, .github/workflows/ci.yml, tests/architecture.

## Milestone 2: raw-data ingestion

**Status:** Complete for the approved, local-file-only Kaggle Ultimate UFC Dataset scope. UFCStats remains a red/no-go audit decision with no adapter or scraper. See `docs/CURRENT_PROGRESS.md` for the locked dependency and acceptance evidence.

**Goal:** Acquire permitted source inputs reproducibly while preserving bytes and provenance.

**Deliverables**

- data-source registry/policy and completed audit for initial UFCStats scope.
- RawObject/IngestionRun persistence and object-store adapter.
- Source adapter contract, rate limiter, retry/checkpoint, schema fingerprints, quarantine.
- CLI/worker paths for bounded backfill and incremental update.
- Row-accounting and freshness report.

**Dependencies:** M1; legal/terms decisions.  
**Acceptance criteria:** replaying approved fixtures/backfill is idempotent; raw checksums trace to run; unknown schema blocks publication; checkpoints advance only after durable validation.  
**Tests:** HTTP fixtures, retry/429/timeout, checksums, schema variants, malicious/oversized content, duplicate retrieval, row accounting.  
**Risks:** access restrictions, schema drift, unreliable timestamps, rate bans.  
**Complexity:** L.  
**Files/modules:** services/ml/src/ufc_predictor/ingestion/{base,registry,raw_store,runner,validation}.py, adapters/ufcstats, apps/api modules/data models, Alembic 0001-0002, tests/data/ingestion, scripts/ingest.

## Milestone 3: identity resolution and canonical data

**Status:** In progress. Candidate-only alias normalization, candidate/review contracts, canonical fighter/alias schema, append-only durable review evidence, reviewed-link application, bitemporal alias correction, guarded canonical merge/split transitions, a source-shaped canonical Parquet mapping boundary, transactional relational loading, and durable conflict/quarantine reports are implemented. A durable review must exactly match retained source/raw evidence before it can create aliases or transition canonical identities; every application is append-only and terminal (`applied` or `quarantined`). The mapper requires exact reviewed aliases and explicit reviewer-attributed outcome/method/division mappings, preserving raw labels and quarantining any gap. A quarantine requires an audit issue; mapper quarantines plus relational or replay conflicts persist idempotent blocking reports keyed by source record and raw checksum. The loader atomically publishes source references, fights, outcome-independent participants, identity evidence, and results only from a zero-quarantine mapping result. The approved source has no event identifier, so it records event context as `not_observed` rather than inventing events. No real-source taxonomy map is supplied by default. Fixture acceptance is verified; real-source acceptance awaits the manually acquired approved file and its reviewed aliases/labels.

**Goal:** Build canonical fighters/events/fights and prevent identity collisions or silent joins.

**Deliverables**

- Normalized catalog/performance schema and canonical mapping pipeline.
- Fighter/source aliases, candidate generator/scorer, review queue and merge/split audit.
- Canonical outcome/method taxonomy based on observed source labels.
- Referential/semantic validators and conflict reports.

**Dependencies:** M2 representative fixtures/backfill.  
**Acceptance criteria:** every modeled participant has a resolved canonical ID; ambiguous cases quarantine; every canonical fact traces to raw; input counts balance.  
**Tests:** name collisions, source-ID changes, Unicode aliases, duplicate bouts, corrections, two-participant/result/round constraints, invalid joins.  
**Risks:** false merges, sparse identifiers, cross-source disagreement.  
**Complexity:** XL.  
**Files/modules:** services/ml/.../identity, canonical/{models,mappers,taxonomy,validation}.py, apps/api modules/fighters/events/fights/data, Alembic 0003-0005, tests/data/identity and canonical.

## Milestone 4: temporal feature engineering

**Goal:** Publish leak-free point-in-time fighter/matchup snapshots from canonical history.

**Deliverables**

- Feature registry, target grid, PointInTimeJoiner, rolling/EW/career/context features.
- Sequential Elo/Glicko and train-safe opponent-adjustment interfaces.
- pairwise/interactions, missingness/quality, optional market namespace behind gate.
- Feature manifests/lineage/hashes, offline Parquet and online PostgreSQL publication.
- Deterministic two-orientation builder and frozen split manifest tool.

**Dependencies:** M3; dated ranking/odds features only if their source audit is green.  
**Acceptance criteria:** strict temporal invariant and same-fight exclusion pass on full build; training/inference snapshots match; swap properties pass; feature registry covers every output.  
**Tests:** future-poison, later corrections, rolling boundaries, current ranking/profile leakage, odds cutoff, rating sequence, missing reasons, engine parity, hash reproducibility, group split.  
**Risks:** subtle leakage, expensive recomputation, timestamp ambiguity, feature explosion.  
**Complexity:** XL.  
**Files/modules:** services/ml/.../features/{registry,targets,point_in_time,rolling,ratings,opponent_adjustment,pairwise,market,lineage,builder}.py, configs/features, schemas/feature_snapshot.py, tests/data/temporal and features, Alembic 0006.

## Milestone 5: baseline modeling

**Goal:** Establish honest out-of-time baselines and a repeatable training run for Model A.

**Deliverables**

- Immutable chronological split manifest and walk-forward folds.
- Empirical, rating, logistic, CatBoost candidate training.
- MLflow/object artifact tracking and initial model card.
- Metrics/cohort report without final-test-driven tuning.

**Dependencies:** M4 approved feature/dataset version.  
**Acceptance criteria:** deterministic baselines run end-to-end; no leakage gate fails; candidate compared on validation/walk-forward; production image loads artifact/golden vectors.  
**Tests:** split disjointness, preprocessing fit scope, reproducibility, swap, probability, serialization, baseline metric fixtures.  
**Risks:** small samples, overly optimistic baseline, environment nondeterminism.  
**Complexity:** L.  
**Files/modules:** services/ml/.../training/{runner,splits,pipelines,baselines,catboost,optuna_space}.py, evaluation basics, registry client, configs/models, tests/ml/training.

## Milestone 6: calibration and full evaluation

**Goal:** Produce release-grade Models A-D and uncertainty policy with untouched final evaluation.

**Deliverables**

- calibration candidates/selection policy;
- Model B market champion candidate where eligible;
- six-path Model C plus probability reconciler;
- discrete hazard Model D and Model F components;
- full metrics/cohorts/horizons/risk-coverage report and promotion policy;
- Model E feasibility report/shadow candidate if data allows.

**Dependencies:** M5; sufficient audited method/duration/market/judging labels.  
**Acceptance criteria:** coherent calibrated outputs; final report contains required metrics/support/limitations; candidate meets precommitted gates; test remains one-time; artifacts are integrity-bound.  
**Tests:** calibration split isolation, reconciliation properties, survival bounds, OOD/missing/debut confidence, cohort unsupported behavior, tamper/load/stability.  
**Risks:** calibration overfit, rare methods, market selection bias, judging coverage.  
**Complexity:** XL.  
**Files/modules:** services/ml/.../models/{winner,market,method,duration,judging,uncertainty,reconcile,calibration}.py, evaluation/{metrics,cohorts,plots,report,promotion}.py, tests/ml/models and evaluation.

## Milestone 7: database and FastAPI foundation

**Goal:** Expose canonical read APIs with secure, observable application foundations.

**Deliverables**

- SQLAlchemy/Alembic schema through model registry/product foundations.
- FastAPI settings, lifecycle, sessions, repositories, common errors, request IDs, logs/metrics.
- fighter/event/fight/freshness endpoints and OpenAPI-generated TS contract.
- Redis cache and public/admin auth boundaries.

**Dependencies:** M1 and stable M3 schema; can start before M6.  
**Acceptance criteria:** required catalog endpoints meet contract/latency on representative data; migrations upgrade clean/previous; authz and cache isolation pass; readiness is truthful.  
**Tests:** unit/repository/constraint/migration/OpenAPI, 4xx/5xx, pagination, N+1, Redis degradation, CORS/security headers.  
**Risks:** ORM/domain coupling, migration locks, contract churn.  
**Complexity:** L.  
**Files/modules:** apps/api/src/ufc_api/{main,core,auth,fighters,events,fights,data,db}.py, migrations 0001 onward, packages/shared-types generated, tests/api.

## Milestone 8: prediction service

**Goal:** Serve and freeze approved predictions with version-complete responses and safe rollback.

**Deliverables**

- ModelRuntime loader/cache/hot swap and PredictionPort.
- feature snapshot repository, mode router, dual inference, calibration/reconciliation/confidence.
- matchup and fight prediction endpoints; immutable snapshots/explanation status.
- Celery/Redis jobs/idempotency and scheduled card snapshot command.
- promotion/stage/rollback administration.

**Dependencies:** M6 approved bundles; M7.  
**Acceptance criteria:** golden prediction reproduces, swap symmetry passes, pure/market routing explicit, p95 budget met, atomic model rollback works, old GET never recomputes.  
**Tests:** bundle integrity/compatibility, concurrency/hot swap, cache keys, job retries, endpoint contracts, load/resilience.  
**Risks:** memory per replica, artifact code execution, version mismatch, synchronous CPU blocking.  
**Complexity:** XL.  
**Files/modules:** apps/api modules/predictions/models/jobs/explanations, services/ml/inference, worker tasks, migrations for product snapshots, tests/api/model_serving.

## Milestone 9: frontend foundation

**Goal:** Establish accessible design system, typed API integration, navigation, and reliable page-state patterns.

**Deliverables**

- Next App Router shell, typography/tokens/dark theme, component wrappers.
- generated API client, TanStack Query, URL schema helpers, error boundaries.
- landing, upcoming, directory and methodology/transparency page foundations.
- Storybook or equivalent component harness if maintenance cost is justified.

**Dependencies:** M1; M7 OpenAPI or stable mocks.  
**Acceptance criteria:** responsive shells at target widths, WCAG automated gates, typed build, all shared loading/error/empty/stale states demonstrated.  
**Tests:** components, MSW contracts, axe, screenshot, basic Playwright navigation.  
**Risks:** overbuilt design system, chart accessibility, hydration/data duplication.  
**Complexity:** L.  
**Files/modules:** apps/web/app, apps/web/src/{components,features,lib,styles}, packages/ui, packages/shared-types, tests/web.

## Milestone 10: core prediction experience

**Goal:** Deliver event, fight, fighter, comparison, history, and performance experiences.

**Deliverables**

- all core pages and domain components;
- coherent winner/method/round/duration visualizations;
- confidence/data/version/freshness surfaces;
- model performance cohorts/calibration and historical actual-versus-prediction distinction.

**Dependencies:** M8; M9.  
**Acceptance criteria:** user can navigate upcoming event to auditable prediction and compare fighters on mobile/desktop; uncertainty and pure/market mode cannot be missed; no gambling language.  
**Tests:** full page/component/API/E2E, accessibility/manual screen-reader, visual breakpoints, swap and version labeling.  
**Risks:** probability miscommunication, dense mobile UI, expensive fan-out.  
**Complexity:** XL.  
**Files/modules:** apps/web/app/events, fights, fighters, compare, history, models; features/predictions and charts; E2E journeys.

## Milestone 11: simulation and similarity

**Goal:** Add bounded counterfactuals, calibrated Monte Carlo distributions, and explainable historical neighbors.

**Deliverables**

- counterfactual schema/validator/dependency recomputation;
- simulation engine/jobs/results and UI controls/progress/charts;
- standardized similarity vectors, exact nearest neighbors, reason decomposition;
- shareable immutable simulation results and retention cleanup.

**Dependencies:** M8; M10; feature registry controls approved.  
**Acceptance criteria:** unrealistic inputs reject, synthetic values remain distinct, seeded simulations reproduce within exact/declared tolerance, standard job budget met, neighbors are strictly historical and explainable.  
**Tests:** bounds/property/OOD, canonical non-write, sampling calibration/standard errors, job quota/idempotency, time filter/swap-aware distance, E2E.  
**Risks:** causal misinterpretation, compute abuse, incompatible model distributions.  
**Complexity:** L.  
**Files/modules:** services/ml/simulation and similarity, apps/api modules/simulations/similarity, apps/web simulator/simulations/components, migrations, tests.

## Milestone 12: explainability

**Goal:** Provide versioned, non-causal global/local explanations with data-quality context.

**Deliverables**

- TreeSHAP/grouped explanation pipeline and background manifest;
- precomputed/asynchronous explanation storage/API;
- explanation chart/table/copy and methodology;
- explanation stability/latency monitoring.

**Dependencies:** M6 model families; M8; M10.  
**Acceptance criteria:** each explanation names algorithm/baseline/version, favors both sides coherently, reports correlated/missing caveats, meets async/sync budget and accessibility.  
**Tests:** additivity/tolerance, swap/remap, serialization, stability, cache/version, UI text/table/accessibility.  
**Risks:** causal overclaim, correlated-feature confusion, SHAP compute/memory.  
**Complexity:** M.  
**Files/modules:** services/ml/explain, apps/api/explanations/tasks, apps/web explanation components/methodology, tests/ml/explain.

## Milestone 13: testing and hardening

**Goal:** Close release-critical correctness, security, accessibility, performance, and recovery gaps.

**Deliverables**

- full traceability matrix and CI tiers;
- load/resilience and parser/artifact security testing;
- backup/restore, rollback, source-schema, and incident drills;
- dependency/image/SBOM/signing gates;
- resolved critical/high risks or accepted owner/date.

**Dependencies:** M2-M12.  
**Acceptance criteria:** all requirements have evidence; zero critical leakage/coherence/auth/integrity findings; load SLOs and restore/rollback pass; accessibility manual review passes.  
**Tests:** entire TESTING_STRATEGY release suite.  
**Risks:** late systemic defects, flaky E2E, unrealistic load fixtures.  
**Complexity:** L.  
**Files/modules:** tests/e2e, tests/load, tests/security, scripts/drills, .github release workflows, runbooks.

## Milestone 14: deployment and observability

**Goal:** Launch an affordable, reversible MVP with transparent freshness and monitoring.

**Deliverables**

- staging/production IaC and signed immutable images;
- managed PostgreSQL/object storage, Redis, edge/TLS/secrets;
- migration/release/rollback workflows;
- scheduled ingestion/snapshot/retraining evaluation;
- logs/metrics/traces/Sentry, dashboards, alerts, runbooks, public freshness;
- cost/budget alarms and on-call ownership.

**Dependencies:** M13 release approval.  
**Acceptance criteria:** same image promoted staging to production; probes/golden path/SLO dashboards healthy; alert and rollback drills pass; backups restore; public freshness/current versions visible.  
**Tests:** staging E2E/load/security, disaster recovery, model/data/app rollback, synthetic monitors, schedule failure.  
**Risks:** provider limits, cost growth, single-host failure, alert fatigue.  
**Complexity:** L for MVP, XL for scalable production.  
**Files/modules:** infrastructure/{docker,terraform or chosen IaC,monitoring}, .github/workflows/release.yml, scripts/deploy, docs/runbooks, environment manifests.

## Cross-milestone decision gates

- End M2: which sources are legally and temporally green.
- End M3: canonical taxonomy and identity auto-link thresholds.
- End M4: exact split dates and target timestamp policy.
- End M5: baseline metric distributions and numerical promotion thresholds.
- End M6: whether Model B/E and advanced features are product-ready or experimental.
- End M8: whether in-process inference meets memory/latency; extraction requires ADR.
- End M11: whether exact search/simulation approximation meet measured use.
- End M13: low-cost topology and launch go/no-go.

## Definition of done

Done means code, migrations, versioned contract, tests, operational telemetry, documentation, security review, and rollback/maintenance path exist. A notebook result, locally loaded model, or attractive page alone is not a deliverable.
