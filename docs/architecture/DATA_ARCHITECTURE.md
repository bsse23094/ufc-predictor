# Data architecture

## Design choice

Use an immutable, manifest-driven lake layout in Parquet/object storage for history and PostgreSQL for canonical operational/serving data. DuckDB is the default local query engine. This is simpler and cheaper than a distributed lakehouse at UFC scale; the trade-off is that concurrency and transactional updates reside in PostgreSQL rather than one universal store.

## Data zones

| Zone | Form | Mutability | Purpose |
|---|---|---|---|
| Raw | Original HTML/JSON/CSV/PDF/image bytes plus JSON manifest | Append-only | Evidence, replay, parser debugging |
| Quarantine | Raw reference plus machine-readable issues | Append-only | Unknown schemas, invalid records, identity conflicts |
| Interim | Source-shaped Parquet | Rebuildable | Typed parser output before canonical resolution |
| Canonical | PostgreSQL and canonical Parquet export | Versioned facts | Cross-source entities and temporal observations |
| Processed | Feature/dataset Parquet | Immutable per version | Training, evaluation, similarity |
| Product | PostgreSQL | Append-only snapshots plus aggregates | Predictions, explanations, simulations, freshness |

Raw and derived data directories contain only README/.gitkeep policies in Git. Data files remain local or in object storage.

## Raw object layout and manifest

Suggested object key:

    raw/{source}/{retrieval_date}/{ingestion_run_id}/{sha256}.{extension}

The sidecar/catalog record includes source name, source locator, requested_at, retrieved_at, source-provided modified time, HTTP status/headers subset, content type, byte length, SHA-256, retrieval code version, terms-policy version, and secrecy classification. Secrets and session cookies are scrubbed.

Content-addressed storage avoids duplicate bytes, but each retrieval event is still recorded so changing/stable content is observable. Raw objects are never normalized in place.

## Source adapter contract

Each adapter implements:

1. discover units of work from a checkpoint;
2. fetch with per-host rate limit, bounded retries, jitter, timeout, user agent, and robots/terms policy;
3. persist bytes before parsing;
4. fingerprint schema/DOM markers;
5. parse to source-shaped records with row-level raw reference;
6. validate required structure and account for every input record;
7. emit checkpoint only after durable publication.

Retries apply to transient network/5xx/429 errors and honor Retry-After. Parser/validation failures are not blindly retried. Backfills use explicit ranges and the same adapter path as incrementals.

## Versioning

- **raw_object_version:** checksum identifies bytes.
- **source_schema_version:** adapter-owned fingerprint/version.
- **canonical_schema_version:** migration/version of normalized meaning.
- **dataset_version:** immutable manifest of included canonical partitions, observation cutoffs, exclusion policy, source checksums, code/container digest, and quality report.
- **pipeline_version:** semantic version plus Git commit/container digest.
- **feature_set_version:** immutable feature definitions and types.

Human-readable semantic labels are accompanied by content hashes. A dataset version is published only after referential, temporal, row-accounting, and quality gates pass.

## Bitemporal facts

Canonical source facts distinguish:

- **effective/valid time:** when a ranking, fight schedule, odds quote, profile attribute, or result applies;
- **system/knowledge time:** when the platform observed/ingested it.

Point-in-time queries filter both. Corrections append a superseding fact and close system validity rather than overwrite knowledge history. This costs storage and more complex SQL but enables faithful historical replay.

For sources with no reliable observed timestamp, ingested_at is a conservative upper bound and quality metadata records the limitation. The system must not invent historical availability.

## Identity resolution pipeline

1. Normalize text only for candidate generation; preserve original.
2. Match exact source IDs and reviewed aliases.
3. Generate candidates from name, date of birth, height/reach, nationality, gym, event participation, and record context only where actually available.
4. Score candidates and require conservative thresholds.
5. Auto-link only high-confidence non-conflicting candidates.
6. Queue ambiguous/new cases with evidence for review.
7. Publish explicit merge/split decisions with reviewer and audit history.

Names alone never justify a merge. An unresolved identity quarantines affected facts from modeling but remains visible in ingestion quality totals.

## Canonicalization and validation

Validation layers:

