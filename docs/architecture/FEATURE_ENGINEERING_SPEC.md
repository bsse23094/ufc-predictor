# Feature engineering specification

## Objective

Create one reproducible, point-in-time feature pipeline for training, scheduled inference, and ad hoc matchups. The pipeline must represent only information available at prediction_as_of and before the target fight, preserve missingness, and behave symmetrically when fighters are swapped.

No feature in this document implies that a source actually supplies the necessary fields. Each family is enabled only after the source audit proves temporal provenance, coverage, and semantic validity.

## Feature registry

Every feature definition is a versioned registry entry containing:

- stable name, feature family, semantic description, owner;
- scalar/vector type, unit, legal bounds, nullability;
- entity grain and window;
- exact source fact types and source precedence;
- eligibility/cutoff rule and aggregation formula;
- orientation behavior: invariant, fighter-specific, symmetric, or antisymmetric;
- missingness/imputation policy;
- fit dependency and authorized split;
- quality and minimum-support rules;
- lineage granularity;
- first/last version and deprecation reason.

Renaming or changing meaning creates a new feature/version. A registry diff is part of every model card.

## Snapshot keys and layout

Long-form computation uses one row per target fight, prediction cutoff, and fighter. The final pairwise row contains:

    target_fight_id or hypothetical_matchup_id
    target_fight_timestamp
    prediction_as_of
    fighter_a_id, fighter_b_id
    orientation_id and orientation_policy_version
    dataset_version, pipeline_version, feature_set_version
    fighter_a features
    fighter_b features
    symmetric context
    signed differences and interactions
    lineage summary and content hash

Training creates both orientations only after a fight is assigned to a split. Both rows carry the same group_id and sample weights sum to one original fight.

## Eligibility

For target T and cutoff C, a source observation O is eligible only if:

1. its effective relationship to the target is valid;
2. its knowledge timestamp is strictly earlier than min(T, C), conservatively handling timestamp precision;
3. if derived from a fight, source_fight_id differs from target_fight_id and the source fight was completed/known before cutoff;
4. it belongs to the approved dataset manifest;
5. its canonical identity is resolved and quality state is eligible.

Eligibility is applied before windows or aggregations. The builder fails if any output lineage max violates the bound.

## Feature categories

### Fighter-level historical features

Computed separately for each fighter:

- prior fight counts overall and in the relevant division/context;
- career-to-date wins, losses, outcomes, and eligible method summaries;
- rolling summaries over the previous 1, 3, 5, and 10 eligible fights;
- exponentially weighted summaries using registry-defined half-life/decay;
- recent form and streaks derived from eligible historical outcomes;
- age and age-squared at target timestamp from a temporally valid birth observation;
- height, reach, stance, and their missing/age-of-observation flags;
- days since previous fight, fights per time window, and layoff bands;
- weight-class transition and prior history in current/adjacent class;
- prior scheduled/completed five-round and main-event experience;
- short-notice indicators only from a verified timestamped schedule-change source;
- finish rates with Bayesian/empirical shrinkage denominators;
- durability proxies from eligible knockdown/stoppage and absorbed-performance history;
- round-by-round trends and late-versus-early deltas;
- stance-specific history and sample count;
- pre-UFC record summaries only from individually dated, resolved prior bouts.

Counts and denominators always accompany rates so the model and confidence layer can distinguish 1/1 from 20/20.

### Opponent quality and adjusted features

- pre-fight Elo and Glicko rating/uncertainty updated sequentially after each eligible fight;
- strength of schedule from opponents' pre-fight ratings, never their later peak/current rating;
- opponent-adjusted striking and grappling values from residual/hierarchical adjustment fitted only on the training window;
- quality-weighted recent form using opponent pre-fight rating;
- ranking and ranking movement from latest eligible dated publications.

Elo updates use an outcome-independent canonical order and versioned K/initialization policy. Glicko time decay observes inactivity. Hyperparameters are fitted/tuned without validation, calibration, or test leakage. New fighters receive an explicit prior and high uncertainty.

Opponent adjustment is produced through out-of-fold estimates for training rows. A model fitted on a row may not generate its own adjusted feature. Later splits use an adjustment model fitted only on earlier authorized data. This complexity is justified because naive full-data residuals leak targets.

### Fight-level context

- scheduled division/weight class;
- scheduled rounds and round length/ruleset when verified;
- main/co-main/title/context flags only as known at cutoff;
- event date/location/elevation/travel proxies only with reliable provenance;
- prediction horizon and schedule-revision recency;
- gender/division grouping as a sporting cohort, using respectful canonical taxonomy;
- debut/returning and data-availability context.

Event IDs, fighter names, source red/blue order, and high-cardinality identifiers do not enter estimators.

### Pairwise differences

For eligible numeric feature x:

    x_diff = x_A - x_B
    x_abs_diff = abs(x_A - x_B) only when useful and symmetric

Signed differences are antisymmetric on swap; absolute differences are invariant. Raw A/B values may remain for nonlinear models, but orientation augmentation and swap averaging are mandatory.

Examples include age, reach, height, recency, activity, rating, rank, experience, finish/durability, and recent-form differences. Unit compatibility and both-side missingness are validated.

### Interaction features

Interactions express matchup mechanisms, not arbitrary multiplication:

