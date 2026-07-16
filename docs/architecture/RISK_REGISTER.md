# Risk register

## Scoring

Probability and impact are Low, Medium, High, or Critical. Owners are accountable roles, not necessarily current people. Status begins Open unless the mitigation is already an architectural control.

| ID | Risk | Probability | Impact | Owner | Early indicator | Prevention/mitigation | Contingency |
|---|---|---|---|---|---|---|---|
| R-001 | Source terms prohibit or restrict automated access/retention | High | Critical | Product/data owner | Legal audit unresolved, robots/terms change | Complete source audit before enablement; minimal/polite access; licensed alternatives | Disable source/feature, retain only permitted metadata, revise scope |
| R-002 | UFCStats/third-party schema changes silently | High | High | Data engineering | New fingerprint, parse/null/row-count shift | Raw preservation, fingerprints, fixtures, quarantine, alerts | Keep last approved dataset; patch adapter and backfill |
| R-003 | Historical timestamps cannot prove as-of availability | High | Critical | Data/ML owner | Missing publish/quote times, current-page history | Conservative ingested time; exclude unprovable features; bitemporal facts | Launch without rankings/market/attribute family |
| R-004 | Target/post-fight leakage enters features | Medium | Critical | ML owner | suspicious metric jump, lineage violation | PointInTimeJoiner, poison tests, deny-list, independent audit | Invalidate dataset/models/predictions; rollback and publish correction |
| R-005 | Closing odds or future rankings contaminate history | Medium | Critical | ML/data owner | horizon performance implausible, identical current ranks | timestamp-required schemas, mode allow-lists, cutoff tests | Disable Model B/ranking features; rebuild from clean version |
| R-006 | Winner-first/red-blue orientation leakage | Medium | High | ML owner | swap inconsistency, slot-target correlation | canonical outcome-free slot, dual training/inference, pair features | Block promotion and rebuild feature/model version |
| R-007 | Fighter identity false merge/split corrupts histories | High | High | Data steward | name collision, impossible concurrent fights, profile conflicts | source aliases, conservative thresholds, review queue, audit | Split/merge correction; lineage invalidation and forward rebuild |
| R-008 | Silent row loss or untraceable imputation | Medium | High | Data/ML owner | count imbalance, sudden coverage gain | row accounting, missing reason, feature flags, fitted artifact lineage | Block publication; rebuild and issue quality notice |
| R-009 | Train/validation/test contamination | Medium | Critical | ML owner | duplicate fights across splits, unexpectedly stable metrics | frozen chronological group manifests, fit-scope tests, test access policy | Reject run; establish new future holdout if test overused |
| R-010 | UFC sample size is inadequate for complex/rare tasks | High | High | ML/product owner | wide intervals, unstable fold/class metrics | baselines, shrinkage, simple tabular models, support labels | Defer Model E/rare cohorts; expose unsupported rather than overfit |
| R-011 | Market data coverage is selected/biased | High | High | ML owner | Model B evaluated on easier subset | matched A/B evaluation, coverage by horizon/provider, separate product | Keep pure model primary; limit/withdraw B |
| R-012 | Scorecard/pre-UFC data are incomplete or biased | High | Medium/High | Data/ML owner | cohort/geography/era gaps | experimental nullable features, coverage reports, gated Model E | Shadow-only/omit features |
| R-013 | Calibration deteriorates after era/rules changes | Medium | High | ML owner | ECE/slope drift, risk tiers invert | walk-forward, delayed monitoring, recalibration versioning | Roll back/recalibrate on authorized data; lower confidence |
| R-014 | Model outputs disagree across winner/method/time | Medium | High | ML owner | sums/bounds/reconciliation adjustments | six-path model, constrained reconciliation, hazard bounds, property tests | Block output; fall back to supported subset |
| R-015 | Confidence is mistaken for probability of correctness | High | High | Product/design owner | user copy/support feedback | decomposed semantics, plain-language tier, usability review | Change copy/UI; remove overall tier if misleading |
| R-016 | Counterfactuals are interpreted as real or causal | High | High | Product/ML owner | shared screenshots without context | separate observed/modified types, bounds, labels, non-causal explanations | Disable sharing/control; add watermark/context |
| R-017 | Monte Carlo approximation overclaims fight mechanics | Medium | Medium | ML/product owner | users infer exchange simulation | call it sampling, publish engine/limitations/MC error | Limit distributions; defer advanced claims |
| R-018 | Model artifact loading enables code execution/tampering | Low/Medium | Critical | Security/platform owner | digest mismatch/untrusted URI | trusted CI/registry, digest/signature, safe format, isolated warm-up | Quarantine artifact, rollback, rotate credentials, incident response |
| R-019 | Dataset poisoning or compromised source | Medium | Critical | Security/data owner | distribution/conflict/volume anomalies | provenance, checksums, cross-source/quality review, manual approval | Freeze current alias, investigate/rebuild from raw trusted objects |
| R-020 | Public API/simulation abuse causes cost or outage | High | High | Backend/platform owner | rate/queue/CPU spike | layered quotas, caps, cache, async workers, backpressure | Disable expensive capability; tighten limits/scale worker |
| R-021 | In-process models exhaust API memory or block event loop | Medium | High | Backend owner | load time/RSS/latency saturation | bounded bundles, profiling, worker/thread controls, warm replicas | Reduce ensemble; extract model service via ADR |
| R-022 | PostgreSQL/Redis/object dependency outage | Medium | High | Platform owner | probes/pool/queue alerts | managed services, timeouts, cache degradation, durable jobs/backups | serve immutable cache where safe, pause writes/jobs, restore/failover |
| R-023 | Migration locks or incompatibility break rollout | Medium | High | Backend/platform owner | staging duration/lock warning | expand-contract, migration job, representative test/backup | halt deploy, old compatible app, forward fix/restore |
| R-024 | Single-host low-cost MVP failure | Medium | Medium/High | Platform owner | host restart/zone incident | managed DB/object, immutable images, restore/runbook | redeploy host within RTO; communicate outage |
| R-025 | Backup exists but cannot restore | Medium | Critical | Platform owner | missed/failed drill | scheduled isolated restore and golden integrity check | incident recovery from object/raw rebuild; extend outage |
| R-026 | Secrets or licensed raw data leak via Git/logs/API | Medium | Critical | Security owner | scanner alert, raw path/error output | ignore policy, secret/large-file scans, redaction, response allow-list | revoke/rotate, remove exposure, legal/incident process |
| R-027 | Dependency/supply-chain vulnerability | Medium | High | Security/platform owner | SCA/container finding | locks, SBOM, pinned CI, minimal images, patch cadence | block/rebuild/rollback; exception with owner/expiry |
| R-028 | Frontend misrepresents probability/conditioning | Medium | High | Design/product owner | user testing confusion, mismatch values | typed contracts, joint path tables, labels, accessibility/table alternatives | Correct UI/copy; hide ambiguous visualization |
| R-029 | Accessibility/responsive requirements slip | Medium | Medium | Frontend owner | axe/visual failures, keyboard block | component primitives, CI, manual screen-reader/mobile gates | block release of affected path; simplified fallback |
| R-030 | Model/data drift remains invisible due delayed labels | Medium | High | ML/observability owner | OOD/prediction shift before outcome metrics | input/prediction drift and label coverage monitoring | reduce confidence, freeze promotion, investigate source/model |
| R-031 | Current/frozen prediction semantics are confused after corrections | Medium | High | Backend/product owner | old result changes on GET | immutable snapshots and explicit as-of/version; new corrections create new rows | restore original snapshot; publish correction notice |
| R-032 | Operational cost exceeds MVP budget | Medium | Medium | Platform/product owner | worker/object/log spend trend | lifecycle, quotas, exact search, CPU inference, on-demand training | reduce retention of rebuildable telemetry/interim, scale-to-zero, pause expensive features |
| R-033 | Team redesigns components during implementation, breaking contracts | Medium | High | Technical lead | directory/schema divergence, undocumented tech | Terra contract and ADR requirement, architecture CI links/review | pause affected milestone; write superseding ADR/migration plan |
| R-034 | Source outcome corrections invalidate evaluation labels | Medium | Medium | Data/ML owner | revised result after report | bitemporal labels, report versioning, maturity window | recompute monitoring/evaluation artifact; retain old report |
| R-035 | Ethical/regulatory perception becomes gambling-oriented | Medium | High | Product/legal owner | copy/features focus on odds/edge | no betting features/advice, pure model first, responsible-use review | remove market-facing surfaces; legal review |