- transport: status, size, checksum, content type;
- structure: known schema/DOM fingerprint and parser contract;
- row: Pydantic/Pandera types, enums, bounds, timestamp parsing;
- relational: foreign keys, exactly two participants, round/fight consistency;
- semantic: duration within scheduled bounds, totals compatible with detail, odds format conversion trace;
- temporal: source and target eligibility;
- statistical: volume, null, category, duplicate, and distribution drift.

Errors are classified as blocking, quarantine, or warning by a versioned policy. Reports show counts, examples, source partitions, and deltas; they never silently drop data.

## Point-in-time feature construction

Inputs are canonical observations and a target grid containing target_fight_id, target_fight_timestamp, prediction_as_of, fighter_id, opponent_id, and orientation.

For every source row:

    eligibility_cutoff = min(target_fight_timestamp, prediction_as_of)
    source knowledge time < eligibility_cutoff
    source_fight_id != target_fight_id

Where equality at prediction cutoff is trustworthy, a source-specific half-open policy may allow it, but strict exclusion is the safe default. Aggregation occurs only after eligibility filtering. Ranking uses the latest published observation eligible at cutoff. Odds use the latest eligible quote for the declared provider/market and also retain open/current movement features from eligible history.

Output lineage includes the required fields:

- target_fight_id and target_fight_date/timestamp;
- source_fight_ids or a compact lineage object/reference;
- latest_source_timestamp;
- feature_generation_timestamp;
- dataset_version and pipeline_version;
- feature_set_version, prediction_as_of, raw/canonical partition hashes;
- imputation and quality flags.

Per-cell lineage for very wide data can be stored as feature-family lineage ranges and source-set hashes to control size. High-risk fields such as rankings and odds retain direct observation references. This balances traceability against explosive storage.

## Automated temporal invariant

Four independent controls enforce latest_source_timestamp < target_fight_timestamp:

1. PointInTimeJoiner requires a cutoff predicate in its API; generic joins are prohibited in feature modules.
2. Snapshot publication SQL/Pandera checks max source timestamp and rejects same-fight source IDs.
3. Synthetic tests inject impossible future values and assert they never affect output.
4. Dataset audit independently recomputes sampled lineage from canonical observations before approval.

CI also scans feature definitions for target/outcome deny-list fields and verifies all duplicate orientations share a split group. Production builds emit a blocking quality issue and cannot advance the current dataset alias on failure.

## Incremental and backfill strategy

- Maintain a checkpoint per source and work-unit type, not one global timestamp.
- Re-fetch a bounded recent window to capture schedule/result corrections.
- Deduplicate on source key plus observation checksum, retaining changed versions.
- Partition canonical exports by domain and effective year/event, with compacted manifests.
- Recompute only affected fighter histories from the earliest changed effective time forward.
- Invalidate dependent feature snapshots and predictions by lineage, but never delete frozen snapshots.
- Backfills run in low-priority queues with rate caps and resumable manifests.

## Local and production storage

Local:

- data/raw, data/interim, data/processed ignored by Git;
- DuckDB files ignored and rebuildable;
- Docker PostgreSQL for API integration;
- optional local MinIO for production parity.

Production:

- managed PostgreSQL where affordable;
- S3-compatible versioned object storage for raw, Parquet, and model artifacts;
- lifecycle raw objects to colder storage but do not delete while reproducibility/source terms require retention;
- derived interim data may expire after 90 days if rebuildable;
- approved dataset/model manifests and frozen predictions retained indefinitely;
- Redis is non-authoritative and may be rebuilt.

## Data publication gates

A version cannot become approved unless:

- checksums and manifest references resolve;
- input/output row accounting balances;
- schema and referential validation pass;
- identity ambiguities meet a documented zero/blocking threshold for modeled rows;
- temporal leakage checks pass with zero violations;
- duplicates and target-field scans pass;
- null/distribution deltas are reviewed against thresholds;
- source freshness and known gaps are published;
- a reproducibility rerun matches sample hashes.

## Trade-offs and rejected alternatives

- PostgreSQL-only storage was rejected because immutable training snapshots and local analytical scans are cheaper and clearer in Parquet.
- Parquet-only serving was rejected because relational APIs, concurrent writes, authorization, and mutable operational states need transactions.
- A hosted feature-store product is deferred because point-in-time snapshots and PostgreSQL lookup meet current scale; it could reduce custom work later but adds cost and vendor coupling now.
- Distributed Spark/lakehouse tooling is deferred because dataset volume does not justify its operational surface.

