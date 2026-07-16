# Deployment architecture

## Environments

| Environment | Purpose | Data/model policy | Availability |
|---|---|---|---|
| Local | Fast development and deterministic integration | Synthetic/small approved fixtures; local artifacts; optional explicitly obtained raw data ignored by Git | Developer machine |
| Staging | Production-like migrations, integrations, candidate shadow and E2E | Sanitized/approved subset or separate source access; staging registry aliases | Ephemeral or low-cost always-on |
| Production | Public product, scheduled ingestion, frozen predictions | Approved full canonical data and champion registry only | Initial 99.5% objective |

Configuration is environment-driven and validated at startup. Never share databases, buckets, Redis namespaces, signing keys, or model aliases across environments.

## Container services

- web: Next.js standalone server or edge-compatible deployment;
- api: FastAPI ASGI, non-root, read-only filesystem except bounded artifact cache;
- worker: same trusted Python base with queue-specific command/resources;
- scheduler: platform cron invoking idempotent jobs; Celery Beat local fallback;
- postgres: local container, managed service outside local;
- redis: local container, managed/small hosted outside local;
- mlflow: local/staging service; production metadata database/object artifact store or a managed equivalent;
- object-store: local MinIO optional; S3-compatible managed production;
- migration: one-shot Alembic release job;
- reverse proxy/edge only where hosting platform does not provide TLS/CDN.

Training is an ephemeral job/container using services/ml, not a permanent web/API process. Large training and ingestion should not contend with API worker CPU.

## Local-first development

Recommended topology:

    Docker Compose: postgres, redis, optional minio/mlflow
    Host or container: api, web, celery worker
    DuckDB + Parquet: ignored local data directories

Use pinned language/tool versions, one command to start dependencies, migrations/seed fixtures, and separate fast developer processes with hot reload. Optional profiles keep MLflow/MinIO/worker out of the shortest feedback loop. Production-like object storage can be tested without requiring cloud credentials.

Benefits: cheap, offline-capable, debuggable. Trade-off: a developer laptop does not reproduce managed networking/autoscaling; staging is the parity gate.

## Low-cost public MVP

Preferred initial deployment:

- managed static/Next hosting or one small web service;
- one small container host for API and one worker process, independently restartable;
- managed PostgreSQL with automated backups;
- small managed Redis or protected host-local Redis if broker loss is acceptable and jobs are durable in PostgreSQL;
- inexpensive S3-compatible versioned object storage;
- GitHub Container Registry;
- platform cron for ingestion/freshness/card snapshots;
- hosted Sentry and lightweight metrics/log service tiers.

API and worker may share a VM initially but run as separate containers with resource limits. PostgreSQL should be managed before adding Kubernetes. This minimizes operator burden and cost; the trade-off is a smaller failure domain and limited horizontal scaling. Scheduled training can run on an on-demand CI/self-hosted job if data/source licenses and compute duration permit, with artifact upload and no production promotion from untrusted forks.

No raw/model files live in an ephemeral container filesystem except cache.

## Scalable production

When measurements justify:

- CDN/WAF/load balancer;
- multiple stateless web and API replicas across failure zones;
- managed multi-zone PostgreSQL, connection pooler, read replica for analytics;
- managed Redis with appropriate persistence/failover;
- separate autoscaled queue workers by workload;
- versioned object store with lifecycle/replication;
- orchestrated scheduled/ephemeral ingestion/training;
- optional dedicated inference service and pgvector/index service;
- OpenTelemetry collector, managed metrics/logs/traces;
- Kubernetes/ECS/Cloud Run-style orchestration according to team expertise.

Kubernetes is not an MVP requirement. It offers scheduling and standardization but imposes substantial operating cost.

## CI/CD

### Pull request

1. dependency install from locks and cache;
2. lint, format check, Python/TypeScript types;
3. unit/property/component tests;
4. PostgreSQL/Redis integration and Alembic migration test;
5. OpenAPI/client contract and web build;
6. security/secret/license/IaC scans;
7. architecture documentation validation;
8. optional preview web/API with synthetic fixtures.

### Main build

