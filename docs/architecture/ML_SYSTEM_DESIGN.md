# Machine-learning system design

## Design summary

Use a hierarchy of separately trainable tabular models with an inference-time reconciliation layer, rather than one monolithic multitask network. Winner, method, time, and judging have different labels, missingness, censoring, and calibration needs. Independent training improves diagnosability and allows Model E to remain shadow-only; reconciliation prevents contradictory product outputs. The trade-off is more artifacts and explicit dependency/version management.

## Common training contract

Every run consumes an approved dataset and split manifest, a feature-set version, a code/container digest, deterministic seed set, and declared model configuration. It writes:

- fitted preprocessing and estimator;
- exact ordered feature signature with types/units;
- calibration object and decision/abstention policy;
- training/split/dataset fingerprints;
- evaluation and cohort report;
- SHAP-compatible background/reference sample manifest;
- OOD reference statistics;
- environment/dependency lock and serialization smoke result;
- model card, integrity digest, and compatible API contract version.

MLflow tracks runs, parameters, metrics, tags, artifacts, lineage, and registry state. Large immutable artifacts live in S3-compatible storage; MLflow stores their URI/digest. PostgreSQL holds product-facing model version metadata and promotion audit, not arbitrary pickles.

## Baselines and candidate families

Required baselines:

- constant/empirical prior by eligible training cohort;
- Elo/Glicko rating-only logistic prediction;
- regularized logistic regression with training-only preprocessing.

Primary nonlinear candidates are CatBoost and XGBoost. CatBoost is preferred as the initial champion candidate because it handles missing/mixed tabular features well and needs less encoding; XGBoost is a diversity challenger. An ensemble is promoted only if out-of-time log loss/Brier/calibration improvements justify extra latency and complexity. Optuna searches bounded spaces on walk-forward validation only; the final test never influences tuning.

## Model A: pure winner

Purpose: P(A wins | historical performance, physical/rating/context data), conditional on a decisive supported outcome.

- Feature allow-list excludes market and post-fight/target fields by namespace and lineage.
- Candidate: calibrated CatBoost plus logistic/Elo baselines; optional weighted CatBoost/XGBoost ensemble.
- Target: canonical decisive winner remapped for both orientations.
- Orientation: dual-row training, half weights, dual inference, remapped averaging.
- Output: calibrated pair, uncertainty components, coverage state.

This remains the scientific baseline and is always separately visible, even when Model B is available.

## Model B: market-informed winner

Purpose: Model A feature space plus timestamp-eligible market information.

Train a distinct estimator rather than stacking the output of Model A for the MVP. A distinct model provides a clear no-market boundary and simpler leakage audit. It duplicates training and may learn similar structure, but makes performance attribution honest. A future stack may use out-of-fold Model A predictions, documented by ADR.

Routing rules:

- only requested/declared market mode invokes B;
- required market completeness and quote age policy must pass;
- market snapshot timestamp/horizon are returned;
- if unavailable, return a typed unavailability or an explicitly labeled pure result, never a B-labeled imputation;
- compare incremental value over Model A by horizon, provider availability, and calibration.

## Model C: method and fighter paths

Train a multiclass model over six decisive joint paths:

    A by KO/TKO, A by submission, A by decision,
    B by KO/TKO, B by submission, B by decision

The six-path formulation directly supports fighter-specific paths and is preferable to an independent three-class method model that could disagree with winner probability. Training is separate from Model A; it does not consume Model A's in-sample prediction. At inference, a constrained reconciliation layer adjusts the six raw calibrated probabilities so:

- the A/B marginals match the selected calibrated winner model within a declared method;
- the method marginals remain as close as possible to Model C;
- all values remain nonnegative and sum to one.

Iterative proportional fitting or a small convex KL-minimization step can perform reconciliation. Its algorithm/version/tolerance is part of the bundle. This adds an inference step but guarantees coherent UI numbers.

Draw, no contest, other, and overturned cases are excluded or separately governed by the dataset eligibility taxonomy; they are not forced into the three classes.

## Model D: round and duration

MVP: discrete-time survival/hazard model over versioned time bins up to the scheduled maximum, with features repeated/structured by bin and a decision-at-limit terminal state. It estimates a finish hazard and method/path-compatible duration distribution. Expected duration is derived from the calibrated survival curve; expected finishing round is conditional on a finish and clearly labeled.

A simpler CatBoost multiclass round model plus duration regressor may be retained as a baseline, but separate independent outputs can contradict one another. The discrete hazard model is preferred because it handles right/administrative limits and keeps round/time coherent. The trade-off is more specialized evaluation.

Rules:

- three- and five-round bounds are explicit context;
- duration cannot exceed scheduled duration or become negative;
- decision outcomes land at scheduled limit for unconditional fight duration;
- finish-round display conditions on a finish when appropriate;
- method-conditioned hazards are a future extension after support analysis.

## Model E: decision and judging

Use a staged hierarchy:

1. decision likelihood comes from Model C method marginal;
2. conditional on reaching a decision, a judging model estimates unanimous/split-or-majority risk and disagreement;
3. judge-specific behavior is considered only with sufficient dated scorecard data and ethical/statistical review.

Candidate models are calibrated logistic/CatBoost classifiers with scorecard-derived disagreement targets. Model E remains experimental/shadow-only until coverage, class counts, label consistency, and cohort bias meet gates. A missing judging response must not prevent core prediction.

## Model F: confidence and uncertainty

Model F is a composition layer, not one opaque confidence classifier:

