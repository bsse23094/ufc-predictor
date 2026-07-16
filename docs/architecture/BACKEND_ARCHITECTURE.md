# Backend architecture

## Decision

Build a FastAPI modular monolith with SQLAlchemy 2 repositories, Alembic migrations, PostgreSQL, Redis, and Celery workers. Load approved model bundles inside API processes for low-latency predictions; send simulations, bulk work, ingestion, snapshot generation, and expensive explanations to workers.

This hybrid design avoids a premature inference microservice and network hop while preserving a worker boundary for heavy workloads. It requires each API replica to hold model memory and coordinate hot reload; a dedicated model service becomes appropriate only when model size, independent scaling, hardware, or release cadence demands it.

## Application layers

    HTTP routers and dependency injection
                 |
    Pydantic request/response contracts
                 |
    application use cases / transaction boundary
                 |
    domain policies and services
                 |
    repository, cache, model-runtime, queue ports
                 |
    SQLAlchemy/PostgreSQL, Redis, MLflow/object storage, Celery

Routers do not issue SQL, load artifacts, or compute features. Domain code does not import FastAPI, SQLAlchemy models, or Celery. This separation adds mapping types but makes temporal, authorization, and serving behavior testable.

## Module map

| Module | Responsibility |
|---|---|
| core | Settings, lifecycle, errors, request IDs, logging, metrics, security headers |
| auth | JWT validation/issuance integration, principals, roles, audit context |
| fighters | Directory, profile, aliases/attributes, history |
| events | Event/card queries and upcoming lifecycle |
| fights | Fight detail, participants, rounds/statistics/scorecards policy |
| predictions | Request routing, feature retrieval/build, inference, reconciliation, snapshots |
| explanations | Stored/global/local explanation retrieval and jobs |
| simulations | Counterfactual validation and Monte Carlo job lifecycle |
| similarity | Eligible historical vector retrieval and distance explanation |
| models | Public model cards/metrics and administrative promotion/rollback |
| data | Freshness, ingestion and quality summaries |
| jobs | Public/user-scoped asynchronous job status |
| admin | Ingestion triggers, dataset/model governance, audit views |

Module tables are written only through the owning repository. Cross-module operations use application services; they never rely on circular router calls.

## Transaction and database policy

- One short SQLAlchemy AsyncSession transaction per use case.
- PostgreSQL constraints enforce identity and immutability rules where possible.
- Explicit eager loading avoids hidden N+1 queries.
- Read endpoints use keyset pagination; offset is acceptable only for bounded admin views.
- Read models may denormalize approved aggregates/materialized views, while canonical normalized facts remain authoritative.
- Predictions/jobs use an idempotency key plus requester scope and canonical request hash.
- External artifact/object calls occur outside open database transactions.
- Alembic uses expand/migrate/contract changes for deploy compatibility.

## Model runtime

At startup/readiness:

1. Resolve configured model aliases from a signed/integrity-checked promotion manifest.
2. Download/cache artifacts by immutable digest.
3. verify digest, safe expected format, dependency/API compatibility, and feature signature.
4. load estimator/calibrator/reconciler/OOD references into a ModelBundle.
5. run golden smoke vectors and swapped-orientation check.
6. mark ready only when required pure champion loads; market/method/duration capability is reported separately.

The runtime stores an atomic map from mode/version to immutable bundle. A watcher polls for alias changes, warms the new bundle, runs health checks, atomically swaps the pointer, and retains the previous version for a bounded rollback window. In-flight requests keep their selected bundle reference. Bundle selection/version is logged and persisted.

Artifact deserialization is a code-execution risk. Prefer constrained formats where supported; otherwise load only trusted, digest-verified artifacts built by CI in the matching image. Never load a user-supplied pickle.

## Feature retrieval

Scheduled predictions use precomputed PostgreSQL feature snapshots keyed by fight, cutoff/horizon, dataset, and feature version. Ad hoc matchup requests call the same ML feature-builder port, normally via a bounded synchronous path if histories are already materialized. If building exceeds budget, return a 202 job resource.

The API never constructs feature SQL from the public payload. Counterfactuals load a base approved snapshot, validate modifications, and recompute only declared dependent nodes through the versioned graph.

## Request flow for prediction