## Top risks before implementation

The immediate critical path is R-001/R-003 (source legality and temporal evidence), R-007 (identity), R-004/R-009 (leakage/contamination), and R-010 (sample support). Architectural sophistication cannot compensate for failure in these areas.

## Unresolved decisions and owners

| Decision | Due gate | Owner | Required evidence |
|---|---|---|---|
| Enabled sources and legal retention | End M2 | Product/data owner | Completed audit/terms review |
| Exact target fight timestamp policy when bout time unknown | End M2/M4 | Data/ML owner | Source precision study and leakage-safe rule |
| Canonical method/result mappings | End M3 | Data steward/ML | Observed label inventory |
| Identity auto-link thresholds | End M3 | Data steward | Labeled collision set and false-merge tolerance |
| Split dates and cohort support thresholds | Start M5 | ML owner | Approved dataset coverage |
| Calibration families and promotion numeric gates | Before final test M6 | ML owner | Walk-forward/baseline evidence |
| Model B public readiness/provider | End M6 | ML/product/legal | timestamp coverage, matched evaluation, terms |
| Model E public versus shadow | End M6 | ML/product | scorecard coverage and calibration |
| Counterfactual allowed ranges | M11 | ML/product | training support plus domain review |
| MVP host/provider and budget ceiling | M13 | Platform/product | measured load/cost and data residency |

## Review process

Review the register at every milestone gate, source/model promotion, security incident, and quarterly maintenance. Any High/Critical accepted risk needs an owner, rationale, expiry/review date, monitoring signal, and contingency. Closing a risk requires evidence; architecture text alone is not mitigation completion.

