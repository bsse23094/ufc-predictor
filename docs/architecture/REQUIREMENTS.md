# Requirements

## Purpose and requirement language

This document turns the product brief into testable architecture requirements. **Must** denotes a release gate, **should** a strong default, and **may** a deferred option. IDs are stable and are referenced from tests, risks, milestones, and ADRs.

## Product outcomes

| ID | Requirement | Acceptance evidence |
|---|---|---|
| PRD-001 | The system must return calibrated win probabilities for both participants. | Probabilities are finite, each is in [0,1], and the decisive-fight pair sums to 1 within tolerance. |
| PRD-002 | It must return KO/TKO, submission, and decision probabilities plus fighter-specific paths. | Joint path probabilities reconcile with winner and method marginals. |
| PRD-003 | It must return finishing-round and duration distributions/expectations. | Values obey scheduled-round and duration bounds; evaluation report includes censored/edge-case policy. |
| PRD-004 | It must expose confidence and uncertainty as decomposed estimates, not one unexplained label. | Response includes data sufficiency, OOD, disagreement, missingness, and calibration metadata. |
| PRD-005 | It must support upcoming cards, fighter comparison, historical exploration, counterfactuals, Monte Carlo, similar matchups, explanations, and performance reporting. | Contract and end-to-end tests cover the public surfaces. |
| PRD-006 | Pure and market-informed predictions must be distinct products. | Mode and odds cutoff appear in every prediction; no silent mode substitution. |
| PRD-007 | Predictions for an event must be freezable before the event. | Immutable snapshot has an as-of time and a uniqueness constraint for fight/mode/horizon/model. |
| PRD-008 | The UI and API must describe outputs as uncertain estimates and must not recommend bets. | Content and accessibility review; forbidden-copy test. |

## Data and provenance

| ID | Requirement | Acceptance evidence |
|---|---|---|
| DAT-001 | Raw inputs must be preserved unchanged with checksum, retrieval time, source URI/key, HTTP metadata when relevant, license/terms note, and parser version. | Manifest-to-object checksum audit passes. |
| DAT-002 | Ingestion must be idempotent, incremental, retryable, rate limited, and capable of historical backfill. | Replaying a manifest creates no duplicate canonical facts. |
| DAT-003 | Each source adapter must detect schema/version and quarantine unknown or invalid inputs. | Contract fixtures and unknown-schema test. |
| DAT-004 | Canonical records must retain provider IDs and lineage to raw objects. | Random sample can trace canonical row to raw checksum. |
| DAT-005 | Fighter identity must use canonical IDs, source-scoped aliases, collision detection, and review status. | No unresolved/ambiguous identity enters a published feature dataset. |
| DAT-006 | Validation must report rejected counts and reasons; silent row dropping is forbidden. | Row accounting balances input = accepted + quarantined + explicitly filtered. |
| DAT-007 | Unit conversions and imputations must be named, versioned, and observable at feature level. | Feature metadata and missingness indicators exist. |
| DAT-008 | Raw datasets and trained binaries must not be committed to Git. | Repository policy and CI secret/large-file scan. |
| DAT-009 | Source audit must explicitly record access, coverage, identifier, legal, and stability unknowns. | DATA_SOURCE_AUDIT has no unsupported assertion of availability. |

## Temporal and leakage safety

| ID | Requirement | Acceptance evidence |
|---|---|---|
| TMP-001 | Every feature cell or snapshot must be derived solely from facts with latest_source_timestamp less than both prediction_as_of and target_fight_timestamp. | Hard temporal assertion blocks publication. |
| TMP-002 | Historical rankings must use publication/effective history, never the current ranking copied backward. | Ranking point-in-time fixture tests. |
| TMP-003 | Market features must use only snapshots observed at or before prediction_as_of and must state horizon/source. | Odds cutoff test and lineage query. |
| TMP-004 | Post-fight target statistics must not join into that fight's feature row. | Same-fight poison-value test. |
| TMP-005 | Duplicate orientations, simulations, and repeated snapshots for one fight must remain within one data split. | Group-disjoint split assertion. |
| TMP-006 | Split boundaries must be chronological at event granularity and the final test must remain untouched until release evaluation. | Versioned split manifest and access audit. |
| TMP-007 | Fit operations, including imputation, scaling, encoding, feature selection, OOD thresholds, and calibration, must use only their authorized split. | Pipeline provenance test. |
| TMP-008 | Corrections ingested later must not rewrite what was known for an earlier frozen prediction; reproduction must select the historical knowledge cutoff. | Bitemporal correction fixture. |

## ML behavior