1. Validate IDs/context/mode/as-of and authorize/rate-limit.
2. Resolve canonical fight or hypothetical context.
3. Select explicit model alias/version and compatible feature/dataset policy.
4. Retrieve/build immutable feature snapshot; validate content/signature/completeness.
5. Run both orientations.
6. calibrate, remap/average, and reconcile winner/method/duration.
7. assess OOD/data/ensemble confidence.
8. persist immutable snapshot unless request policy is non-persisting preview.
9. return response with version tuple and explanation status.

Failures are typed: missing data never becomes a generic 500 and market unavailability never becomes a mislabeled pure result.

## Background jobs

Celery with Redis is selected for its mature retries, routing, scheduling ecosystem, and operational familiarity. It is heavier than Dramatiq, but the platform needs multiple periodic and long-running workflows.

Queues:

- ingestion-low: polite fetch/backfill;
- data: canonicalization, identity, feature snapshot;
- training: orchestrates external/ephemeral training jobs, never runs large training in an API pod;
- inference: bulk card snapshot/explanations;
- simulation: Monte Carlo/counterfactual batches;
- maintenance: freshness aggregation, cleanup, drift evaluation.

Tasks are idempotent and accept immutable IDs, not large serialized data. Durable output goes to PostgreSQL/object storage; Redis results are short-lived. Retry only known transient errors with exponential backoff/jitter. Poison messages move to a dead-letter/failure state and alert. Celery Beat is acceptable locally; production scheduled jobs should use the platform scheduler to avoid single-beat fragility.

## Authentication and authorization

Public catalog/read/prediction endpoints require no account in the MVP but use IP/token rate limits. Admin endpoints require short-lived signed JWT access tokens issued by a trusted OIDC provider or a tightly scoped internal auth flow; production should prefer OIDC. Roles:

- viewer: optional saved/user-scoped job access;
- analyst: internal quality/model reports;
- model_manager: stage/promote/rollback models;
- data_operator: ingestion/backfill/quality decisions;
- admin: role management, not automatically a model approver.

Sensitive actions may require two distinct roles/approvals later. Every privileged change emits an append-only audit event.

## Cache policy

Redis keys include API contract version and relevant entity/data/model/version/cutoff:

- stable fighter/event history: 5-30 minutes with ETag and explicit invalidation;
- upcoming cards/freshness: 30-120 seconds;
- frozen predictions/model metrics: long TTL because immutable, content-addressed;
- ad hoc prediction: 5-30 minutes keyed by canonical request hash;
- readiness: process-local/very short;
- simulations: durable result resource, no recomputation for idempotent duplicate.

Cache failure degrades reads to PostgreSQL/model paths; it must not change prediction mode/version. Stampede protection uses request coalescing/short locks. No secrets or raw JWTs are cached.

## Error model

All API errors use:

    {
      "error": {
        "code": "stable_machine_code",
        "message": "safe user-facing message",
        "details": [{"field": "...", "reason": "..."}],
        "request_id": "...",
        "retryable": false
      }
    }

422 is schema/domain validation, 401 unauthenticated, 403 forbidden, 404 absent/hidden, 409 state/idempotency conflict, 429 rate limit, 503 dependency/model/data unavailable, and 500 an unexpected request-ID-bearing failure. Internal source paths, SQL, model internals, and stack traces are never returned.

## Concurrency and resource controls

- Async I/O for database/cache/object metadata; CPU inference runs in bounded thread/process execution or synchronous native library calls proven not to block excessively.
- Cap request body, query complexity, page size, simulation draws, SHAP work, and concurrent expensive operations.
- Separate API and worker CPU/memory limits.
- Database and Redis pools are bounded below server concurrency.
- Graceful shutdown stops new requests, drains in-flight work, and never abandons a database transaction.

## Health

- GET /health: process liveness only; no network dependencies.
- GET /readiness: database, required model bundle, migration compatibility, and critical configuration; Redis may be degraded rather than fatal for read-only service.
- GET /data/freshness: user-facing per-source/derived freshness and known issues, never a deployment probe.

## Model service extraction trigger

Revisit an independent service when at least one is measured:

- bundles cannot fit economically per API replica;
- GPU/special hardware is required;
- inference scales materially differently from API reads;
- model release cadence requires independent deployment;
- multiple consumers need a stable inference protocol;
- isolation/compliance demands a harder boundary.

An internal PredictionPort and versioned request schema make extraction possible. Extracting earlier would add service discovery, network failure, distributed tracing, and cross-service versioning without demonstrated benefit.

