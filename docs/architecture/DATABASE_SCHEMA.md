# Database schema

## Conventions

PostgreSQL is the transactional system of record for canonical entities and product snapshots. UUID primary keys prevent source coupling; source IDs live in alias/reference tables. All tables use timezone-aware timestamps. money-like odds representations are not assumed; original provider values are preserved in typed source payload references and normalized probabilities only after an audited mapping.

Common columns where applicable:

- created_at and updated_at for operational rows;
- effective_from/effective_to for sport-world validity;
- observed_at/ingested_at and system_from/system_to for knowledge history;
- source_id/raw_object_id/parser_version for provenance;
- row_version for optimistic locking;
- content_hash for immutable data.

Use CHECK constraints for probability/range/state invariants, PostgreSQL enums only when values are truly stable (otherwise reference tables/text checks), and JSONB only for versioned variable payloads, not as a substitute for core relationships.

## Identity and catalog

### fighters

- fighter_id UUID PK
- display_name TEXT NOT NULL
- identity_status TEXT NOT NULL
- created_at, updated_at, retired_at TIMESTAMPTZ NULL
- merged_into_fighter_id UUID NULL FK fighters
- row_version INTEGER NOT NULL

Indexes: lower(display_name) search/trigram; identity_status.  
Constraints: merge target differs from self. Names are not unique.

Reviewed merge/split state is not inferred from display names. `merged_into_fighter_id`
is a current-state projection guarded by database triggers; every transition must
have an applied, append-only identity-resolution application and merge/split
ledger record. A split restores only that identity edge and never silently moves
source aliases.

### fighter_aliases

- fighter_alias_id UUID PK
- fighter_id UUID NOT NULL FK fighters
- source_id UUID NOT NULL FK data_sources
- alias_type TEXT NOT NULL
- alias_value TEXT NOT NULL
- normalized_value TEXT NOT NULL
- provider_external_id TEXT NULL
- resolution_status/confidence/evidence JSONB
- valid/observed/system timestamps and raw_object_id

Unique: (source_id, alias_type, provider_external_id) where external ID is not null. Name strings are deliberately not unique.  
Indexes: fighter_id; (source_id, normalized_value); unresolved status.

Alias identity/provenance fields are immutable. A current alias may only be
closed by setting `system_to`; reviewed corrections create a replacement alias
and an append-only supersession link rather than reassigning or overwriting the
source alias.

### fighter_identity_merges and fighter_identity_splits

Both ledgers are append-only and reference the terminal identity-resolution
application that authorized the action. A merge records the active canonical
fighter, merged fighter, actor, and timestamp. A split references exactly one
prior merge, its superseding review, the restored fighter, actor, and timestamp.
The database permits neither a merge retarget nor a restoration without these
records. Historical aliases remain attached to their original fighter records;
alias correction is a separate bitemporal operation.

### fighter_attribute_observations

Stores only fields actually observed after source audit, one typed observation per fighter/attribute.

- observation_id UUID PK
- fighter_id/source_id/raw_object_id FKs
- attribute_key, value_numeric/value_text, unit, quality_state
- effective_from/to, observed_at, ingested_at, system_from/to

Unique: source observation identity/content hash.  
Index: (fighter_id, attribute_key, observed_at DESC).

### promotions

- promotion_id UUID PK
- canonical_name TEXT NOT NULL
- created_at, updated_at

Unique: normalized canonical name only after reviewed resolution.

### events

- event_id UUID PK
- promotion_id UUID NULL FK promotions when the source has not supplied a reviewed promotion fact
- canonical_name TEXT NOT NULL
- status TEXT NOT NULL
- scheduled_start_at, actual_start_at TIMESTAMPTZ NULL
- location fields nullable and source-backed
- latest_schedule_observed_at TIMESTAMPTZ
- created_at, updated_at

Indexes: (scheduled_start_at DESC); (promotion_id, scheduled_start_at); status.  
Provider identifiers belong in event_source_refs with unique source/external key and bitemporal schedule observations in event_observations.

### fights

- fight_id UUID PK
- event_id UUID NULL FK events only when `event_context_status = not_observed`; a missing event identifier is never inferred from date/location
- status TEXT NOT NULL
- division_id UUID NULL FK divisions
- scheduled_order INTEGER NULL
- scheduled_rounds, round_length_seconds INTEGER NULL
- scheduled_start_at TIMESTAMPTZ NULL
- ruleset_version TEXT NULL
- fight_date DATE NULL retains a source-supplied calendar date without fabricating a start timestamp
- publication_state (`staged`/`published`), created_at, updated_at