- striker pressure/offense versus opponent striking defense;
- wrestling/takedown offense versus opponent takedown defense;
- submission offense versus opponent submission defense;
- stance pair plus each fighter's eligible stance-specific experience;
- reach/height difference with style/pressure proxies;
- activity and cardio trend under three- versus five-round format;
- offensive pace versus opponent durability/late-round trend;
- layoff, age, and recent activity interactions;
- weight-class move with physical/experience differences.

Each interaction has component support counts and missingness. Pressure, cardio, short-notice, and style proxies remain experimental until a defensible observed definition is approved.

### Market features

Allowed only in Model B:

- original and normalized eligible implied probability;
- latest-as-of quote and age;
- opening-to-current movement where both observations predate cutoff;
- provider dispersion/liquidity proxies if actually available;
- missing/provider-count flags and prediction horizon.

De-vig/normalization policy is versioned. Closing, result-derived, and post-cutoff quotes are deny-listed. The Model A feature schema fails if a market-prefixed or market-lineage feature appears.

### Confidence and data-quality features

- eligible prior-fight and round counts;
- recency and source age;
- missing count/fraction by family;
- imputation flags/reasons and identity resolution quality;
- source coverage and disagreement flags;
- rating deviation/uncertainty;
- distance to training support and categorical novelty;
- debut and sparse-opponent flags;
- schedule/odds timestamp precision;
- model disagreement inputs.

These may feed Model F or appear as product metadata. Quality features cannot make invalid facts eligible.

## Rolling computation

Historical facts are sorted by effective fight completion timestamp, then deterministic fight ID for stable ties. Windows use prior rows only:

- window 1 captures immediate previous performance;
- 3, 5, and 10 capture increasingly stable form;
- career-to-date uses all eligible history;
- exponentially weighted values use elapsed time or fight sequence as declared per feature.

For rate features, store numerator, denominator, rate, and shrunk rate. Empty windows are null, not zero. Partial windows are allowed with count flags.

Polars lazy frames are preferred for typed, parallel batch transforms; DuckDB performs manifest and exploratory SQL; Pandas is restricted to library interoperability. Mixing engines requires explicit dtype/null and parity tests.

## Missingness and imputation

Missing values are categorized:

- not applicable;
- not yet observed/debut;
- source unavailable;
- identity unresolved;
- invalid/quarantined;
- stale beyond policy;
- structurally absent.

Raw canonical data is never imputed. Feature snapshots keep null plus category flags. Estimator preprocessing may:

- use CatBoost native missing handling;
- use training-only median/most-frequent or explicit unknown category for baselines;
- use bounded domain priors only when documented;
- add missingness indicators.

Imputer statistics and code are part of the model bundle. No global pre-split imputation is allowed. The API reports family completeness before imputation so filled values do not overstate certainty.

## Preferred fighter orientation strategy

Use four mutually reinforcing controls:

1. Assign a deterministic canonical orientation independent of winner, such as sorted stable fighter UUIDs; retain source color separately.
2. Train on both A/B orientations after split assignment, remapping targets and giving each half weight.
3. Use signed difference/symmetric features where interpretable, while allowing paired raw values for nonlinear capacity.
4. Infer both orientations and average after remapping:

       p_A = (model(A,B) + 1 - model(B,A)) / 2

The same remapping applies to fighter-specific method paths. This is preferred to random red/blue alone because it gives a testable symmetry guarantee and eliminates seed-dependent imbalance. It doubles row-level inference/training work, but UFC-scale data makes that cost small. Hard antisymmetric model constraints are deferred because mainstream tabular libraries do not support them cleanly and may reduce useful nonlinear capacity.

Required tests:

- swapped winner probabilities differ only within numerical tolerance after reconciliation;
- method paths swap exactly by fighter;
- invariant context stays equal and signed differences negate;
- same fight/orientations share split and aggregate weight;
- source red/blue or winner-first indicators cannot enter feature schema.

## Feature materialization

1. Select target grid and cutoff policy.
2. Resolve canonical participants and context as known at cutoff.
3. Query eligible observations through PointInTimeJoiner.
4. Compute fighter histories and ratings sequentially.
5. Apply train-authorized opponent adjustment.
6. assemble context, paired differences, interactions, and optional market namespace.
7. validate types, bounds, symmetry, lineage, row accounting, and temporal invariant.
8. write immutable Parquet partition and manifest.
9. optionally publish the exact approved online snapshot to PostgreSQL.

Online inference never rebuilds history from arbitrary API joins. Scheduled snapshots are preferred; ad hoc builds invoke the same versioned builder and cache/store the result.

## Feature change process

A change requires registry update, leakage review, unit/property tests, historical backfill impact, dataset version decision, model retraining, and feature drift baseline. Semantic changes create a feature-set major/minor version; bug fixes that alter values create a new dataset and snapshot even if the public name stays.

## Pseudocode for the critical guard

~~~text
cutoff = conservative_min(target_fight_timestamp, prediction_as_of)
eligible = observations.where(
    knowledge_timestamp < cutoff
    and source_fight_id != target_fight_id
    and quality_state == ELIGIBLE
)
snapshot = aggregate(eligible)
assert snapshot.latest_source_timestamp < target_fight_timestamp
assert snapshot.latest_source_timestamp < cutoff
publish_immutable(snapshot, lineage_hash)
~~~

This is illustrative only; implementation belongs in Milestone 4.