| ID | Requirement | Acceptance evidence |
|---|---|---|
| ML-001 | A deterministic logistic baseline and rating-only baseline must precede complex models. | Evaluation report compares candidate to baselines. |
| ML-002 | Winner orientation must be outcome-independent in storage and symmetric at training/inference. | Swap test within declared probability tolerance. |
| ML-003 | Model A excludes all odds/market-derived fields; Model B includes only timestamped eligible market fields. | Feature allow-list checks. |
| ML-004 | Method probabilities must be coherent with winner paths, and round/duration must be coherent with scheduled rules. | Probability reconciliation property tests. |
| ML-005 | Calibration must be fitted on a dedicated chronological calibration split and versioned separately. | Registry bundle and calibration metrics. |
| ML-006 | Release evaluation must include all metrics and cohorts in MODEL_EVALUATION_PLAN. | Complete model card with coverage flags. |
| ML-007 | Insufficiently supported cohort metrics must be labeled, not suppressed or overinterpreted. | Minimum sample counts/confidence intervals. |
| ML-008 | Randomness must be seeded and environments/artifacts must be pinned. | Repeat run meets numerical tolerance. |
| ML-009 | Model F must expose data sufficiency, OOD, debut, missingness, calibration, and disagreement components. | Contract test against uncertainty schema. |
| ML-010 | Counterfactual values must be bounded, labeled synthetic, and kept separate from observed features. | Validation and UI semantics tests. |

## API and frontend

| ID | Requirement | Acceptance evidence |
|---|---|---|
| API-001 | The REST API must be versioned under /api/v1; health probes may remain at the root. | OpenAPI contract. |
| API-002 | Errors must use one structured schema with request ID and stable code. | Contract tests for 4xx/5xx cases. |
| API-003 | Every prediction response must include model, dataset, feature, cutoff, horizon, completeness, confidence, and explanation metadata. | Schema test. |
| API-004 | Public mutation-like analytical endpoints must be rate limited and idempotency-aware where jobs are created. | Load and duplicate-request tests. |
| API-005 | Expensive simulations, bulk inference, and explanation work must be asynchronous. | 202 job response and worker integration test. |
| API-006 | Administrative model and ingestion actions must require role-based authentication and audit logging. | Authorization matrix test. |
| WEB-001 | All required pages must support keyboard access, useful loading/error/empty states, and WCAG 2.2 AA contrast targets. | Automated and manual accessibility evidence. |
| WEB-002 | Server state must use TanStack Query; URL state must represent filters/comparisons; ephemeral UI state remains local. | Architecture lint/review. |
| WEB-003 | Version, freshness, data quality, and uncertainty must be visible near predictions. | Visual acceptance tests. |
| WEB-004 | Layouts must be usable at 360 px, tablet, and desktop widths. | Screenshot tests. |

## Operations and security

| ID | Requirement | Acceptance evidence |
|---|---|---|
| OPS-001 | Local, staging, and production use environment-based configuration with production secrets outside Git. | Deployment check. |
| OPS-002 | Migrations must run as a release job before application rollout and be backward compatible for rolling deployment. | Staging rollback drill. |
| OPS-003 | Structured logs, metrics, traces/request IDs, health, readiness, freshness, and error monitoring must be implemented. | Observability smoke test. |
| OPS-004 | PostgreSQL backups and object versioning must be tested through restore drills. | Recorded quarterly drill. |
| OPS-005 | Scheduled ingestion and retraining must be idempotent and alert on missed schedules, quality failure, and staleness. | Forced-failure test. |
| SEC-001 | Inputs must be schema validated; ORM parameterization must be used; uploaded/source files must be size/type limited and parsed in isolation. | Security tests. |
| SEC-002 | Artifacts and raw objects must be checksummed; promoted model manifests must be signed or integrity-bound to trusted storage. | Tamper test. |
| SEC-003 | Dependencies, images, code, secrets, and licenses must be scanned in CI. | Required CI checks. |
| SEC-004 | CORS must use an explicit allow-list; security headers and TLS are mandatory in public environments. | Dynamic configuration test. |
| SEC-005 | Source ingestion must apply politeness limits and comply with reviewed access terms. | Source audit approval and adapter configuration. |

## Non-functional priorities

Priority order is correctness and leakage safety, reproducibility, understandable uncertainty, operability, latency, then feature breadth. This may delay impressive product features; it prevents a fast but invalid platform.

Data scale is expected to be moderate for historical UFC data, so PostgreSQL plus Parquet is preferred over distributed systems. The architecture keeps replaceable ports around storage and execution, accepting some abstraction work now to avoid premature infrastructure.

## Explicit assumptions requiring validation

- Source access and permitted retention are not yet legally or technically confirmed.
- Exact source fields, historical depth, timestamps, and stable identifiers are unknown until the audit/backfill.
- Event bout order and start time may change; snapshots therefore preserve both observed schedule and ingestion time.
- Method labels, overturned results, draws, and no contests require a canonical taxonomy approved during data implementation.
- Short-notice, cardio, pressure, judging, and pre-UFC features may have insufficient reliable coverage and are nullable/experimental until audited.
- Public traffic, budget, and availability targets are initial planning assumptions.

No implementation may convert an assumption into a guaranteed fact without an ADR or source-audit update.

## Traceability

Milestone acceptance criteria are in [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md). Test ownership is in [TESTING_STRATEGY.md](TESTING_STRATEGY.md); risks and mitigations are in [RISK_REGISTER.md](RISK_REGISTER.md).

