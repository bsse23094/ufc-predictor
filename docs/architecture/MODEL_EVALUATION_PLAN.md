# Model evaluation plan

## Evaluation goals

Evaluation must answer: Are probabilities accurate out of time? Are they calibrated? Do they remain valid across important cohorts and prediction horizons? Are improvements over simple ratings real? Does uncertainty identify weak cases? Can the exact result be reproduced?

## Frozen chronological split

Boundaries are defined by event date/timestamp after the source audit shows coverage. They are stored as immutable dates/event IDs in a split manifest, never recomputed from row order.

Initial allocation guidance:

| Split | Approximate chronological share | Use |
|---|---:|---|
| Train | earliest 60-70% | Fit preprocessing, feature adjustments, estimator |
| Validation | next 10-15% | Hyperparameters, feature/model selection |
| Calibration | next 10-15% | Fit calibrators, confidence mapping, fixed thresholds |
| Final test | latest 10-15% | One-time release estimate only |

Shares are guidance, not fabricated dates. Boundaries fall between events. One event, fight, both orientations, repeated snapshots, and related synthetic variants share a group and split. If multiple prediction horizons exist for one fight, all are grouped unless the evaluation explicitly models real repeated forecasts without allowing target leakage.

The final test manifest is access-controlled and unopened until the model/feature/calibration policy is frozen. Once used, it remains a historical benchmark; future iterations require a newer rolling holdout.

## Walk-forward validation

Within pre-test history, use expanding-window folds:

    Fold k: train on all events before boundary k
            validate on the next contiguous block of events
            optional gap/embargo for timestamp or schedule ambiguity

Use at least enough folds to cover era changes and reliable cohort counts, determined after audit. Report mean, dispersion, and time trend rather than only pooled metrics. All fit-dependent transforms, opponent adjustments, OOD references, and rating hyperparameters are recomputed inside each fold.

Nested Optuna tuning uses only fold training/validation. Trial counts, search spaces, sampler seed, pruning, and objective are logged. Compute budget is capped in advance to prevent test-driven persistence.

## Labels and eligibility

- Winner evaluation includes only cases allowed by the versioned decisive-outcome policy.
- Method evaluation maps verified outcomes through the versioned KO/TKO, submission, decision taxonomy.
- Duration uses verified scheduled rules and result time; exclusions/censoring are reported.
- Decision/judging evaluation is conditional and shadow-only until sample/coverage gates pass.
- Changed/overturned outcomes follow the dataset's as-of-label policy and are reported.
- Every exclusion has a counted reason.

## Metrics

### Winner

- accuracy and balanced accuracy at a predeclared 0.5 rule;
- ROC-AUC and PR-AUC;
- log loss as primary probability score;
- Brier score;
- expected calibration error with fixed/predeclared bins and adaptive-bin sensitivity;
- calibration intercept/slope and reliability curves;
- confusion matrix;
- precision, recall, F1;
- prediction coverage/abstention;
- confidence-stratified log loss, Brier, accuracy, and coverage.

Accuracy is descriptive, not the sole promotion objective. Confidence intervals use event/group-aware bootstrap where feasible.

### Method and joint paths

- multiclass log loss and Brier score;
- macro/weighted per-class precision, recall, F1 and PR-AUC where defined;
- one-vs-rest ROC-AUC with support caveats;
- confusion matrix;
- classwise calibration curves/ECE;
- reconciliation adjustment magnitude;
- coherence violations, which must be zero after reconciliation.

### Round, duration, and survival

- mean/median absolute error for expected duration;
- root mean squared error as a tail-sensitive secondary metric;
- round accuracy and within-one-round accuracy for baselines;
- survival negative log likelihood/Brier score over time;
- calibration of finish-by-round/time;
- expected-versus-observed duration by scheduled format and method;
- bounds/coherence violation count.

### Judging

- decision likelihood metrics inherited from Model C;
- conditional split/disagreement log loss, Brier, PR-AUC, recall/precision at declared operating points;
- calibration and coverage;
- scorecard/judge coverage and label-confidence report.

### Uncertainty

