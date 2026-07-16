# Data source audit

Status: pre-implementation audit plan; no source availability or field is asserted until verified.

## Audit rule

No adapter, schema, or feature may be treated as production-ready based on source reputation or a sample screenshot. For each source, implementation must capture access terms, robots/rate policy, coverage, timestamp semantics, identifiers, schema variants, revision behavior, and representative raw fixtures. Findings replace the assumptions below.

## Preliminary source matrix

| Source | Intended use | Key uncertainties and leakage risk | Initial decision |
|---|---|---|---|
| UFCStats events/fight metadata | Event, bout, result, format context | DOM stability, schedule revisions, actual publish time, canceled/changed bouts | Primary candidate; audit HTML and terms before scraper |
| UFCStats fighter profiles | Identity candidates and physical attributes | Attribute update history may be absent; current profile could leak later changes backward | Preserve observations by retrieval time; never backfill current values as historically known |
| UFCStats round statistics | Historical performance | Stats are post-fight by definition; corrections and totals; labels/units | Eligible only for later fights through point-in-time join |
| Historical UFC rankings | Rank/movement features | Publication dates, archives, ties/NR, division changes, retroactive pages | No ranking feature until dated archives are verified |
| Historical betting odds | Model B only | Quote/market/provider/time-zone, open versus close, de-vig method, survivorship | Require timestamped snapshots; closing odds never used before observed |
| Golden modeling dataset | Comparison and validation only | Unknown derivation, leakage, licensing, duplicates, imputation | Never canonical truth or training input unless separately audited and approved by ADR |
| Pre-UFC professional records | Debut/experience context | Promotion coverage, opponent identities, result corrections, uneven geography | Nullable experimental source; report coverage bias |
| UFC scorecards | Judge/round decisions | Image/PDF OCR, amended cards, identity, completeness | Preserve originals; human/OCR confidence; Model E gated by coverage |
| MMA decision/judging data | Split risk and disagreement | Terms, unofficial records, score semantics, duplicate cards | Experimental; source-specific validation and legal review |

## Required audit worksheet per source

Every source receives a completed record with:

- owner and review date;
- official/public/third-party status and contact;
- terms of service, robots policy, licensing, attribution, redistribution, and retention decision;
- access mechanism, authentication, pagination, rate limits, retry semantics, and expected cost;
- earliest/latest coverage and measured missing periods;
- data granularity and all observed schema fingerprints;
- source keys and collision/stability tests;
- timezone, observed/published/effective timestamp meanings and precision;
- revision/deletion behavior and backfill method;
- sampled nulls, duplicates, invalid values, and cross-source disagreements;
- sensitive/personal data classification;
- raw retention and allowed product exposure;
- parser fixtures, checksum, and validation thresholds;
- go/no-go decision and feature allow-list.

Legal/access review is a hard dependency, not an engineering afterthought. If automated scraping is disallowed or unclear, use licensed/manual alternatives or omit the source.

## Source-specific validation plans

### UFCStats event and fight pages

- Fixture multiple eras, event states, scheduled/completed/canceled bouts, title/main events, and unusual results.
- Verify event/fight URLs or IDs for stability; do not infer fields not present.
- Compare event bout lists across repeated retrievals to characterize revision.
- Validate exactly two supported participants, scheduled format, result consistency, and explicit unknowns.
- Rate limit globally per host, cache already fetched content by checksum, and use conditional requests when supported.

### UFCStats fighter profiles

- Test name collisions and profile-ID stability.
- Treat height, reach, stance, date of birth, and record as optional observations until verified.
- Record retrieval time and never assume a current value was historically visible.
- Reject using displayed current career record as a historical pre-fight feature; derive record from eligible fights instead.

### Round statistics

- Validate round numbering, time format, attempts/landed relationships when those concepts exist, totals, and duplicates.
- Trace every statistic to fight, participant, and round.
- Characterize corrections through repeat retrieval.
- Maintain raw labels and explicit mapping; do not fabricate zero for missing.

### Rankings

- Require dated publication/archive evidence and timezone policy.
- Normalize division and rank values through versioned mappings; retain ranked/not-ranked and champion/interim semantics separately if present.
- Detect copied-current pages masquerading as archives.
- Join by publication/knowledge time and canonical fighter identity.
- If dated coverage is insufficient, exclude rankings from MVP rather than reconstruct them silently.

### Odds

- Record provider, bookmaker/aggregate, market, participant side, quote format, quote timestamp, observed_at, retrieved_at, and source timezone only if source supplies or audit establishes them.
- Store original quote and separately versioned normalized implied probability/de-vig output.
- Detect side swaps, suspended markets, stale quotes, duplicates, and timestamp precision.
- Define horizon buckets after coverage analysis. Opening, latest-as-of, and movement use only eligible quotes.
- A record without trustworthy temporal provenance cannot feed Model B.

### Golden comparison dataset

- Compute schema/row counts, target distributions, duplicate keys, date ranges, and overlap with canonical facts.
- Reproduce published/expected benchmarks if documentation exists.
- Compare aggregate and row-level values without importing its engineered fields into training.
- Document licensing and probable leakage. It remains an external benchmark; disagreement prompts investigation, not automatic correction.

### Pre-UFC records

- Resolve promotions, fighters, opponents, and event dates conservatively.
- Measure missingness by geography, era, gender/division, and fighter debut cohort.
- Derive only facts visible before UFC debut.
- Treat record summaries from a current page as potentially future-contaminated unless historical bouts are individually dated.

### Scorecards and judging

- Retain original image/PDF; hash and malware-scan it.
- Separate OCR output, confidence, human correction, and canonical score.
- Validate legal round score ranges only after confirming ruleset; preserve unusual values for review.
- Resolve judge identity with aliases and never infer an unknown judge.
- Gate Model E on coverage, label reliability, and cohort bias; a shadow-only result is acceptable.

## Cross-source reconciliation

Canonicalization does not choose a universal provider priority silently. Each field family has a documented source precedence and conflict policy. Conflicts are stored as parallel observations, surfaced as quality issues, and resolved through a versioned rule or review. Fight result corrections are particularly sensitive: the canonical status retains amendment history and training eligibility follows the dataset policy.

## Audit deliverables before ingestion milestone closes

1. Completed worksheet and legal/access decision for each enabled source.
2. At least one raw fixture for every observed schema era/state, stored in test fixtures only if redistribution permits.
3. Adapter contract tests and measured polite rate configuration.
4. Coverage/null/duplicate/timestamp report.
5. Identifier stability and identity-collision report.
6. Source-specific data dictionary generated from observed fields, without invented columns.
7. Explicit allow-list for canonical fields and ML feature families.
8. Backfill time/cost estimate and stop/recovery procedure.

## Go/no-go gates

A source is **green** when access is permitted, temporal meaning is adequate, schema fixtures pass, and lineage is complete. It is **amber** when usable only for product display or experimental features due to coverage/timestamp issues. It is **red** when terms, provenance, identity, or leakage risk cannot be controlled. Red sources are preserved only if legally acquired for investigation and cannot enter a published dataset.

## Known unresolved decisions

- Exact provider URLs, fields, rate ceilings, and licensing/retention conditions.
- Historical ranking and timestamped odds provider selection.
- Whether scorecard originals may be redistributed or only derived facts displayed.
- Minimum viable coverage for pre-UFC and judging features.
- Whether event start, bout order, or a conservative event-level timestamp defines target_fight_timestamp when exact fight time is unavailable.

These are scheduled for Milestone 2 and are tracked in the risk register. They must not be resolved by assumption.

