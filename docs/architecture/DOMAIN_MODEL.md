# Domain model

## Ubiquitous language

| Term | Meaning |
|---|---|
| Fighter | A canonical person identity, independent of any provider spelling or profile. |
| Alias | A source-scoped identifier/name believed to refer to one fighter, with resolution evidence. |
| Event | A promotion event with a scheduled/actual date and venue context. |
| Fight | A scheduled or completed bout; status changes are history, not destructive rewrites. |
| Participant | A fighter's role in a fight. Red/blue or display order is context, not target truth. |
| Observation | A source fact with event/effective time and system ingestion time. |
| Prediction cutoff | The time at which knowledge is frozen for an analytical request. |
| Horizon | Time from cutoff to scheduled fight start; a required evaluation dimension. |
| Feature snapshot | An immutable point-in-time vector with lineage and missingness. |
| Prediction snapshot | Immutable model output for one input/cutoff/version tuple. |
| Pure prediction | A prediction whose feature policy forbids market-derived data. |
| Market-informed prediction | A separate prediction using eligible odds observations as of cutoff. |
| Counterfactual | A synthetic copy of an input in which named values are user-adjusted. |
| Simulation | Repeated stochastic draws from a versioned probability model/engine. |
| Dataset version | An immutable manifest of raw/canonical inputs and exclusions. |
| Model bundle | Estimator, preprocessing, feature signature, calibration, thresholds, metadata, and integrity digest. |

## Bounded contexts

### Source acquisition

Owns source definitions, retrieval policies, raw objects, checksums, and ingestion runs. It knows provider keys but not product-facing identity.

### Identity and catalog

Owns canonical fighters, aliases, promotions, events, fights, participants, divisions, and resolution decisions. Ambiguous identity is a domain state, not a best-effort join.

### Historical performance

Owns rounds, statistics, results, scorecards, judges, rankings, odds observations, and ratings. Facts retain source and bitemporal metadata.

### Feature and dataset

Owns feature definitions, lineage, dataset/split manifests, point-in-time snapshots, and quality reports. Only this context is allowed to create model inputs.

### Modeling

Owns experiment runs, model versions, calibrators, evaluation, promotion state, and champion aliases. It consumes published dataset versions and cannot edit them.

### Prediction

Owns requests, immutable prediction snapshots, reconciliation, explanations, and input completeness. It consumes approved feature snapshots and model bundles.

### Simulation and retrieval

Owns counterfactual specifications, Monte Carlo jobs/results, standardized similarity vectors, and neighbor explanations. Observed and modified values are different value types.

### Governance and operations

Owns users/roles where needed, audit events, data-quality issues, freshness, administrative approvals, and retention.

The contexts are code-module boundaries inside a modular monolith and ML package, not separate network services. This preserves clear ownership without the operational cost of microservices.

## Core aggregates and invariants

### Fighter aggregate

- A fighter has one stable UUID and zero or more aliases.
- An alias key is unique within source and alias type.
- A merge records from/to IDs, reviewer/reason, and timestamp; identifiers are not silently reused.
- Physical attributes are observations with provenance and validity, not timeless columns where history matters.
- An unresolved or conflicting identity blocks feature publication for affected fights.

### Event and fight aggregate

- A fight belongs to one event and has exactly two active participants for supported MMA prediction.
- Participant orientation is canonical/deterministic and independent of outcome. Source red/blue is retained as observation only.
- Result, method, rounds, and time may be absent for scheduled fights.
- Draw, no contest, overturned, canceled, and unknown are explicit statuses; they are never coerced to a winner.
- Scheduled rounds and round length define valid duration bounds.
- Schedule revisions are timestamped so historical prediction horizons remain reproducible.

### Observation aggregate

Every source observation has:

- provider and provider record key;
- raw object/checksum and parser/schema version;
- source_observed_at when the platform/provider observed the fact;
- effective_at/valid interval when the fact applies in the sport;
- ingested_at when the platform stored it;
- optional supersedes reference and quality state.

This bitemporal design increases query care but is required to reproduce what was known at a past cutoff after a later correction.

