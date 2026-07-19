# Data source audit

Status: source-specific audit; no source availability or field is asserted until verified.

Implementation status: source-neutral governance, immutable raw storage, and quarantine contracts are implemented with synthetic bytes. UFCStats remains blocked. The completed Kaggle worksheet below is narrowly approved for one user-downloaded local file, immutable raw preservation, source-shaped interim output, and only explicitly reviewed M3 canonical facts; it is not approval for features, training, or product use.

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
| Kaggle Ultimate UFC Dataset | Licensed local completed-bout ingestion | Upstream provenance, temporal meaning of supplied aggregates, archive drift, duplicate/result quality | Approved only for local M2 raw/interim ingestion; no feature or training use |
| Golden modeling dataset | Comparison and validation only | Unknown derivation, leakage, licensing, duplicates, imputation | Never canonical truth or training input unless separately audited and approved by ADR |
| Pre-UFC professional records | Debut/experience context | Promotion coverage, opponent identities, result corrections, uneven geography | Nullable experimental source; report coverage bias |
| UFC scorecards | Judge/round decisions | Image/PDF OCR, amended cards, identity, completeness | Preserve originals; human/OCR confidence; Model E gated by coverage |
| MMA decision/judging data | Split risk and disagreement | Terms, unofficial records, score semantics, duplicate cards | Experimental; source-specific validation and legal review |

## UFCStats decision record: events, fight metadata, and round statistics

**Review date:** 2026-07-17
**Review authority:** engineering evidence review only; no product/data-owner
approval has been granted.
**Decision:** **red / no-go**. This is an evidence-backed rejection of automated
ingestion, not an approved source worksheet. No `DataSource` record may be
enabled and no adapter, fixture, raw retention, field mapping, or backfill may
be added for this scope.

### Access and legal evidence