Unique: (event_id, scheduled_order) only when stable/non-null is not relied on for identity; provider refs have actual unique source keys.  
Indexes: event_id; scheduled_start_at; status/division.  
Checks: positive rounds/round length. A deferred constraint trigger requires exactly two participants and one current result before a canonical fight can become `published`.

### event_source_references and fight_source_references

Immutable source/raw links retain source ID, raw object, schema version, source
record/external key, ingestion time, and canonical fight key. Replaying the same
source fact returns the existing fight; a conflicting replay is rejected rather
than silently updating a canonical fact and is recorded as a blocking canonical
quality issue with source-record/checksum evidence.

### fight_participants

- fight_participant_id UUID PK
- fight_id UUID NOT NULL FK fights
- fighter_id UUID NOT NULL FK fighters
- canonical_slot SMALLINT NOT NULL
- source_corner TEXT NULL
- bout_weight observation fields only if audited
- created_at

Unique: (fight_id, fighter_id), (fight_id, canonical_slot).  
Checks: canonical_slot in (0,1). A deferred constraint trigger validates exactly two participants when a fight becomes published. canonical_slot is outcome-independent. `fight_participant_identity_evidence` links each source participant to the applied identity-resolution decision that resolved that fighter.

### fight_results

- fight_result_id UUID PK
- fight_id UUID NOT NULL FK fights
- winner_participant_id UUID NULL FK fight_participants
- outcome_type TEXT NOT NULL
- canonical_method_code TEXT NULL
- source_method_label TEXT NULL
- ending_round, ending_time_seconds_in_round NULL
- effective_from/to, observed_at, ingested_at, system_from/to
- source_id/raw_object_id/parser_version
- quality_state

Unique: current approved result per fight via partial index; retain superseded versions.  
Checks: draw/no-contest cannot have winner under canonical policy; time/round bounds validated with trigger/application.

## Fight performance and judging

### rounds

- round_id UUID PK
- fight_id UUID NOT NULL FK fights
- round_number INTEGER NOT NULL
- scheduled_duration_seconds INTEGER NULL

Unique: (fight_id, round_number).  
Check: round_number > 0.

### round_statistics

- round_statistic_id UUID PK
- round_id UUID NOT NULL FK rounds
- fight_participant_id UUID NOT NULL FK fight_participants
- statistic_definition_id UUID NOT NULL FK statistic_definitions
- value/attempt components typed according to audited definition
- source_id/raw_object_id
- observed_at, ingested_at, system_from/to
- quality_state, content_hash

Unique: versioned source observation identity; partial unique current approved observation per source/round/participant/definition.  
Indexes: participant/definition; round; observed_at.  
Cross-fight participant consistency is enforced in validation/constraint trigger.

### judges

- judge_id UUID PK
- display_name TEXT NOT NULL
- identity_status
- created_at, updated_at, merged_into_judge_id NULL FK judges

Judge aliases mirror fighter alias logic in judge_aliases; names are not unique.

### scorecards

- scorecard_id UUID PK
- fight_id UUID NOT NULL FK fights
- judge_id UUID NULL FK judges
- source_id/raw_object_id
- card_status, extraction_method, extraction_confidence
- observed_at, ingested_at, system_from/to
- quality_state

Unique: current source card key; index fight_id/judge_id.  
scorecard_round_scores stores scorecard_id, round_id, participant_id, points, deductions if audited, with unique (scorecard_id, round_id, participant_id). Raw images/PDF stay in object storage.

## Temporal market, ranking, and rating facts

### rankings

- ranking_id UUID PK
- fighter_id UUID NOT NULL FK fighters
- division_id UUID NOT NULL FK divisions
- source_id/raw_object_id FKs
- ranking_value/code nullable according to taxonomy
- published_at, effective_from/to, observed_at, ingested_at, system_from/to
- quality_state, content_hash

Unique: versioned source observation; index (fighter_id, division_id, published_at DESC), (division_id, published_at, ranking_value). Current rankings are not stored on fighters.

### odds_snapshots

