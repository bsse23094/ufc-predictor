# Observability plan

## Goals

Observability must answer:

1. Is the product available and fast?
2. Are sources, datasets, and predictions fresh?
3. Did any data disappear, duplicate, change schema, or violate time?
4. Which model/data/feature version produced an output?
5. Is probability quality or cohort behavior degrading after labels arrive?
6. Can an operator diagnose and safely roll back without exposing sensitive data?

Use structured logs, Prometheus-compatible metrics, OpenTelemetry traces/request propagation, Sentry-equivalent error grouping, and immutable audit events. A small deployment may use hosted low-cost services, but the event/metric names remain portable.

## Correlation and context

Propagate:

- request_id and trace_id from edge through API, queue headers, worker, database metadata/log context;
- job_id, ingestion_run_id, dataset_version, feature_set_version;
- prediction_id, target fight, cutoff/horizon, mode, model/calibration versions;
- source key/schema/parser version;
- deployment environment, service, release/image digest.

Do not put fighter names, raw payloads, odds values, tokens, email, signed URLs, or unbounded feature vectors in metric labels. IDs belong in logs/traces, while metrics use bounded dimensions.

## Structured logs

JSON log fields:

- timestamp, severity, service/module, environment/release;
- event_name, message, request/trace/job/run IDs;
- duration/status/outcome/error code/retryability;
- bounded version/capability fields;
- safe actor/target for privileged actions through separate audit stream.

Log at info for lifecycle summaries, warn for degradations/retries/quality warnings, error for terminal unexpected failure, and debug only locally/temporarily. Stack traces go to restricted error monitoring. Central redaction removes auth, cookies, DSNs, source secrets, file contents, and sensitive metadata. Sampling may reduce successful request logs; never sample audit events, errors, leakage violations, promotions, or quality publication failures.

## Metrics

### API/web

- HTTP request count, duration histogram, in-flight, response size, and error count by route template/method/status class;
- cache hit/miss/error/lock wait;
- database pool use/wait, query duration by operation name, transaction failures;
- model inference duration/load time/memory by task/mode/model bounded version;
- prediction route mode, supported/unsupported count, completeness band, OOD/confidence tier;
- rate-limit and validation rejections by endpoint/code;
- web Core Web Vitals and frontend error rate by release/page group.

### Workers and queues

- queued/running/succeeded/failed/retried/expired jobs by type/queue;
- queue depth and oldest-message age;
- runtime, time-to-start, iterations/records processed;
- dead-letter/terminal error;
- worker concurrency, memory, CPU, restart.

### Ingestion and data

- last successful retrieval/observation/publication timestamp by source;
- raw objects/bytes/checksum duplicates;
- input/accepted/quarantined/filtered records and row-accounting delta;
- schema fingerprints and unknown-schema count;
- missing/duplicate/identity-conflict/invalid-join counts;
- temporal violation and future-poison failures;
- dataset build duration/status/current version age;
- feature null/completeness and lineage max lag by family/cohort.

Temporal_violation_total must always be zero for published data; any positive value is critical.

### Models

At prediction time:

- prediction probability distribution, entropy, confidence tier, OOD, missingness, model disagreement, pure/market coverage, horizon;
- reconciliation adjustment and probability-coherence violation;
- latency/load/error.

After delayed outcomes:

- log loss, Brier, ECE/calibration slope/intercept, ROC/PR/accuracy as secondary;
- method class scores, duration/survival scores;
- coverage/risk by confidence;
- performance by bounded cohort and horizon;
- feature/prediction drift against training/reference;
- label delay/coverage.

Metrics requiring sparse high-cardinality cohorts are computed as scheduled tables/reports rather than Prometheus labels.

## Tracing

Trace representative:

- web server fetch -> API router -> use case -> repository/cache;
- prediction -> feature lookup/build -> model bundle -> orientation calls -> calibration/reconciliation -> persist;
- job submit -> queue -> worker -> artifact/result;
- ingestion discover/fetch/raw persist/parse/validate/publish;
- model alias poll/download/verify/warm/swap.

Instrument operation names, not raw SQL or feature payloads. Sample successful catalog traces lightly, predictions/jobs more heavily, and always retain errors/slow traces within privacy/cost limits.

## SLOs and indicators

Initial MVP service objectives:

