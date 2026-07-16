# ADR-0005: Celery with Redis for background jobs

Status: Accepted  
Date: 2026-07-17

## Context

The system needs ingestion/backfills, feature builds, card predictions, explanations, Monte Carlo, cleanup, and training orchestration. Tasks require routing, retries, scheduling integration, status, and operational visibility.

## Decision

Use Celery for background task execution and Redis as the initial broker/cache. Store authoritative job state/results in PostgreSQL/object storage. Use platform cron/scheduler in production to enqueue idempotent jobs; Celery Beat is a local fallback.

## Rationale

Celery has mature routing, retry, worker, monitoring, and Python ecosystem support. Although heavier than newer alternatives, it covers the varied workflow set and is familiar to operators.

## Consequences

Positive:

- queue isolation and independent worker scaling;
- established retry/routing/scheduling patterns;
- supports local Compose and hosted Redis.

Negative:

- operational and configuration complexity;
- at-least-once delivery requires idempotency;
- Redis broker loss/visibility needs careful handling;
- Celery is not a full data workflow orchestrator.

Tasks pass immutable IDs, use bounded retries, persist durable state, and expose dead-letter/failure alerts. Training is orchestrated as an external job rather than serialized inside a task.

## Alternatives

- Dramatiq/RQ: smaller and simpler, but less complete scheduling/routing ecosystem for this workload.
- Temporal/Prefect/Dagster: stronger durable workflows/data orchestration but more infrastructure and concepts for MVP.
- In-process FastAPI background tasks: not durable and tied to API lifecycle.

## Revisit

Revisit if multi-step workflow recovery/backfill lineage becomes unmanageable, broker semantics fail requirements, or team adopts a data orchestrator. Migration must preserve idempotency/job API.