- risk-coverage curve and area;
- error/log-loss by confidence tier;
- OOD detection on synthetic corruptions, held-out eras/cohorts, and debut fighters;
- correlation of disagreement/missingness with error;
- calibration intervals and bootstrap stability;
- unsupported/abstention rate and false-confidence review.

## Required cohorts

All applicable metrics are evaluated separately by:

- each weight class with sufficient support;
- men's and women's divisions;
- debut versus established fighters;
- ranked versus unranked status as known at cutoff;
- three-round versus five-round format;
- main events versus other bouts;
- low-data versus higher-data matchups under predeclared count rules;
- confidence tier and OOD state;
- prediction horizon buckets;
- source completeness and market availability;
- calendar era/fold.

No cohort below the minimum reportable support is silently omitted. Show count, mark estimate unstable, and use interval/suppression rules that avoid misleading precision. Exact thresholds are set in the first evaluation policy based on data volume, before candidate comparison.

## Baseline comparisons

Every candidate is compared with:

- empirical cohort prior;
- Elo/Glicko rating baseline;
- regularized logistic feature baseline;
- prior champion, if any;
- Model A versus Model B at matched rows/horizons;
- raw versus calibrated candidate;
- optional public/golden benchmark only on a declared comparable intersection.

Use paired, event-aware bootstrap differences for log loss/Brier and report interval/effect size. A tiny metric improvement may be rejected if latency, calibration, subgroup behavior, or complexity worsens.

## Market evaluation

Model B is assessed only where timestamp-valid market inputs exist. Reports include coverage to prevent favorable selection from being hidden. Compare:

- A and B on identical fights/cutoffs;
- normalized market-only baseline if legally and semantically available;
- performance by horizon and quote age/provider dispersion;
- incremental calibration and log-loss benefit;
- missing-market cohort separately.

The system does not translate model edge into betting returns in the MVP.

## Leakage and contamination audit

Before metric computation:

- assert chronological event boundaries and group disjointness;
- verify max lineage timestamp for all feature snapshots;
- reject target fight IDs in source lineage;
- scan feature names and provenance for target/result/closing/future-ranking deny lists;
- verify fit artifacts name only authorized rows;
- poison future and post-fight fixture values and compare hashes/predictions;
- confirm both orientations stay within group and weights;
- ensure calibrator and OOD reference saw no final-test row.

A leakage failure invalidates the entire run, not one metric.

## Calibration protocol

Choose the calibration family through predeclared walk-forward/calibration analysis, then fit exactly once on the dedicated calibration split. Report raw and calibrated metrics. Reliability plots include uncertainty and sample counts. Recalibration creates a new calibration artifact/model bundle version even if the estimator is unchanged.

Model B, method/path, and format-specific duration may need separate calibrators only when support justifies them; excessive segmentation is avoided because it overfits small UFC samples.

## Robustness and stability tests

- repeat training with declared seeds and quantify prediction variance;
- perturb numeric inputs within measurement precision;
- mask optional feature families;
- swap fighter orientation;
- test source correction/replay;
- compare serialization before/after registry load;
- test dependency/container rebuild;
- evaluate plausible data drift and schema novelty;
- verify monotonic domain expectations only where scientifically justified, not imposed casually.

## Release report

The immutable evaluation artifact contains:

- executive model card and intended/not-intended use;
- dataset, split, feature, code, estimator, calibration, and environment versions;
- row/exclusion accounting;
- metric tables with intervals;
- cohort and horizon tables;
- calibration, ROC/PR, confusion, risk-coverage, drift, and duration plots;
- baseline/champion paired comparisons;
- leakage/quality test results;
- latency, memory, artifact size, and load time;
- known limitations and approval/signatures.

## Promotion policy

Primary gates are no leakage/coherence/security failure, non-inferior or improved out-of-time log loss/Brier, acceptable calibration, no material cohort regression without approved rationale, and service-budget compliance. Numeric tolerances are baselined after Milestone 5 and committed before later candidate evaluation.

If final test fails, the candidate is rejected. Fixing it starts a new model version; repeated iteration must not keep consulting the same final holdout as if untouched.

