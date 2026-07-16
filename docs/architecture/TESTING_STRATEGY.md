# Testing strategy

## Principles

Tests protect domain invariants, especially those that ordinary accuracy tests miss. The suite is deterministic, version-aware, and layered: fast unit/property tests on every change; integration/contract tests with real infrastructure in CI; representative end-to-end and load tests before release; scheduled data/model validation on actual versions.

Production source snapshots are not casually copied into Git. Test fixtures are minimal, synthetic, redistribution-approved, and deliberately include corrections, ambiguous identities, swapped fighters, future poison values, missing data, draws/no contests, and schedule changes.

## Test levels

| Level | Scope | Typical cadence |
|---|---|---|
| Unit/property | Pure transforms, domain services, schemas, calculations | Every change |
| Component | Module with controlled repositories/model doubles | Every change |
| Integration | PostgreSQL, Redis, object store, Celery eager/worker, artifact loading | Every pull request |
| Contract | OpenAPI/web client, source adapter fixtures, artifact/feature signature | Every pull request |
| End-to-end | Browser through API/database/worker | Pull request smoke; full before release |
| Data/model validation | Versioned real dataset/candidates | Ingestion/training and scheduled |
| Load/resilience | API/jobs/cache/dependency failures | Before release and material changes |
| Security | Static/dynamic/dependency/authz/tamper | Every PR/scheduled/release |

## Data tests

### Schema and parsing

- known source-schema fixtures parse to source-shaped types;
- unknown fingerprints quarantine and do not advance checkpoint;
- required/optional field changes are detected;
- date/time timezone and precision cases are explicit;
- unit conversion round trips, bounds, and original value/unit lineage;
- malformed, oversized, duplicate, reordered, and partial pages;
- output row accounting equals accepted + quarantined + policy-filtered.

### Missingness and duplicates

- null reason taxonomy is retained rather than zero/default;
- null/volume/category deltas produce expected warning/block status;
- source record idempotency under replay;
- semantic duplicate fight/event/quote/stat detection;
- raw identical bytes deduplicate storage without losing retrieval events.

### Identity

- exact source ID mapping;
- same-name different-person collision;
- alias spelling/case/Unicode candidate behavior;
- conflicting birth/physical/event evidence remains unresolved;
- merge/split history and referential redirect;
- unresolved identity blocks affected feature publication;
- duplicate fighter in one fight rejected.

### Relational and semantic

- exactly two eligible participants;
- round belongs to fight and statistic participant matches fight;
- result winner/status/method consistency;
- ending time/round within scheduled format;
- odds side and normalized probability bounds;
- ranking division/publication ordering;
- invalid joins create blocking quality issues rather than loss.

### Temporal leakage

- feature max source timestamp is strictly before target;
- prediction cutoff bound applies independently;
- same target fight statistics are excluded;
- a later correction is absent from historical knowledge view;
- current fighter record/profile/ranking cannot backfill history;
- closing/post-cutoff odds never enter earlier Model B rows;
- historical rating uses only pre-fight updates;
- rolling windows exclude the current/future row;
- future poison values cause no feature hash change;
- both orientations/horizons/simulations remain in one split group.

### Outcome leakage

Maintain deny-list and lineage rules for winner/result/method/ending round/time, source corner if outcome-associated, post-fight totals, current record, future rank, and post-cutoff market fields. Tests insert perfectly predictive poison columns and require schema/build failure.

## ML tests

### Reproducibility

- same approved inputs/config/image/seed produce identical manifests and predictions within declared numeric tolerance;
- Polars/Pandas interoperability preserves types/nulls/order;
- parallelism does not change row assignment or random sampling;
- training and inference feature parity on golden snapshots.

### Orientation symmetry

- winner p(A,B) equals 1 - p(B,A) after averaging;
- six paths remap and method marginals remain invariant;
- signed differences negate, invariant features remain;
- training half weights total one fight;
- canonical orientation does not correlate mechanically with target beyond chance diagnostics.

### Calibration and probability

- probabilities finite/in-range/sum correctly;
- calibration fits only calibration IDs;
- raw/calibrated artifacts are distinct/versioned;
- synthetic calibrated fixtures recover expected reliability;
- method reconciliation has zero coherence violations and bounded adjustment;
- duration survival curves are monotonic and bounded.

### Baseline and evaluation

- empirical, rating, and logistic baselines run for every eligible candidate;
- split/group manifests are disjoint and chronological;
- metric implementations match trusted small examples;
- missing/one-class cohort metrics report unsupported rather than crash;
- final-test access policy and report completeness.

### Drift and stability

- feature null/distribution drift on controlled shifts;
- categorical novelty and OOD response;
- debut/high-missing cases reduce support/confidence;
- prediction stability to serialization, dependency image, numeric precision, and small input perturbation;
- model/seed/bootstrap disagreement component;
- sensitivity to missing optional feature families.

### Serialization and loading

