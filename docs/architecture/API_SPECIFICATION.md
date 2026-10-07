# API specification

> This is a target contract, not a description of every current route. As of
> 2026-10-08, the implemented matchup route supports only the pure winner model,
> returns null for method/round distributions, defaults `persist` to false, and
> rejects durable snapshots with 501. The upcoming route returns 404 when no
> verified future card exists. See the
> [implementation audit](../IMPLEMENTATION_AUDIT_2026-10-08.md).

## Conventions

Canonical endpoints are under /api/v1 except root probes /health and /readiness. JSON uses snake_case to match Python and generated clients. Times are timezone-aware ISO 8601 UTC; dates are ISO 8601 dates; IDs are UUIDs unless a schema explicitly says opaque string. Probabilities are numbers in [0,1]. Pagination is keyset-based:

    {"items": [...], "next_cursor": "opaque-or-null", "has_more": false}

OpenAPI is the source for generated TypeScript shared types. Unknown request fields are rejected on analytical/admin mutations. Responses include X-Request-ID; immutable resources use ETag. The common error is defined in BACKEND_ARCHITECTURE.

Expected latencies below are initial server-side p95 objectives, excluding client network, and are not SLAs.

## Core schemas

### FighterSummary

fighter_id, display_name, optional nickname, nationality, current/division summaries when actually derived, profile_image policy field, and data_quality summary. Historical/physical claims carry observed_at/provenance summaries in FighterDetail rather than pretending to be timeless.

### FightSummary

fight_id, event summary, scheduled timestamp, status, scheduled rounds, division, two participants in display order, verified result summary when available, and freshness.

### FeatureValue

name, observed_value, effective_value, unit, source_status, missing_reason, is_counterfactual, and optional allowed_range. Public responses expose selected interpretable values, not the full proprietary/internal vector.

### Confidence

overall_tier, supported, probability_entropy, data_sufficiency, ood_risk, missingness_risk, model_disagreement, calibration_uncertainty, reasons, and policy_version. Component semantics are documented; none is labeled probability_correct.

### Prediction

- prediction_id, mode, status, prediction_timestamp, prediction_as_of, target_fight_timestamp, horizon_seconds;
- fighter_a/fighter_b summaries and calibrated winner probabilities;
- joint paths by fighter and method marginals;
- round/duration distribution and expectations with conditioning labels;
- Confidence and input_completeness by feature family;
- model_version/model_bundle_version, calibration_version, dataset_version, feature_set_version, pipeline_version;
- feature_snapshot_hash and request/input hash;
- market metadata only for market mode;
- explanation: status, explanation_id, algorithm/version, baseline cohort;
- warnings, intended_use, and decisive-outcome conditioning.

### Job

job_id, type, state, created_at, started_at, completed_at, progress (coarse), result_url, error (safe typed form), expires_at, and version metadata. Anonymous job retrieval uses an unguessable scoped token or same-session credential; admin jobs require authorization.

## Validation shared by endpoints

- Page limit defaults to 25 and is at most 100.
- Search text is trimmed, Unicode-normalized for lookup, 2-100 characters, and never interpolated into SQL.
- IDs must parse and must reference visible canonical records.
- as_of cannot be in the future beyond a small clock-skew allowance and must precede target fight time.
- Two fighters must be distinct and supported in a compatible context.
- Model mode is pure or market; market requires eligible timestamped input.
- Simulation count defaults to a versioned safe value and is bounded (initial API contract may allow 1,000-100,000 after load tests).
- Counterfactual fields are allow-listed; each has hard and empirical bounds and dependent fields are recomputed.
- include parameters are enum allow-lists, not arbitrary relation expansion.

## Catalog and fight endpoints

| Endpoint | Request schema and validation | Response schema | Auth | Errors | Cache | Latency | Database/model interaction |
|---|---|---|---|---|---|---:|---|
| GET /api/v1/fighters | query, optional division/status; cursor; limit. Search length and enum validation. | Page[FighterSummary] | Public | 422 invalid query; 429 | 5 min, key by query/data version; ETag | 250 ms | PostgreSQL fighter search/read view; no model |
| GET /api/v1/fighters/{fighter_id} | UUID path; optional as_of | FighterDetail with aliases safe for display, physical observations, summary ratings, quality/freshness | Public | 404; 422; 429 | 10 min by fighter/as_of/dataset | 250 ms | PostgreSQL point-in-time profile/read models; no model |
| GET /api/v1/fighters/{fighter_id}/history | UUID; cursor/limit; optional status/from/to | Page[FightSummary] plus summary trends | Public | 404 fighter; 422 range; 429 | 5 min; ETag | 350 ms | PostgreSQL participant/fight/event joins and approved aggregates; no online model |
| GET /api/v1/events | cursor/limit; from/to; status | Page[EventSummary] | Public | 422; 429 | 2 min by filters/data version | 250 ms | PostgreSQL event read view |
| GET /api/v1/events/upcoming | optional horizon_days within policy; cursor/limit | Page[EventSummary] with card completeness and last_updated | Public | 422; 429; 503 data unavailable | 30-60 s; stale-while-revalidate | 250 ms | PostgreSQL latest known schedule; no model |
| GET /api/v1/events/{event_id} | UUID; optional include=card,prediction_summaries | EventDetail and ordered FightSummary list; optional frozen prediction summaries | Public | 404; 422 include; 429 | 60 s upcoming, immutable/long for historical | 400 ms | PostgreSQL; batch prediction query, no new inference |
| GET /api/v1/fights/{fight_id} | UUID; include enum summary,rounds,scorecards,features | FightDetail with provenance and optional approved display features | Public | 404; 403 restricted source; 422; 429 | 5 min/historical long; ETag | 500 ms | PostgreSQL fight/participant/statistics/scorecard read models; no new inference |