- **aleatoric/decision uncertainty:** entropy and distance from 0.5 of calibrated probabilities;
- **epistemic/model uncertainty:** ensemble/seed/bootstrap disagreement;
- **calibration uncertainty:** confidence interval around calibration error in the relevant cohort;
- **data sufficiency:** eligible fight/round counts, recency, family completeness, debut state;
- **missing-feature uncertainty:** prediction sensitivity across approved imputation/feature masks;
- **OOD risk:** standardized distance/density against training data plus categorical novelty;
- **model disagreement:** Model A candidate/challenger and pure-versus-market delta when both exist;
- **identity/source quality:** resolution, timestamp precision, and conflict flags.

The API returns normalized components, reasons, and a conservative overall tier: low, moderate, or high confidence. The tier mapping is fitted/validated on earlier data and versioned. It is never described as the chance that the prediction is correct. Severe OOD or invalid completeness can produce an unsupported/abstain state.

## Calibration

Winner binary outputs use Platt/sigmoid or beta calibration as the robust default; isotonic is eligible only with enough calibration samples and stable walk-forward evidence. Multiclass method/path uses temperature/vector scaling or Dirichlet calibration with regularization. Survival hazards require calibration of cumulative incidence/survival at clinically/sport-relevant time points.

Calibrators fit only the dedicated chronological calibration split and are immutable child artifacts of the estimator. Selection is based on calibration-split policy established before final-test opening. Calibration must not conceal subgroup harm; reports include cohort curves/ECE with uncertainty.

## Training graph

    approved canonical dataset
              |
       temporal features + frozen split manifest
              |
       train-only fitted transforms/ratings/adjusters
              |
       walk-forward tuning and candidate selection
              |
       fit estimator on authorized pre-calibration data
              |
       fit calibrator/thresholds on calibration split
              |
       one-time final test + cohort/OOD/stability report
              |
       registry candidate -> approval -> staging -> champion

If the selected estimator is refit using validation data, the calibration and final-test chronology remains strict and the exact refit policy is declared before evaluation. No result from final test causes hyperparameter changes; a change creates a new experimental cycle with a new future holdout.

## Explainability

- Global: permutation importance and SHAP summaries on a bounded, versioned evaluation sample.
- Local: TreeSHAP for supported tree models, using an approved background/reference cohort and feature grouping.
- Product display: top factors favoring each fighter, value, baseline, direction, data-quality note, and explanation version.
- Correlated features are grouped and text avoids causal language.
- Counterfactual change explanations compare the base and synthetic snapshot, rather than presenting SHAP as causality.

Expensive local explanations may be precomputed for scheduled fights or executed in workers. Approximation status and algorithm are returned.

## Counterfactual architecture

An allow-listed schema exposes takedown defense, striking defense, layoff, reach difference, format, class change, ranking, recent form, cardio proxy, and activity only when the underlying feature definition exists.

For each control:

- preserve observed value and source/quality;
- validate hard physical/rules bounds and softer empirical plausibility quantiles learned on training data;
- mark modified value synthetic and record user delta;
- recompute dependent differences/interactions through the feature graph;
- run the same orientation, calibration, reconciliation, OOD, and uncertainty path;
- return base/changed probability, deltas, strongest changed feature groups, and warnings.

Out-of-range requests return 422. Plausible but OOD combinations may run with a high-risk warning. Synthetic values never persist as fighter facts.

## Monte Carlo architecture

### MVP

Sample from the reconciled joint distribution of winner and method, then sample duration/round from Model D's compatible conditional distribution. Apply calibration uncertainty by drawing probability parameters from bootstrap/ensemble variants where available. Use deterministic user/request-derived seeds, stream vectorized batches, and return estimates with Monte Carlo standard errors and quantiles.

This calibrated approximation is easy to validate and faithful to model outputs. It does not claim to simulate exchanges or tactics.

### Advanced

Build a semi-Markov round-state transition/hazard model with states such as standing control, grappling/control, damage, submission threat, round end, and absorbing outcomes, learned from suitably granular data. Bayesian hierarchical parameters could share strength for sparse fighters and produce posterior uncertainty. This is more interpretable as a fight process but requires granular reliable state data and substantially harder validation; it is deferred.

## Similar matchup retrieval

Build standardized pairwise vectors from approved pre-fight matchup features. To remove orientation ambiguity, store both orientations or use a symmetric representation and select the lower swap-aware distance. Retrieval:

1. filter prior fights strictly before target cutoff;
2. prefer same/compatible weight-class cohort;
3. standardize with training-only robust center/scale;
4. weight vetted style, physical, rating, experience, and context groups;
5. retrieve candidates with exact nearest neighbors initially;
6. rerank with missingness-aware distance and diversity constraints;
7. explain similarity with top smallest group contributions and important differences.

PostgreSQL/Parquet exact search is sufficient for UFC scale. pgvector/FAISS becomes justified only after measured latency/volume; a vector database now would add operations without value. Historical outcomes are shown as examples, not evidence that the target must follow the same path.

## Promotion gates

A candidate must:

- load and predict with the production image;
- pass schema, leakage, orientation, probability, serialization, and stability tests;
- beat or non-inferiorly match required baselines on predeclared primary metrics;
- meet calibration and cohort guardrails;
- document data/feature/model changes and limitations;
- pass shadow/staging comparison and latency/memory budgets;
- have signed/integrity-checked artifacts and rollback target;
- receive human model-owner approval.

Exact numerical thresholds are established after the first baseline distribution and versioned in model policy; inventing them now would be arbitrary.

## Drift and maintenance

Track input schema/null/coverage, feature distributions, OOD rate, prediction distribution, model disagreement, calibration and outcome metrics once labels mature, by horizon/cohort/model. Delayed labels mean feature and prediction drift alert earlier than performance drift. Retraining is scheduled quarterly for evaluation and event-driven by drift/data volume, but promotion remains gated and manual.