- The public [UFC Terms of Use](https://www.ufc.com/terms), reviewed on the
  date above, prohibit automated page scraping/robots and commercial
  reproduction or distribution without prior written permission. They are the
  only relevant published terms located during this review.
- `ufcstats.com` presents itself in search results as "Stats | UFC", but that
  is not evidence that the UFC terms apply to that separate hostname, nor is it
  a licence for this product. The relationship, permitted retention, and
  redistribution rights remain unverified.
- Direct review attempts for `https://ufcstats.com/robots.txt` and the site
  root failed from the project environment (connection failure); browser
  retrieval also returned a gateway failure. Therefore no robots policy,
  rate ceiling, conditional-request behaviour, contact route, or source terms
  could be verified from the source itself. No response bytes were retained.

### Technical and temporal evidence

- No permitted representative HTML was obtained. There are consequently no
  observed schema fingerprints, source-key stability checks, parser fixtures,
  coverage measurements, null/duplicate report, or data dictionary.
- Event dates visible in public search snippets do not establish a source
  publication, observation, effective, or exact fight timestamp. They cannot
  support target construction, feature cutoffs, or backfill chronology.
- Fighter profile observations and round statistics remain especially unsafe:
  a current profile may describe a later state, and a fight's statistics are
  post-fight observations. Neither is permitted for historical features without
  a later point-in-time join even if a licensed source is later approved.

### Required path to reconsider

Only written permission or a licensed machine-readable feed that explicitly
covers automated access, retention, internal use, public exposure, and
attribution can reopen this decision. A product/data owner must then complete
the required worksheet below from permitted representative responses, set an
audited rate/concurrency policy, define a field allow-list, and explicitly
approve it. Until then the source remains disabled and absent from the
registry.

## Kaggle Ultimate UFC Dataset

**Dataset:** [mdabbert/ultimate-ufc-dataset](https://www.kaggle.com/datasets/mdabbert/ultimate-ufc-dataset/data)

**Review date:** 2026-07-17

**Review authority:** engineering implementation record under the product direction
to use this licensed local-file path.  Feature/training approval is explicitly
out of scope.
**Decision:** **green for M2 local raw and source-shaped interim ingestion only;
amber for every downstream use.** The adapter never contacts UFCStats, Kaggle,
or the publisher's GitHub mirror. It reads only an explicitly user-downloaded
file from `data/incoming/ultimate-ufc-dataset/`.

### Current licence, attribution, and provenance

- Kaggle's public metadata, queried on the review date, identifies owner
  `mdabbert`, dataset version **181**, a `2026-04-01T23:37:51.8Z` update, and
  **Attribution 4.0 International (CC BY 4.0)**. Its listed bundle size is
  3,205,223 bytes. The page describes the dataset as a merge of public UFC
  datasets and names UFCStats, BestFightOdds, and Kaggle UFC rankings as
  upstream inputs. That description is provenance, not independent validation
  of those upstream sources.
- CC BY 4.0 permits sharing and adaptation, including commercially, provided
  that appropriate credit, a licence link, and an indication of changes are
  supplied. Every raw and interim manifest records the licence identifier
  `CC-BY-4.0`, the attribution "Ultimate UFC Dataset by mdabbert, via Kaggle,
  licensed CC BY 4.0," the Kaggle URL, and the fact that the platform created
  a restricted source-shaped Parquet projection. See the [CC BY 4.0 deed](https://creativecommons.org/licenses/by/4.0/).
- Raw input stays ignored by Git and is retained locally as immutable evidence.
  No public redistribution, model training, odds feature, ranking feature, or
  source-specific claim is authorized by this decision.
- Every immutable raw retrieval manifest records the source identifier, declared
  dataset licence, attribution, requested/retrieved timestamps, original
  filename, SHA-256, source-schema version, and ingestion-run ID. The interim
  manifest links its Parquet checksum back to those raw references.

### Files, schema, and local acquisition

- The supported M2 input is **`ufc-master.csv`**. Publisher material also
  advertises `upcoming.csv`; it is deliberately outside this adapter because
  its market/current-card semantics are not audited. Any other downloaded file
  is left untouched and is not read or normalized.
- The public version-181 metadata endpoint did not enumerate file names, so
  the operator must record `kaggle datasets files mdabbert/ultimate-ufc-dataset/181`
  output with the manual acquisition. The adapter itself records the selected
  original filename and checksum, which is the authoritative local input
  identity.
- The audited completed-bout contract is schema version
  `completed-bouts-v1`. It requires `R_fighter`, `B_fighter`, `date`,
  `Winner`, and `no_of_rounds`. `date` must be ISO-8601, scheduled rounds must
  be a positive integer, and result must be Red, Blue, Draw, NC, or No Contest.
  The full CSV header is not a feature contract; unknown/missing required
  structure is quarantined after raw preservation.
- With the official Kaggle CLI, acquire exactly the reviewed version and file:

  ```powershell
  kaggle datasets files mdabbert/ultimate-ufc-dataset/181
  kaggle datasets download mdabbert/ultimate-ufc-dataset/181 -f ufc-master.csv -p data/incoming/ultimate-ufc-dataset
  ```

  This environment has neither the Kaggle CLI nor credentials, so no dataset
  bytes were downloaded. The adapter is verified against a synthetic,
  representative CSV fixture only once its locked Parquet dependency is
  available.

### Temporal and leakage allow-list

Only source record identity and event context are retained in interim Parquet:
an opaque two-fighter source pair, date, location/country, title flag, weight
class, gender, and scheduled rounds. The original R/B labels are deliberately
not retained as output columns and are marked `winner_derived_ordering_unverified`.
None of these fields is an approved ML feature.

The adapter explicitly quarantines from feature output:

- `Winner`, `finish`, `finish_details`, `finish_round`,
  `finish_round_time`, and `total_fight_time_secs` as outcome/finish fields;
- odds and expected-value columns as market timestamps are not audited;
- R/B statistics, records, ranks, streaks, differences, and any supplied
  aggregate as current-fight, post-fight, or rolling temporal provenance is
  unverified;
- every unreviewed source field.

No supplied rolling/aggregate feature is assumed pre-fight safe. Milestone 4
must independently establish `latest_source_timestamp < target_fight_timestamp`
and same-fight exclusion before any feature can use this source.

### Canonical-label mapping status

The M3 canonical mapper can consume the adapter's accepted, raw-linked source
records, but it ships with **no real-source default outcome, finish/method, or
weight-class mapping**. Each mapping is scoped to this source/schema version,
retains the original observed label, and requires a named reviewer, timezone-
aware approval timestamp, rationale, and taxonomy version. An unmapped label or
an unresolved exact fighter alias quarantines the complete source record and
blocks canonical Parquet publication; it is never coerced to an unknown code,
guessed winner, or feature value. Test-only mappings cover synthetic fixture
labels only and are not evidence of the downloaded dataset's full taxonomy.

The completed-bout contract has no reviewed event identifier, event name,
promotion, or start timestamp. The relational M3 loader therefore records the
mapped fight with `event_context_status = not_observed` and no event/source-event
reference. It never groups bouts by date/location or manufactures event facts;
an audited event-capable source is required before event linkage can be loaded.

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

## M3 dual-source contract (2026-07-17)

The Ultimate UFC Dataset local input is now retained at
`data/incoming/ultimate-ufc-dataset/ufc-master.csv`. Its immutable SHA-256 is
`deb1cd9a7014c08a538875e2b585e6f51fbf8f7a6d3f981eb684db1bd7242dc5`
(3,198,027 bytes), matching the supplied expected digest. It remains CC BY
4.0 with recorded Kaggle attribution. `upcoming.csv` is scoring-only and
excluded from historical training. All `*_dif`, `R_ev`, `B_ev`, results,
finish details, total fight time, supplied R/B snapshots, and supplied market
derivatives remain quarantined. Project differences are only `red - blue`;
market features may later be recomputed only from `R_odds` and `B_odds`.
The local-only run `5aa550c81d624934b62ea93dffc84739` accounted for 7,177
rows from 118 columns with zero quarantines.
That is **zero quarantined rows**, not zero quarantined fields: every accepted
row carries 111 excluded source fields. The restricted interim Parquet exposes
15 context/provenance/audit columns and no unsafe source field. A hard
model-ready gate rejects every direct `R_`/`B_` field, every `*_dif`, `R_ev`,
`B_ev`, result/finish/timing fields, and other direct source snapshots.

UFC-DataLab is a separate MIT source. Its only approved input is a
byte-for-byte local copy of `data/stats/stats_raw.csv` at
`data/incoming/ufc-datalab/<commit-sha>/stats_raw.csv`. The local
`ingest-ufc-datalab` command does not call GitHub or UFCStats, requires a
pinned commit path, records repository/commit/upstream path/bytes/checksum/
delimiter/encoding/dimensions/timestamp/attribution/run ID, and labels
detailed statistics as post-fight facts. Processed tables, scorecards, and
current fighter-detail snapshots are expressly excluded.

The requested shallow clone did not complete: Git left an empty temporary pack
and invalid HEAD, and a retry encountered a stale shallow lock. No commit SHA,
source dimensions, or raw-file checksum are claimed for UFC-DataLab yet.
The cache deletion required to retry was refused by the execution host before
it ran; the exact requested clone then failed because the invalid non-empty
destination remains. No substitute source or scraped data was used.

Sources are reconciled as parallel traceable observations, never concatenated.
Identity and taxonomy queues are candidate-only; no fuzzy auto-merge or label
default is allowed. Historical features use only `event_time < target_time`;
same-fight/future rows cannot alter a target's features and corner swaps negate
only project-owned difference values.

## UFC-DataLab completion record (2026-07-18)

The prior cache-acquisition blocker is superseded. The valid local checkout is
`https://github.com/komaksym/UFC-DataLab.git` at commit
`3268146c05211de9deab8b9b4c0bb4a954815f0b`; `git status --short` was clean.
Only `data/stats/stats_raw.csv` was copied byte-for-byte to the commit-pinned
incoming path. It is 4,258,380 bytes, SHA-256
`26a49b01247a1f51c0553fbcfd3d1dc6529b4fae3b145799d7433270bafeae10`,
with 8,737 rows and 60 semicolon-delimited UTF-8-SIG columns. The repository
license is MIT. The pinned repository attributes this raw all-bouts export to
UFC Official Fight Statistics (UFCStats); this project made no direct
UFCStats request and did not use scorecards, OCR, processed tables, or fighter
snapshots.

Local run `22ea088e-6af0-57bd-ac84-faacf4c70ac5` published the restricted
post-fight-fact Parquet. One legacy same-day duplicate candidate is retained
as `REV-011.duplicate_unordered_bout:row-8604` for review, not removed.
Candidate-only reconciliation against Ultimate reports 2,176 exact, 3
normalized-exact, 0 corner-swapped, 0 probable, 0 ambiguous, and 4,664
conflicts; 334 Ultimate-only and 1,894 UFC-DataLab-only bouts remain. These
are evidence counts, not canonical links or conflict resolutions.

The candidate-keyed, non-model prior-history proposal has 8,737 rows and 51
columns. It is built only from bouts whose event date is strictly earlier than
the target date; every row is marked `candidate_unreviewed` and therefore is
not a training or model-ready feature view. UFC-DataLab adds 37 identity and
24 taxonomy review items. All are pending; no ambiguous identity or taxonomy
decision was applied.

## M3 reconciliation semantic profile (2026-07-18)

The prior `4,664 conflicts` figure is retained as the original, deliberately
coarse legacy comparison count. It did not distinguish a result side from the
fighter who won when the sources used opposite corner orientation, nor did it
separate source coverage and post-fight detail from outcome risk. The v4
reconciliation run preserves both source observations and emits no merged or
canonical bout.

The local artifacts are under
`data/quarantine/reconciliation/ultimate_ufc_datalab/m3-reconciliation-v5/`:
`reconciliation_summary.json` (all field and combination counts),
`deterministic_or_soft_conflicts.jsonl`, and
`residual_material_conflicts.jsonl`. Every JSONL record retains both raw
source rows, normalized comparison values, rule IDs, and match evidence.

Among 6,843 candidate pairs, semantic disagreement counts by field are:
fighter identity 0; corner orientation 0; outcome 14; event date 0; event
name 6,843 (Ultimate does not expose an event name); weight class 326;
scheduled rounds 44; finish method 4,691; finish round 408; finish time 408;
and location 0. The summary artifact also records every field combination;
the largest are event name + finish method (4,174), event name only (1,915),
and event name + finish method + finish round + finish time (274). Raw-format
variation counts are retained separately, so case/Unicode/punctuation variants
are observable without being presented as semantic conflicts.

The dispositions are: 0 equivalent after complete deterministic normalization;
2,028 soft metadata disagreements (including 1,915 missing-value-only pairs);
0 strictly post-fight-only disagreements; and 4,801 post-fight-detail
disagreements combined with expected event-name absence. There are 334
Ultimate-only and 1,894 UFC-DataLab-only candidates, each classified
`missing_on_one_source`; there are 0 material identity conflicts, 14 material
outcome conflicts, and 0 ambiguous bout matches. The final reviewer queue is
therefore 14 records, not 4,664.

Only unquestionably meaning-preserving comparison rules are applied:
Unicode/whitespace/case/punctuation folding for candidate aliases and text;
ISO date and `m:ss` time normalization; source outcome corner labels mapped to
the winning candidate only for comparison; integer formatting; the audited
presentation suffix `Bout` for the same weight label; and finish-method,
event, and location formatting. No reviewed identity link, taxonomy decision,
fuzzy alias, division interpretation, source precedence, or source-value
overwrite was applied. Post-fight method/round/time differences remain
non-blocking for the candidate pre-fight proposal unless identity or outcome
is uncertain. The proposal remains candidate-only and not model-ready.

## M3 final human-review preparation (2026-07-18)

The source-scoped queues were consolidated without applying any decision into
`data/quarantine/reviews/m3/`: `m3_reviewer_packet.md`,
`m3_identity_decisions.csv`, `m3_taxonomy_decisions.csv`, and
`m3_outcome_conflict_decisions.csv`. The packet has 51 deduplicated identity
decisions, 63 deduplicated taxonomy decisions, and 14 residual outcome
decisions. Repeated source values are grouped under one stable M3 review ID;
each item retains all source spellings, affected source-row/bout counts,
representative queue or reconciliation evidence, confidence, a conservative
recommended action, and blank reviewer decision/notes fields.

Bruno Silva is a dedicated homonym-preservation decision: Flyweight and
Middleweight identities must remain separate. Identity suggestions are
source-backed alias/display candidates only; they explicitly prohibit automatic
or fuzzy merges without corroborating bout, weight-class, physical-profile, or
other source evidence. The 14 outcome rows retain both source record keys,
participants, result and method values: 12 are no-contest-versus-winner cases
(their evidence identifies `Overturned` when present), and 2 are
winner-versus-winner disagreements. No draw or source-parsing case was
observed in this residual set.

`ufc-predictor build-m3-reviewer-packet` deterministically rebuilds the
packet. `ufc-predictor import-m3-reviewer-decisions <completed-csv...>`
accepts only packet-issued IDs and exact evidence hashes; it rejects missing
reviewer/timestamp/rationale, duplicates, stale rows, and contradictions. It
append-records an idempotent reviewer ledger with reviewer, timestamp,
rationale, decision, and source evidence. It does not modify immutable raw
data or itself apply an alias, taxonomy mapping, result, or canonical record.
M3 remains conditionally complete until reviewed decisions are imported and
all later canonical/model-ready gates pass.

## M3 corrected deferred-review packet (2026-07-18)

The original deferred IDs are retired and cannot be accepted by the importer:
`M3-ID-45CDDFCF91DA`, `M3-ID-333577CCC1AF`, and the ten listed deferred
taxonomy IDs in `m3_retired_review_ids.json`. Replacement-only artifacts are
in `data/quarantine/reviews/m3-corrections-v4/`; each replacement has a new
review ID and new evidence hash. The outcome template was not reinterpreted:
its 12 `confirm_overturned` and 2 `select_ufc_datalab` decisions remain the
reviewer's original outcome instructions.

The consolidated Roldan replacement is `M3-ID-524AA01602F1`. It proposes one
canonical display identity, **Roldan Sangcha-an**, while preserving both
source aliases `Roldan Sangcha-an` and `Roldan Sangcha'an`. Seven taxonomy
replacement decisions cover the corrected division text, five exact finish
method mappings, and the explicit null-stance policy. The stance policy keeps
missing as null, prohibits inference, and permits model-ready use only through
null handling or an indicator.

The three aggregate schedule/finish anomalies are replaced by 48 bout-level
items: 27 explicit UFC-DataLab overtime-format records may be preserved only
by an individual approved corrected mapping; 21 Ultimate four-round records
lack attached authoritative correction and each recommends
`exclude_affected_record`. No exclusions or mappings have been applied yet.
The importer accepts `approve_corrected_mapping`, `preserve_null`,
`exclude_affected_record`, and `defer` in addition to the existing explicit
outcome actions. M3 remains conditionally complete until these 56 replacement
decisions are reviewed and imported.

## M3 corrected anomaly-packet audit (2026-07-18)

The claimed 4,827 UFC-DataLab overtime-format records cannot be reproduced
from the immutable 8,737-row source and must not enter a human row-review
queue. `stats_raw.csv` has one aggregate bout record per CSV row (not
per-round statistics or repeated fighter-side records): 8,736 unordered
date/fighter bout keys, with one repeated key. The detector uses only raw
`time_format`, raw `round`, and event date/fighter names for stable dedupe.
`time_format` is the scheduled-format string: overtime extends the parsed
maximum, and `No Time Limit` remains null. A violation is only numeric
`finish_round > parsed_scheduled_rounds`.

The reproducible source profile is **0** flagged rows / **0** flagged bouts,
not 4,827. There are 152 explicit overtime-format rows representing 151
unique bouts; all are within their parsed schedules. The top-20 raw-format
combinations, 30 representative normal/special cases, parsing/null rules, and
dedupe proof are in
`data/quarantine/reviews/m3-corrections-v6/m3_anomaly_detector_audit.md`.
The 21 Ultimate raw-four-round rows are fully enumerated in
`m3_ultimate_four_round_audit.md`: 19 are exact cross-source
`3 Rnd + OT (5-5-5-5)` confirmations and legitimate special formats; two
remain unresolved identity/bout matches. Neither is auto-excluded.

The old 56-item replacement packet is exactly 1 replacement identity, 6 exact
taxonomy mappings, 1 missing-stance-null policy, 27 individual DataLab format
items, and 21 individual Ultimate four-round items (1 + 6 + 1 + 27 + 21 =
56). The evidence-bound v6 packet replaces that detector output with 20
decisions: 1 identity, 6 exact taxonomy, 1 null policy, 9 grouped DataLab
special formats, 1 grouped Ultimate confirmation, and 2 unresolved bout
actions. Thus 46 of the old 48 bout review records are deterministic false
positives (27 DataLab + 19 Ultimate); the remaining two are exclusion
candidates, with zero exclusions applied. The 152/151 valid special-format
rows/bouts are preserved as explicit formats, not silently normalized.

`build-m3-correction-packet` now writes the deterministic v6 packet, evidence
hashes, retirement manifest, and both audit artifacts. Focused tests prove
that standard three-round decisions and finishes, five-round finishes,
overtime formats, duplicate source rows, and impossible round values are
handled correctly. No raw source, reviewer decision, canonical record,
feature, or model was modified. M3 remains **conditionally complete**.

## M3 v6 imported-decision validation (2026-07-18)

Validated the immutable v6 ledger at
`data/quarantine/reviews/m3-corrections-v6/m3_imported_decisions.jsonl`.
It contains exactly 34 unique active IDs, with zero blank or deferred rows,
and replays idempotently as 0 new / 34 replayed. The ledger checksum is
`e4092ca73c5d15dc8695db33c291f6a472b5fe0e36b0d705a19fc64fa37215bb`.
Its decision composition is 1 identity, 6 exact taxonomy mappings, 1 null
stance policy, 9 special-format groups, 1 Ultimate four-round confirmation,
2 reviewed exclusions, and 14 outcome resolutions (12 overturned no-contests,
2 UFC-DataLab winner selections). Reviewer, timezone-aware timestamp,
rationale, v6-issued ID, and recomputed evidence hash checks pass.

Canonical/model-ready materialization is deliberately still blocked. The v6
ledger is a closed set of 34 correction/outcome decisions; it does not contain
the source-wide exact fighter-alias and observed-label taxonomy authority that
the existing canonical mapper requires for every Ultimate/UFC-DataLab row.
The older queue files contain additional unledgered approval records and may
not be silently treated as v6 authority. Inventing aliases, outcome labels,
or taxonomy mappings would weaken the no-unresolved-data gate. No raw source,
canonical output, feature table, model, or partial ledger was modified; M3
remains **conditionally complete** pending an authorized complete source-wide
decision ledger or an explicit reviewed mapping package.

## M3 final authority materialization (2026-07-18)

The closed v6 ledger is retained unchanged. A separate immutable supplemental
ledger migrates only the 49 identity and 53 taxonomy approvals from the
completed legacy packet after packet evidence-hash, reviewer, timezone-aware
timestamp, retirement, and supersession checks. Twelve deferred or retired
rows are rejected. This resolves the old coverage defect without claiming that
every unchanged source spelling requires a human mapping: exact source values
map to themselves when unambiguous, while transformations remain source- and
field-scoped reviewed authority. No fuzzy identity merge is used.

`materialize-m3` reads only the two audited local raw CSVs and writes derived
Parquet snapshots under `data/processed/m3-authority-v1/`. Its model-ready
view contains only project-owned strictly-prior history values; it excludes
source differences, odds, rankings, result fields, finish fields, and current
fight statistics. Same-day bouts are calculated from a pre-date snapshot.