1. build minimal multi-stage images once;
2. generate SBOM, scan, sign/attest image digest;
3. publish immutable digest to registry;
4. deploy the same digest to staging;
5. run migration, E2E, accessibility, bundle load/swap, and smoke load tests;
6. require environment approval;
7. deploy production by digest, migration-first, rolling/canary;
8. verify probes, golden prediction, freshness, errors, then mark release.

Do not rebuild between staging and production. Frontend and API compatibility are checked before rollout.

## Database migrations

- Alembic revisions are reviewed and tested from the last supported production snapshot and clean database.
- Release job acquires a deployment lock and applies migrations before new application rollout.
- Use expand/migrate/contract: add nullable/table/index concurrently where possible; deploy dual-compatible code; backfill via resumable job; enforce/remove only later.
- Backups/checkpoints precede risky migrations.
- Application rollback normally keeps a backward-compatible expanded schema. Destructive downgrade is not the primary rollback mechanism.
- Long indexes use PostgreSQL concurrent operations with Alembic transaction care.

## Data and model workflows

### Scheduled ingestion

- frequent source-specific cadence based on audit and terms;
- event schedule/upcoming data more frequent than stable history;
- platform scheduler creates an idempotent ingestion_run;
- publish only after quality gates; current dataset alias does not advance on failure;
- bounded recent refetch captures corrections; full backfills are manual/low priority.

### Scheduled prediction snapshots

- trigger after approved card/data change and at declared pre-event horizons;
- capture schedule and odds cutoff;
- precompute explanation/similarity where affordable;
- freeze immutable snapshot; do not overwrite when the card changes.

### Retraining

- quarterly evaluation or after enough new labeled fights/material drift;
- ephemeral job creates candidate only;
- automated walk-forward/final policy report and staging shadow;
- human promotion through registry alias;
- no automatic promotion solely because a schedule fired.

## Rollbacks

Application: route traffic to previous signed image digest; schema remains compatible.  
Model: atomic alias compare-and-set to the previous validated bundle, API warm/smoke then switch.  
Dataset: current alias returns to previous approved manifest; downstream rebuild impact is recorded.  
Frontend: previous immutable build.  
Migration: prefer forward fix; restore only for severe integrity failure under runbook.

Every rollback records actor/reason and verifies golden requests. Frozen predictions retain original version references rather than changing to the rollback.

## Backups and disaster recovery

MVP:

- managed daily PostgreSQL backups with point-in-time recovery if affordable;
- encrypted object storage versioning and lifecycle;
- registry/container images retained by release policy;
- infrastructure/config in code; secrets in manager;
- quarterly restore to isolated staging;
- target RPO 24 hours and RTO 4 hours initially.

Scalable production tightens RPO with continuous WAL/PITR, multi-zone service, replicated object storage, and more frequent restore drills. A backup is not accepted until restored and integrity/golden queries pass.

## Configuration and environment variables

Settings are namespaced by component and validated:

- environment/build/release identifiers;
- PostgreSQL/Redis/object/MLflow connections through secret references;
- model aliases/cache paths and integrity policy;
- source enable/rate/policy configuration;
- CORS/OIDC/JWT/rate limits;
- Sentry/OpenTelemetry/log level;
- worker queues/concurrency and simulation caps;
- public web/API URLs and feature flags.

The exact variable contract is in TERRA_HANDOFF. Defaults are safe for local only; production fails closed when required security configuration is missing.

## Cost controls

- cache immutable reads and precompute event predictions;
- exact similarity rather than managed vector database;
- CPU tabular inference in process;
- lifecycle derived/interim objects;
- scheduled/on-demand training, no idle GPU;
- one managed PostgreSQL rather than separate online feature database;
- sampling for traces/logs without sampling errors/audit;
- queue quotas and simulation caps;
- scale workers to zero where platform permits.

Cost savings never permit dropping raw provenance, backups, temporal validation, or artifact integrity.

## Release acceptance

- migration and backward compatibility pass;
- required model bundle loads and golden/swap predictions pass;
- web/API contracts and E2E pass;
- probes and dashboards healthy;
- restore status within policy;
- no critical vulnerability or secret finding;
- source freshness/quality status is visible;
- rollback target identified and tested;
- release and model/dataset versions recorded.