- odds_snapshot_id UUID PK
- fight_id UUID NOT NULL FK fights
- fight_participant_id UUID NOT NULL FK fight_participants
- source_id UUID NOT NULL
- provider_market_key, provider_quote_key
- market_type, quote_format, original_quote representation
- normalized_implied_probability NUMERIC NULL
- normalization_policy_version NULL
- quote_timestamp, observed_at, ingested_at TIMESTAMPTZ
- raw_object_id, quality_state, content_hash

Unique: (source_id, provider_quote_key, quote_timestamp, content_hash) or audited provider identity.  
Indexes: (fight_id, market_type, quote_timestamp DESC); participant/time; observed_at.  
Checks: normalized probability in [0,1]. Never overwrite a quote.

### fighter_ratings

- fighter_rating_id UUID PK
- fighter_id UUID NOT NULL FK fighters
- rating_system_version_id UUID NOT NULL FK rating_system_versions
- as_of_at TIMESTAMPTZ NOT NULL
- source_fight_id UUID NULL FK fights
- rating_value, rating_deviation, volatility nullable numeric
- dataset_version_id UUID NOT NULL FK dataset_versions
- content_hash

Unique: (fighter_id, rating_system_version_id, as_of_at, dataset_version_id).  
Indexes: fighter/system/as_of descending; source fight. Ratings are pre/post update states explicitly tagged by definition.

## Data governance and ingestion

### data_sources

source_id UUID PK; stable key/name; source type; declared dataset licence; policy/terms version; attribution text; enabled state; rate policy; owner; timestamps. Secrets are references, never stored here.

### raw_objects

raw_object_id UUID PK; source_id FK; object_uri; sha256; bytes/content type; source locator (redacted as needed); original filename; source-schema version; requested/retrieved/source-modified times; HTTP metadata safe JSON; ingestion_run_id FK; retention class.

Unique: source_id plus storage namespace and sha256; every retrieval relationship remains in raw_retrievals. This keeps source provenance unambiguous when different sources retain identical bytes, while the object-store implementation may still deduplicate the underlying blob by checksum. Index source/retrieved.

### ingestion_runs

- ingestion_run_id UUID PK
- source_id FK
- mode, bounded range/checkpoint, parser/schema/pipeline versions
- status and attempt
- requested/started/completed/published timestamps
- input/accepted/quarantined/filtered counts
- previous_checkpoint/new_checkpoint JSONB
- error summary and initiated_by nullable

Unique: idempotency key/source. Index status/start and source/published.

### data_quality_issues

- issue_id UUID PK
- ingestion_run_id/dataset_version_id/source_id nullable FKs
- entity_type/entity_id nullable
- rule_id, severity, status, blocking
- safe summary, evidence object URI/JSON, occurrence_count
- canonical_issue_key nullable; unique per source when present for idempotent canonical quarantine/conflict replay aggregation
- first/last_seen, assigned/resolved timestamps and actor
- row_version

Indexes: blocking unresolved; source/status/severity; dataset. Retain audit history.

### identity_resolution_decisions

Decision ID, entity type, source alias/ref, proposed/resolved canonical ID, decision type, confidence/evidence, actor/model version, timestamps, supersedes decision. Append-only.

## Feature, dataset, and model registry

### dataset_versions

- dataset_version_id UUID PK
- version TEXT UNIQUE NOT NULL
- manifest_uri, manifest_sha256
- canonical_schema_version, pipeline_version, code_digest
- knowledge_cutoff, status
- quality_report_uri/hash
- created/approved/superseded timestamps and actors

Approved manifests are immutable. Index status/approved time.

### feature_snapshots

- feature_snapshot_id UUID PK
- target_fight_id UUID NULL FK fights
- hypothetical_matchup_hash NULL
- fighter_a_id/fighter_b_id FKs
- prediction_as_of, target_fight_timestamp
- orientation, orientation_policy_version
- dataset_version_id FK
- feature_set_version, pipeline_version
- latest_source_timestamp, generated_at
- values_jsonb for online approved typed values and/or parquet_uri/row_key
- lineage_uri/summary_jsonb
- input_completeness_jsonb
- content_hash
- status

Unique: semantic key plus content_hash; one published alias can be selected without mutating rows.  
Indexes: target fight/as_of; fighter pair; content_hash; dataset/feature version.  
Checks: latest_source_timestamp < target_fight_timestamp and below prediction cutoff according to conservative policy; exactly one target form. Large offline matrices stay in Parquet.