## Prediction and explanation endpoints

### POST /api/v1/predictions/matchup

Request MatchupPredictionRequest:

- fighter_a_id and fighter_b_id;
- either existing fight_id or hypothetical Context containing scheduled timestamp, division, scheduled_rounds and only audited optional context;
- mode: pure or market;
- prediction_as_of, default now for hypothetical/upcoming requests;
- optional model_version for authorized analysts; public uses champion;
- persist defaults true; explanation mode none, cached, or async;
- optional idempotency_key header.

Validation enforces distinct fighters, fight participant consistency, cutoff/horizon, compatible scheduled format, model capability, and market availability. Client-supplied raw feature vectors or odds are not accepted by this endpoint.

Response is 200 Prediction when snapshot/capability is ready, or 202 Job when feature/explanation work exceeds the synchronous budget.

Auth: public champion requests, strict per-IP/API-key limit; analyst role for non-champion versions.  
Errors: 404 fighter/fight; 409 incompatible version/idempotency; 422 context/mode; 429; 503 model/data/market unavailable.  
Cache: request hash including all version/cutoff fields, 5-30 min for ad hoc and immutable for frozen snapshots.  
Latency: 1.5 s synchronous; 500 ms job acknowledgement.  
Interactions: PostgreSQL canonical/features/predictions; Redis cache/idempotency; in-process ModelRuntime for dual inference, calibration, reconciliation, confidence; Celery if async.

### GET /api/v1/predictions/fights/{fight_id}

Request: fight UUID; optional mode, horizon, latest_as_of, model_version; cursor for historical snapshots. latest_as_of means select a stored snapshot, never recompute.  
Response: Page[Prediction] or a compact PredictionSet comparing pure/market snapshots.  
Auth: public for published versions; analyst for internal candidates.  
Errors: 404 fight/no published snapshot; 422 filters; 403 internal; 429.  
Cache: immutable by snapshot IDs; selection query 60 s; ETag.  
Latency: 350 ms.  
Interactions: PostgreSQL prediction/explanation summaries; no model inference.

### GET /api/v1/predictions/{prediction_id}/explanation

Request: prediction UUID; optional detail=summary or full where authorized.  
Response: Explanation containing grouped contributions, direction, value/baseline, quality warnings, algorithm/version, and causal disclaimer.  
Auth: public summary for published prediction; analyst for full/debug.  
Errors: 404; 403; 409 explanation pending; 429.  
Cache: immutable, long TTL/ETag.  
Latency: 300 ms stored; use POST jobs through prediction request for missing expensive explanation.  
Interactions: PostgreSQL/object storage read; no inline SHAP for public GET.

## Simulation and similarity endpoints

### POST /api/v1/simulations/counterfactual

Request CounterfactualRequest:

- base_prediction_id or a valid MatchupPredictionRequest;
- modifications: list of feature key and proposed value;
- optional explanation=true;
- idempotency key.

Response: 200 CounterfactualResult for bounded synchronous requests or 202 Job. Result contains base prediction, changed prediction, observed/effective FeatureValues, probability deltas, strongest changed groups, uncertainty delta, OOD/plausibility warnings, synthetic disclaimer, and version tuple.

Auth: public with strict rate/size limits; authenticated user may retrieve longer-lived result; candidate models require analyst.  
Errors: 404 base; 409 incompatible/stale base version; 422 forbidden/unrealistic/control unavailable; 429; 503.  
Cache: canonical request hash 10 min; stored results immutable according to retention.  
Latency: 1.5 s synchronous or 500 ms acknowledgement.  
Interactions: PostgreSQL base feature/prediction; counterfactual validator/feature graph; in-process model; Celery for explanation/heavy dependency recompute.

### POST /api/v1/simulations/monte-carlo

Request MonteCarloRequest:

- prediction_id or nested valid matchup/counterfactual request;
- iterations within bounded policy;
- optional seed (otherwise server derives and returns one);
- requested distributions: winner, method, round, duration;
- idempotency key.

Response: normally 202 Job with Location. Small internal requests may return MonteCarloResult containing counts/probabilities, duration quantiles/histogram, Monte Carlo standard errors, seed, iterations completed, engine/version, base model versions, uncertainty and limitations.

