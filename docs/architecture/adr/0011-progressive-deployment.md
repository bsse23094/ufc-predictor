# ADR-0011: Progressive deployment from local-first to managed MVP

Status: Accepted  
Date: 2026-07-17

## Context

The platform should be affordable initially yet preserve a path to scale. Kubernetes/microservices can absorb disproportionate effort, while a single unmanaged database would put irreplaceable canonical/audit state at risk.

## Decision

Use three progressive topologies:

1. local Docker Compose dependencies with host/container applications, DuckDB/Parquet, optional MinIO/MLflow;
2. low-cost public MVP with managed PostgreSQL, versioned object storage, small Redis, separate API/worker containers, hosted web/edge, platform cron and hosted error/metrics services;
3. scale to replicated API/workers, managed failover, read replicas, orchestration, and optional dedicated inference/vector services only from measurements.

Build immutable signed images in CI, promote the same digest through staging, use migration-first expand/contract releases, and retain tested app/model/data rollback targets.

## Rationale

Managed durable state/backups reduce the highest operational risk, while simple stateless compute keeps cost and cognitive load low. The architecture already defines component ports and queues, so scaling need not be pre-purchased.

## Consequences

Positive:

- quick, inexpensive developer and MVP operation;
- production durability where it matters;
- reversible releases and clear growth path;
- avoids premature Kubernetes.

Negative:

- initial single compute host may be a failure domain;
- staging/local cannot perfectly match autoscaling/network;
- later scale may require infrastructure migration;
- managed services have baseline cost/vendor-specific configuration.

## Alternatives

- Kubernetes from day one: flexible but operationally excessive for scale/team.
- Fully serverless: low idle cost but worker/training/runtime/model-cache constraints and provider coupling.
- One VM including database: cheapest, but backup/recovery/upgrade risk is too high for canonical state.

## Revisit

Choose exact providers/IaC after measured load, budget, residency, and team expertise. Scale when SLO/cost metrics justify it, not from speculative traffic.