| SLO | Indicator | Objective |
|---|---|---:|
| Public read availability | non-5xx eligible requests / eligible requests | 99.5% monthly |
| Cached read latency | route p95 | under 250 ms |
| Uncached sync prediction latency | prediction p95 | under 1.5 s |
| Job acknowledgement | accepted p95 | under 500 ms |
| Standard simulation | completion p95 | under 30 s |
| Published temporal integrity | violations in approved dataset | exactly zero |
| Prediction coherence | invalid probability outputs | exactly zero |

Source freshness uses source-specific objectives set after the audit; one universal freshness SLO would mislead. Show observed, retrieved, and published times plus expected cadence.

## Dashboards

1. **Public service:** traffic, availability, p50/p95/p99, errors, cache, web vitals, release markers.
2. **Prediction runtime:** volume/mode/horizon, latency, bundle versions, unsupported/OOD/completeness, reconciliation.
3. **Queues/workers:** depth/age/runtime/failure/retries by queue.
4. **Data freshness/quality:** per-source times, schema, row accounting, quarantine, identity, dataset publication.
5. **Model performance/drift:** delayed metrics, calibration, cohorts, coverage, feature/prediction drift, promotion markers.
6. **Infrastructure/cost:** CPU/memory/disk, PostgreSQL/Redis/object requests, pool, worker utilization, estimated cost.
7. **Security/audit:** rate/auth failures, artifact tamper, admin actions, unusual backfills/promotions without sensitive labels.

Version/promotion/deployment annotations are mandatory; otherwise changes cannot be correlated to regressions.

## Alerts and response

| Severity | Condition | Action |
|---|---|---|
| Critical | published temporal/coherence violation, artifact integrity failure, failed model promotion leaving no champion, data corruption, sustained public outage | Page; disable affected capability/rollback; preserve evidence |
| High | API error-budget burn, queue oldest age above workflow objective, database saturation, unknown source schema blocking current events, stale upcoming data | Page/on-call during supported hours; follow runbook |
| Medium | source missed expected cadence, quarantine/null/identity spike, drift/OOD or calibration threshold breach, backup failure | Ticket/chat alert and investigate before next publish/promotion |
| Low | cost/bundle growth, noncritical retry, deprecation usage | Dashboard/digest |

Use multi-window burn-rate alerts instead of noisy single thresholds for SLOs. Data/model thresholds are established from baseline distributions and versioned; a performance alert never automatically promotes/retrains.

## Runbooks

Required runbooks:

- API 5xx/latency and dependency outage;
- PostgreSQL pool/saturation and restore;
- Redis loss/queue recovery;
- stuck/failing task and poison message;
- source rate limit/ban, unknown schema, or freshness failure;
- data-quality/identity/temporal violation;
- model load/integrity/prediction anomaly;
- promotion rollback;
- corrupted/incorrect frozen prediction correction;
- leaked secret/security incident;
- cost spike/disk/object growth.

Each identifies symptoms, dashboards/queries, safe containment, rollback, verification, escalation, and post-incident work. Commands use explicit environment/targets and avoid destructive defaults.

## Model monitoring workflow

Outcomes arrive later than predictions, so:

1. Freeze prediction snapshot and cutoff before event.
2. Ingest verified result under its own knowledge time.
3. Match result to eligible published prediction without rewriting it.
4. Compute metrics only after label quality/maturity policy passes.
5. Aggregate by model, mode, horizon and supported cohorts.
6. compare with evaluation bounds/champion and open a review on drift.
7. Retrain candidate if scheduled/justified; promotion remains separate.

Market and pure metrics use matched coverage sets as well as their natural coverage. Corrections recompute a new monitoring report version with audit lineage.

## Data transparency

The public freshness API/page exposes per-source last successful observation/retrieval/publication, expected cadence, current dataset version, prediction cutoff, broad quality warnings, and known gaps. Internal dashboards contain raw evidence and entity IDs. This split gives users meaningful transparency without disclosing licensed data, filesystem paths, or exploit details.

## Retention

- Metrics: high resolution 15-30 days, downsampled aggregates 12-24 months initially.
- Application logs: 30-90 days based on cost/security policy.
- Error traces: 90 days or provider policy.
- Audit, promotion, approved data/model manifests, and incident records: long-term/indefinite.
- Distributed traces: 7-30 days sampled.

These are starting points subject to legal/source/privacy review. Retention must preserve the prediction reproducibility contract even if operational telemetry expires.