Auth: public at low quotas; authenticated tier/API key for higher approved quota; no anonymous arbitrary model version.  
Errors: 404 base; 409 idempotency/version; 422 iterations/distribution; 429; 503 queue/model.  
Cache: idempotency/canonical hash; durable result with retention.  
Latency: 500 ms acknowledgement; standard result target under 30 s.  
Interactions: PostgreSQL job/base prediction/result; Redis/Celery simulation queue; worker loads compatible bundle, vectorized sampler.

### GET /api/v1/similar-matchups

Request: prediction_id or fighter_a_id/fighter_b_id plus context/cutoff; k defaults 5 and max 20; optional same_weight_class and style_weight preset.  
Response: SimilarMatchupResult with target version, historical FightSummary items, distance/score, top similarity reasons, important differences, feature coverage, and historical-outcome disclaimer.  
Auth: public; analyst-only custom raw weights.  
Errors: 404 target; 422 context/k; 429; 503 index unavailable.  
Cache: 10 min by target/vector/index version; immutable for frozen target/index.  
Latency: 750 ms exact search at MVP.  
Interactions: PostgreSQL metadata plus Parquet/precomputed neighbor read; SimilarityRetriever only, no prediction model.

### GET /api/v1/jobs/{job_id}

Request: opaque job ID plus anonymous scoped token when applicable.  
Response: Job; 303/embedded result URL may be used after success.  
Auth: owner/session token or role; public anonymous token is unguessable and scoped.  
Errors: 401/403; 404; 410 expired; 429.  
Cache: no-store while active; immutable short cache after completion.  
Latency: 200 ms.  
Interactions: PostgreSQL authoritative job/result status; Redis optional progress.

## Model and operations endpoints

| Endpoint | Request/response | Auth | Errors | Cache | Latency | Interactions |
|---|---|---|---|---|---:|---|
| GET /api/v1/models | filters mode/status; returns Page[PublicModelCard] with intended use, versions, promotion state, limitations | Public for champion/archived public cards; analyst for candidates | 422, 403, 429 | 5 min/ETag | 250 ms | PostgreSQL model metadata; no artifact load |
| GET /api/v1/models/{model_id}/metrics | UUID; optional cohort/horizon/metric enums; returns EvaluationSummary with support/intervals and artifact links safe for role | Public published; analyst detailed | 404, 403, 422, 429 | Immutable by evaluation version | 500 ms | PostgreSQL aggregates and object-store report references |
| GET /health | no request; returns status and build version only | Public | 500 only on process fault | no-store | 50 ms | No dependencies |
| GET /readiness | no request; returns ready/degraded, migration and capability states without secrets | Orchestrator; public exposure may be network-restricted | 503 not ready | no-store | 250 ms | PostgreSQL ping, process model map, config; bounded Redis state |
| GET /api/v1/data/freshness | optional source/domain; returns per-source last successful observation/retrieval/publish, expected cadence, status, known issue summary, dataset version | Public summary; analyst detail | 422, 429, 503 | 30-60 s | 250 ms | PostgreSQL ingestion/freshness/quality aggregates |

## Administrative endpoints

These endpoints are in the contract even if the first UI uses CLI workflows:

| Endpoint | Request | Response | Role | Main behavior |
|---|---|---|---|---|
| POST /api/v1/admin/ingestion-runs | source, mode incremental/backfill, bounded range, dry_run, idempotency key | 202 Job | data_operator | Validate source policy; enqueue; audit |
| GET /api/v1/admin/data-quality-issues | status/severity/source cursor filters | Page[DataQualityIssue] | analyst/data_operator | PostgreSQL read |
| PATCH /api/v1/admin/data-quality-issues/{id} | expected version, status, resolution note | updated issue | data_operator | Optimistic lock; audit; no fact mutation |
| POST /api/v1/admin/models/{id}/stage | expected current state, note | ModelVersion | model_manager | Registry compatibility/staging job; audit |
| POST /api/v1/admin/models/{id}/promote | target alias, expected current alias/version, approval note | Promotion | model_manager | Atomic compare-and-set alias, warm rollout; audit |
| POST /api/v1/admin/models/{id}/rollback | target alias, reason, expected current version | Promotion | model_manager | Point alias to previously validated version; audit |

Validation rejects unbounded backfills, invalid state transitions, self-approval where separation is enabled, and stale expected versions. Errors include 401, 403, 404, 409, 422, 429, and 503. Responses are no-store; acknowledgement p95 is 500 ms. Database interactions use audited transactions; long work uses Celery/registry ports.

## Caching correctness

Every cache key includes any state that can change meaning: contract version, canonical request, prediction cutoff/horizon, mode, dataset/feature/model/calibration/similarity-index versions, and authorization visibility. Cache entries store the returned version tuple. The API compares immutable IDs rather than relying only on TTL. Promotion changes aliases and invalidates alias-selection caches, but existing prediction resources stay immutable.

## Version and deprecation policy

Breaking schema/semantic changes create /api/v2. Additive optional fields are allowed within v1. Deprecated fields are documented for at least one public release window and emit a deprecation header. Generated web clients are checked against OpenAPI in CI. Model versions are independent of API versions but declare compatibility.