### model_versions

- model_version_id UUID PK
- name, task, mode, semantic version
- registry URI/run ID, artifact URI/digest, model card/evaluation URIs
- dataset_version_id FK
- feature_set/calibration/reconciliation/OOD policy versions
- API compatibility, container digest
- status, created/validated/promoted/archived timestamps
- created/approved actors

Unique: (name, semantic_version); artifact digest. Index task/mode/status.

model_aliases maps a unique (task, mode, environment, alias) to model_version_id with row_version. model_promotions is append-only audit history.

## Product snapshots

### predictions

- prediction_id UUID PK
- fight_id NULL FK fights; hypothetical matchup hash NULL
- feature_snapshot_id FK feature_snapshots
- model_version_id FK model_versions plus bundle/component version JSON
- mode, status
- prediction_timestamp, prediction_as_of, target_fight_timestamp, horizon_seconds
- fighter_a/b IDs
- winner/path/method/round/duration JSONB constrained by application plus validation trigger
- confidence/input completeness/warnings JSONB
- request_hash, content_hash, explanation_status
- published/internal visibility

Unique: a declared frozen snapshot key (fight, mode, horizon/cutoff, model bundle, feature hash) and idempotent request scope.  
Indexes: fight/time; fighter pair; model; published/time; request hash.  
Rows are immutable except controlled visibility/explanation-status transitions; output revisions create rows.

### prediction_explanations

- explanation_id UUID PK
- prediction_id FK predictions
- algorithm/version, baseline cohort/version
- summary JSONB and artifact URI/digest
- approximation flag, generated_at, status

Unique: (prediction_id, algorithm, version, baseline version). Immutable once succeeded.

### simulations

- simulation_id UUID PK
- base_prediction_id FK predictions
- type counterfactual/monte_carlo
- request_hash, seed, iterations_requested/completed
- observed_values/modifications JSONB separated
- engine/version and model/dataset/feature versions
- result JSONB or artifact URI/digest
- uncertainty/warnings
- status, owner/anonymous scope hash
- created/started/completed/expires timestamps

Unique idempotency/request scope. Index owner/status/created and base prediction. Counterfactual rows never join as canonical observations.

### jobs

job_id UUID PK; type/status; owner/scope hash; idempotency key/request hash; queue task ID; progress; durable result entity/type; safe error; attempts; created/started/completed/expires. Unique scoped idempotency key. Redis is not authoritative.

### audit_events

audit_event_id UUID PK; actor/principal, action, target type/id, request ID, source IP hash/policy, before/after safe JSON, reason, created_at, integrity chain fields if enabled. Append-only, indexed by target/actor/time.

## Deletion and retention

- Raw source objects: retain indefinitely by default for reproducibility, subject to source terms/privacy; lifecycle to cold storage. A legal deletion records a tombstone and impact.
- Interim files: rebuildable, expire after roughly 90 days by policy.
- Canonical history, approved manifests, model metadata, frozen published predictions, promotions, and audit events: retain indefinitely.
- Model binaries: retain champion, rollback candidates, and all versions referenced by published predictions; archive others under policy, never strand a prediction.
- Simulation results: anonymous MVP 30 days, authenticated 90 days unless saved; aggregate non-identifying metrics may persist. Exact values are policy-configurable.
- Redis/cache/task transient data: hours/days; never authoritative.
- User/auth data: minimal and deletable per privacy policy without deleting public analytical snapshots.

Retention values are initial recommendations and must be reconciled with source licenses and privacy law. Longer auditability costs storage; object lifecycle controls cost without sacrificing manifests.

## Partitioning and scale

Do not partition small tables prematurely. Candidates after measured growth:

- odds_snapshots by quote month/year;
- round_statistics by effective event year;
- predictions/audit events by creation month.

PostgreSQL indexes are confirmed with EXPLAIN on real query fixtures. Parquet partitions favor domain/effective year/dataset version and avoid tiny event-level file explosion. Exact nearest-neighbor search is sufficient initially.

## Integrity limitations

Some cross-table constraints, such as participant belonging to the same fight, round/time compatibility, probability JSON coherence, and immutability state transitions, require deferred triggers plus domain validation. Both are tested; relying only on application checks is insufficient, while encoding all evolving domain taxonomy in rigid database enums would make migrations fragile.