- artifact digest tampering fails;
- wrong API/feature/dependency compatibility fails readiness;
- model bundle loads in production image and runs golden/swap vectors;
- atomic hot swap preserves in-flight version and rollback works;
- untrusted/non-registry artifact URI rejected.

## Backend tests

### Unit

Domain policies for cutoff/mode routing, counterfactual bounds, confidence mapping, reconciliation, idempotency, authorization, cache keys, and state transitions. Repositories/model/queue are ports with controlled fakes.

### Database/integration

- Alembic upgrade from supported previous release and clean database;
- downgrade only where intentionally supported; operational rollback uses forward fix for data migrations;
- primary/foreign/unique/check/trigger constraints;
- transaction rollback and optimistic locking;
- keyset pagination stability;
- query-count/N+1 and representative EXPLAIN assertions;
- PostgreSQL timezone and JSON schema checks;
- Redis outage degradation and stampede behavior;
- Celery duplicate/retry/dead-letter/job durability;
- object/MLflow artifact failure.

### API contract

- OpenAPI schema snapshot/change classification;
- generated TypeScript client compiles;
- every endpoint's success, validation, auth, not-found, conflict, rate, and dependency cases;
- common error/request ID;
- ETag/cache-control and no cross-role cache leakage;
- prediction response version tuple/completeness/confidence;
- pure/market unavailability behavior;
- 202 job and status lifecycle.

### Model serving

- feature signature and missingness validation;
- dual-orientation execution;
- sync budget fallback to job;
- concurrent promotion/load/failure/rollback;
- model memory/startup/readiness;
- old frozen predictions never recompute on GET.

### Load and resilience

Use k6 or Locust scenarios for catalog, event card fan-out, cached/uncached prediction, job polling, and simulation submission. Verify p95 objectives, error budget, pool limits, queue backpressure, autoscaling signals, rate limits, and recovery from Redis/database/object/model-registry degradation. Never run destructive load tests against production canonical data.

## Frontend tests

### Component

- every reusable domain component across loading/empty/error/stale/unsupported states;
- probability and confidence semantics;
- counterfactual observed/modified separation and resets;
- charts have accessible summaries/tables;
- timezone/number formatting and long names/locales;
- fighter swap behavior.

### API integration

Mock Service Worker uses OpenAPI-valid fixtures. Tests cover retry/cancel, error mapping, ETag/stale data, pagination, 202 polling, expiration, and version changes. A contract suite runs against a real local API before release.

### Accessibility

axe on pages/components, keyboard traversal, focus/dialog behavior, screen-reader smoke passes, contrast, reduced motion, zoom/reflow, and non-color chart interpretation. Automated passing is necessary but insufficient.

### Responsive/visual

Screenshot tests at 360 px mobile, representative tablet, and desktop; dense tables, long names, missing images, warnings, and chart overflow. Visual changes require reviewed diffs.

### End-to-end

Playwright:

1. browse upcoming event to frozen fight prediction;
2. inspect uncertainty/explanation/version;
3. search fighters and compare/swap;
4. create bounded counterfactual and verify synthetic labels;
5. submit/poll Monte Carlo result;
6. filter historical fights and distinguish outcome from pre-fight prediction;
7. inspect cohort model performance;
8. handle no data/stale/error/rate-limit;
9. deny public admin and exercise authorized promote confirmation in a test environment.

## Test data management

- factories generate canonical entities with explicit times and provenance;
- golden fixtures are small and human-reviewable;
- source fixtures are encrypted/restricted if terms prohibit repository storage;
- database tests use per-worker schemas/containers and migrations;
- model tests use tiny deterministic estimators, with a separate production-artifact smoke suite;
- seeds and locale/timezone are fixed unless a property test varies them.

Never anonymize by changing timestamps in a way that destroys temporal test meaning.

## CI test matrix and gates

Pull request:

- format/lint/type/static/security/secret/license checks;
- Python/TypeScript unit/component/property tests;
- migration and PostgreSQL/Redis integration;
- source/OpenAPI/artifact contracts;
- frontend accessibility/build/smoke E2E;
- architecture link/required-section check.

Main/nightly:

- full browser matrix, source fixtures, data-quality sample, serialization image, longer property tests, dependency drift, vulnerability scan.

Release:

- staging migration/rollback, full E2E/accessibility, load/resilience smoke, champion bundle warm/swap/rollback, restore verification status, model evaluation gates, SBOM/image signing, and manual approvals.

Any temporal leakage, artifact integrity, migration, probability coherence, authorization, or required evaluation failure is blocking. Flaky tests are quarantined only with owner/expiry and cannot cover a release-critical invariant.

## Ownership and evidence

Each requirement ID maps to one or more named tests in the test-management manifest. CI publishes JUnit, coverage, OpenAPI diff, accessibility, migration, security, data-quality, and model-evaluation artifacts. Coverage percentage guides gaps but does not replace invariant and mutation/property testing.