### Feature snapshot aggregate

Identity is:

    target or hypothetical matchup
    + prediction_as_of
    + orientation
    + feature_set_version
    + dataset_version

Invariants:

- latest_source_timestamp < target_fight_timestamp;
- latest_source_timestamp <= prediction_as_of, with the strict fight bound always taking precedence;
- no source fight equals the target fight;
- every derived feature points to definition and lineage summaries;
- missing values remain explicit and are accompanied by reason/indicator;
- content hash changes if any value, lineage, order, or definition changes;
- snapshots are immutable after publication.

The brief states a strict latest_source_timestamp less than target_fight_timestamp. The cutoff bound permits equality for a market observation recorded exactly at cutoff; the implementation can use a half-open interval. Any provider timestamp precision ambiguity is handled conservatively by excluding the boundary observation.

### Prediction snapshot aggregate

- Contains exactly one request mode and model-bundle version.
- Probabilities are validated and reconciled.
- Links to immutable input/feature hashes.
- Does not mutate when a model is promoted or source fact corrected.
- Revised product views create a new snapshot.
- Explanation metadata states algorithm, baseline cohort, availability, and version.

### Counterfactual aggregate

- Holds observed values and modifications separately.
- Modification fields come from an allow-list with domain and plausibility bounds.
- Does not write back to fighter history or canonical observations.
- Carries the base prediction and changed-factor attribution.
- UI/API always label values synthetic.

## Outcome taxonomy

Canonical outcomes must retain more detail than the MVP predicts:

- decisive win/loss;
- draw;
- no contest;
- overturned/changed result;
- canceled/not contested;
- unknown/pending.

Canonical methods should preserve provider detail, then map through a versioned taxonomy to:

- KO/TKO;
- submission;
- decision;
- excluded/other/unknown.

The mapping is not specified until real source labels are audited. Training eligibility is a versioned policy, never a parser side effect.

## Probability model

For supported decisive bouts:

- P(fighter A wins) + P(fighter B wins) = 1.
- Six joint path probabilities represent fighter by KO/TKO, submission, or decision.
- Summing three paths for a fighter reconciles to that fighter's win probability.
- Summing both fighters for a method yields the method probability.
- Round/duration distributions are conditional or joint as explicitly labeled; unconditional display values must include the conditioning contract.

Draw/no-contest estimation is deferred until data support exists. Responses say the winner distribution is conditional on a decisive modeled outcome. This is less comprehensive but avoids fabricating a weak rare-class probability.

## State transitions

### Ingestion run

    requested -> fetching -> parsed -> validated -> published
                    |          |          |
                    +--------> failed/quarantined

Only published runs contribute to an approved dataset. Retry creates/reuses idempotent work while preserving attempts.

### Dataset version

    building -> validation_failed
        |
        v
    candidate -> approved -> superseded

Approved and superseded manifests are immutable.

### Model version

    training -> failed
        |
        v
    candidate -> validated -> staging -> champion -> archived
                                   |          |
                                   +<-- rollback

Promotion is an alias change plus audit event; it does not mutate the artifact.

### Prediction job

    accepted -> queued -> running -> succeeded
                    |        |
                    +------> failed/canceled/expired

## Domain services

- IdentityResolver proposes matches and manages review evidence.
- PointInTimeJoiner enforces temporal eligibility.
- FeatureSnapshotBuilder computes typed versioned features.
- PredictionRouter selects pure/market mode and champion bundle explicitly.
- ProbabilityReconciler enforces winner/method/path coherence.
- ConfidenceAssessor combines calibrated uncertainty components without calling confidence a probability of correctness.
- CounterfactualValidator applies allow-list and plausibility rules.
- SimilarityRetriever filters eligibility, standardizes by training reference, retrieves neighbors, and explains distance contributions.

## Ownership rule

Only the owning context writes its tables. Cross-context reads go through repository interfaces or published snapshots. This constraint adds some mapping code but prevents the API, scrapers, and notebooks from bypassing temporal and identity invariants.

