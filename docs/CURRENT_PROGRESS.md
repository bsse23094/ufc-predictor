# Current progress audit

Date: 2026-07-17
Inspected commit: `d688ce2` (`Add UFC predictor architecture`)

## Verified repository state

The committed history still contains only the accepted architecture baseline. The implementation is an uncommitted worktree, including the foundation, source-neutral M2 code, migrations, tests, and documentation. `README.md` and `docs/architecture/DATA_SOURCE_AUDIT.md` were already modified when this audit started; all implementation files are untracked relative to `main`.

No approved canonical data, feature snapshot, trained model, catalog API, prediction endpoint, or product UI exists. A narrowly approved, local-file-only Kaggle completed-bout adapter now exists in the untracked worktree; it has no network scraper and no feature/training authority. Do not treat the untracked implementation as delivered until it is deliberately reviewed and committed.

## Milestone status

| Milestone | Status | Verified assessment |
|---|---|---|
| 1. Repository foundation | Partial | Python/Node workspaces, Compose, migrations, health shell, CI policy checks, web build, API-image build, and live PostgreSQL/Redis tests pass. The complete Compose app profile starts and serves API `/health` plus the web shell. The canonical `just` flow remains unverified because its documented executable is not installed locally. |
| 2. Raw-data ingestion | Complete — approved local Kaggle scope | The locked Polars wheel is installed and checksum-verified. Dedicated fixtures, the whole Python suite with live Compose coverage, static checks, Alembic SQL validation, and a local CLI replay all pass. The local-only Kaggle adapter preserves source bytes/checksums/provenance, quarantines unsafe fields, and writes a restricted Parquet projection. UFCStats remains explicitly red and has no adapter or scraper. |
| 3. Identity and canonical data | In progress | Candidate-only normalization, conservative equal-key candidate pairing, versioned scoring, review contracts, canonical fighter/alias schema, append-only durable review evidence, reviewed-link application, bitemporal alias correction, guarded canonical merge/split transitions, source-shaped canonical Parquet mapping, and transactional relational loading retain exact aliases and raw provenance. Canonical mapping accepts only exact reviewed aliases and reviewer-attributed source/schema outcome, method, and division mappings; it preserves raw labels, separates results from future feature inputs, quarantines every gap/conflict, and blocks partial publication. The loader publishes only a balanced mapping result with source references, fights, deterministic participant slots, applied identity evidence, and results. Mapping or relational/replay failures are now recorded as idempotent blocking `data_quality_issues`, keyed by source record and raw checksum, before catalog publication remains blocked. The source lacks a reviewed event identifier, so it explicitly stores `event_context_status = not_observed` instead of inventing events. No real-source taxonomy defaults are approved. Fixture acceptance is covered; real-source M3 acceptance remains blocked on a manually acquired file and reviewed labels/aliases. |
| 4. Temporal features | Not started | No target grid, point-in-time joiner, feature registry, lineage validator, ratings, or split manifest. |
| 5. Baseline modeling | Not started | No approved dataset, splits, baselines, training run, or artifact. |
| 6. Calibration and full evaluation | Not started | No candidate, calibration artifact, evaluation report, or registry. |
| 7. Database and FastAPI foundation | Partial | Settings, error envelope, request IDs, session helper, governance models/repository, and migrations exist. The M3 relational catalog schema is present, but catalog/freshness endpoints, auth, cache, and truthful dependency readiness remain absent. |
| 8. Prediction service | Not started | No feature snapshots, bundles, runtime, workers, or prediction endpoints. |
| 9. Frontend foundation | Partial | Next.js shell, tokens, shared error/empty states, generated health types, formatting tests, lint/typecheck/build exist. No API client, query provider, accessibility/visual suite, or backend integration. |
| 10. Core prediction experience | Not started | No domain pages or real product data. |
| 11. Simulation and similarity | Not started | No implementation. |
| 12. Explainability | Not started | No implementation. |
| 13. Testing and hardening | Not started | Foundation policy/CI scaffolding exists, but no release traceability, load/security drills, or recovery coverage. |
| 14. Deployment and observability | Not started | Local Compose and basic logs exist; no staging/production topology, telemetry, dashboards, alerts, backups, or runbooks. |

## Work completed in this session

- Added `DataGovernanceRepository`, an API-owned PostgreSQL adapter for the ML ingestion persistence port.
- Durable runs now create/retry/replay by source and idempotency key; a completed replay performs no fetch.
- Every locally persisted response is recorded as a raw object/retrieval before transport, schema, parse, or row-accounting work continues. Terminal records persist counts, quality issues, checkpoint visibility, and safe failure state.
- Quarantined or failed equivalent runs can be retried with the same durable run ID and an incremented attempt; only a published run exposes `new_checkpoint`.
- Added forward migration `0002_raw_object_source_scope`. It scopes raw-object catalogue identity to the originating source, preserving unambiguous provenance when two sources retain identical bytes. Object storage may still deduplicate the underlying checksum-addressed blob.
- Added live Compose/PostgreSQL integration coverage for retry persistence, idempotent replay, quarantine retry, raw-object provenance, quality issues, and checkpoint behavior. All fixtures remain synthetic and live under temporary test directories.
- Fixed the read-only API/worker container startup path by putting uv's runtime cache under the existing `/tmp` tmpfs. The app-profile integration test polls the API liveness endpoint after container startup rather than assuming a process is immediately ready.
- Completed the UFCStats access audit to a red/no-go decision. Published UFC terms prohibit the contemplated automation, while separate UFCStats terms, robots policy, licence, retention, rate policy, and representative schemas could not be verified. No source response or raw bytes were persisted.
- Rebuilt the API image with the Dockerfile `/tmp` cache change and started the newly built API/web Compose profile successfully; API `/health` returned `ok` and the web shell returned `200`.
- Audited Kaggle's `mdabbert/ultimate-ufc-dataset` current public metadata: CC BY 4.0, version 181, update `2026-04-01T23:37:51.8Z`, owner `mdabbert`, and stated merged-source provenance. Recorded required CC BY attribution and a manual, version-pinned Kaggle CLI command. The environment has neither Kaggle CLI nor Kaggle credentials, so it downloaded no source bytes.
- Added the approved `kaggle-ultimate-ufc-dataset` local-file policy and `ingest-kaggle-ultimate` CLI. It reads only `data/incoming/ultimate-ufc-dataset/ufc-master.csv`; it never scrapes UFCStats, Kaggle, or an upstream mirror.
- Added immutable raw-manifest and durable-policy metadata for declared dataset licence, attribution, original filename, source schema version, checksum, retrieval timestamp, and ingestion-run ID. Added forward migrations `0003_kaggle_local_provenance` and `0004_dataset_license_policy`.
- Added fixture-backed validation for required columns, ISO dates, positive rounds, results, duplicate unordered bouts, raw-input immutability, checksums, idempotent reruns, output field quarantine, source-policy attribution/licence, and the CLI. The interim output uses neutral fighter-pair names and marks source R/B ordering as unverified; no outcome, odds, ranking, record, statistic, or supplied rolling field is output as a feature.
- Completed the local Kaggle M2 verification after installing the exact locked `polars==1.30.0` wheel from the official PyPI artifact and validating its SHA-256 against `uv.lock`. Fixed the Windows-only Parquet durability failure by opening the completed staging file read/write for `fsync`; immutable publication semantics remain unchanged.
- Updated the stale foundation CLI assertion to the current safety contract: network ingestion remains disabled while audited local-file commands are explicit.
- Began M3 with `identity/normalize.py` and fixture tests. The slice normalizes only for candidate comparison, preserves the original source alias and raw SHA-256, groups equal keys without resolving them, and rejects incomplete/untraceable interim rows.
- Extended the M3 identity boundary with conservative candidate-pair generation, a versioned exact-normalized-alias score, and stable review-queue/decision contracts. Candidate pairs exclude same-record comparisons; every score is `review_required`, has an explicit `None` auto-link threshold, and retains raw SHA-256 evidence. Review decisions require a named reviewer, timezone-aware timestamp, and rationale but cannot assign a canonical ID.
- Added `0005_catalog_identity`, API-owned fighter/alias/review models, and a review-evidence repository. Canonical aliases require a canonical fighter plus source/raw-object lineage; provider external IDs are unique only within source/type when present. Fighters reject self-merges, and PostgreSQL rejects any update or deletion of an identity decision. The live integration test proves review persistence retains both candidate raw SHA-256 values and enforces append-only behavior.
- Added `0006_identity_resolution_app` and the reviewed-link application boundary. A decision can reach exactly one append-only terminal outcome: validated `propose_link` evidence creates source/raw-traceable aliases for an unmerged canonical fighter, while malformed, incomplete, conflicting, or non-link attempts are durably quarantined. Replays return the stored outcome; no candidate score can assign an identity. Live PostgreSQL tests cover exact-evidence application, replay, quarantine, and mutation rejection.
- Added `0007_alias_supersession` and bitemporal reviewed-alias correction. A superseding durable `propose_link` decision must reference the prior decision and exactly revalidate its source/raw evidence. It closes only the current aliases created by that prior decision, creates corrected replacements for a different unmerged fighter, and records each old-to-new link in an append-only ledger. Invalid correction attempts quarantine instead of rewriting history.
- Added `identity/resolver.py`, `0008_identity_merge_split`, and guarded canonical identity transitions. Only an original durable `propose_merge` review whose two exact current aliases belong to the selected active fighters can merge them. The database rejects direct merge/retarget/restoration mutations and alias reassignment/deletion. A durable `propose_split` review must supersede the exact active merge decision, retain evidence for both current aliases, restore only the absorbed fighter, and create an append-only split ledger. Both operations replay safely; invalid evidence durably quarantines.
- Added `canonical/{taxonomy,models,mappers,publisher}.py`. The mapping slice consumes only accepted Kaggle ingestion records with retained raw references, requires exact reviewed fighter aliases, derives outcome winners only from an explicit source-field taxonomy decision, and uses an outcome-independent UUID ordering for canonical participants. Original outcome/method/division labels remain present beside explicit canonical codes; missing mappings, aliases, malformed fields, and post-resolution duplicate fights quarantine whole rows. An immutable canonical Parquet/manifest publisher refuses partial results. The production taxonomy is deliberately empty pending source-label review; mappings in tests are synthetic-only.
- Added `ufc_api.fights` and migration `0009_canonical_bout_catalog`. `CanonicalCatalogRepository` atomically and idempotently loads only zero-quarantine mapped facts into raw-linked source references, divisions, fights, deterministic slots, applied identity-decision evidence, and results. Published fights require exactly two participants and one current result; winner ownership and applied matching identity evidence are database-validated. The approved source's event context remains explicitly `not_observed`; no date/location grouping or event fact is invented.
- Added `canonical/validation.py` and migration `0010_canonical_quality_issues`. A quarantined mapping must carry an audit issue and cannot enter catalog publication. Mapper quarantines and relational or conflicting-replay catalog failures now persist a blocking `data_quality_issues` report with source-record/raw-checksum evidence. A partial unique issue key makes repeated failures increment `occurrence_count` instead of creating duplicate reports; the catalog transaction still rolls back completely.

## Files changed this session

- Runtime/persistence: `apps/api/src/ufc_api/data/repository.py`, `apps/api/src/ufc_api/data/models.py`, `services/ml/src/ufc_predictor/ingestion/{registry,policies,raw_store,runner,kaggle_ultimate}.py`, `apps/api/migrations/versions/{0002_raw_object_source_scope,0003_kaggle_local_provenance,0004_dataset_license_policy}.py`
- M3 identity/canonical: `services/ml/src/ufc_predictor/identity/{normalize,candidates,scorer,review,resolver}.py`, `services/ml/src/ufc_predictor/canonical/{taxonomy,models,mappers,publisher,validation}.py`, `apps/api/src/ufc_api/fighters/{models,repository}.py`, `apps/api/src/ufc_api/fights/{models,repository}.py`, `apps/api/migrations/versions/{0005_catalog_identity,0006_identity_resolution_application,0007_alias_supersession,0008_identity_merge_split,0009_canonical_bout_catalog,0010_canonical_quality_issues}.py`
- Environment/dependencies: `apps/api/Dockerfile`, `apps/api/pyproject.toml`, `compose.yaml`, `pyproject.toml`, `uv.lock`
- Tests: `tests/data/test_kaggle_ultimate_ingestion.py`, `tests/integration/test_ingestion_persistence.py`, `tests/integration/test_canonical_catalog_persistence.py`, `tests/integration/test_compose_health.py`, `tests/api/test_data_governance_models.py`
- Documentation: `README.md`, `docs/architecture/DATABASE_SCHEMA.md`, `docs/architecture/DATA_SOURCE_AUDIT.md`, and `docs/SESSION_REPORT.md`

## Verification results

The historical pass rows through `just test` describe the source-neutral tree before this Kaggle/Polars change. The subsequent rows are the current-tree evidence and supersede them where a check now depends on Polars or the new migrations.

| Check | Result |
|---|---|
| `git status --short`, `git log --oneline -15`, `git diff` | Inspected; implementation remains untracked from `main` |
| `uv run ruff format --check apps/api/src services/ml/src tests scripts` | Pass |
| `uv run ruff check apps/api/src services/ml/src tests scripts` | Pass |
| `uv run mypy` | Pass (61 source files) |
| `uv run pytest` | Pass (29 tests, including Compose app startup, migrations, and durable-ingestion integration) |
| `corepack pnpm lint` | Pass |
| `corepack pnpm typecheck` | Pass |
| `corepack pnpm test` | Pass (2 tests) |
| `corepack pnpm build` | Pass |
| `corepack pnpm check:generated` | Pass |
| `docker compose config --quiet` | Pass |
| `uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head --sql` | Pass; includes `0002_raw_object_source_scope` offline SQL |
| `uv run python scripts/check_architecture.py` | Pass, including after the UFCStats decision-record update |
| `uv run pytest tests/architecture/test_repository_contract.py` after the audit update | Pass (4 tests) |
| `uv run python scripts/check_repository_policy.py` | Pass |
| `corepack pnpm audit --prod --audit-level high` | Pass; no known vulnerabilities |
| Docker Compose dependencies, live migrations, durable ingestion, and app profile | Pass through the integration suite; direct probes returned API `health=ok`, readiness `ready`, and web `200` |
| `docker compose --profile app build api` | Pass; rebuilt successfully with the Dockerfile `/tmp` cache setting |
| `docker compose --profile app up -d --wait api web` after that rebuild | Pass; API `/health` returned `ok`, web returned `200`, then the profile was removed |
| `just test` | Blocked: `just` is not installed or on `PATH` |
| `uv lock` after adding required `polars==1.30.0` | Pass |
| `uv run ruff format services/ml/src/ufc_predictor/ingestion/kaggle_ultimate.py services/ml/src/ufc_predictor/{cli.py,ingestion/policies.py}` | Pass |
| `uv run ruff check apps/api/src services/ml/src tests scripts` | Pass after the Kaggle implementation |
| `uv run python -m py_compile services/ml/src/ufc_predictor/ingestion/kaggle_ultimate.py services/ml/src/ufc_predictor/ingestion/policies.py services/ml/src/ufc_predictor/cli.py` | Pass |
| `uv run ruff format --check apps/api/src services/ml/src tests scripts` | Pass (68 files) |
| `uv run pytest tests/data/test_ingestion_contract.py tests/data/test_raw_store.py` | Pass (10 tests); confirms the generic executor/raw-manifest contracts after provenance metadata changes |
| `uv run pytest tests/api/test_data_governance_models.py tests/architecture/test_repository_contract.py` | Pass (7 tests) |
| `uv run pytest tests/data/test_kaggle_ultimate_ingestion.py` | Blocked during collection: `polars` is not installed yet; no fixture test executed |
| Full `pytest` | Blocked during collection by the same missing `polars` import (29 other tests collected); it was not bypassed |
| `mypy` | Blocked only by the missing `polars` implementation in the new adapter and its fixture test after correcting the independently detected duplicate-key type error |
| `.venv\\Scripts\\alembic.exe -c apps/api/alembic.ini upgrade head --sql` | Pass; renders migrations through `0004_dataset_license_policy` |
| `uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head --sql` | Blocked before Alembic by the Polars download attempt; the direct virtualenv invocation above verifies the same migration chain without dependency resolution |
| `.venv\\Scripts\\python.exe scripts/check_architecture.py` and `scripts/check_repository_policy.py` | Pass |
| `docker compose config --quiet` and `git diff --check` | Pass |
| `uv sync --all-packages --group dev --frozen` and direct download of the pinned Polars wheel | Blocked by transfer timeout. Direct download stopped after 180 seconds at 4,259,840 of 36,363,630 bytes; the partial wheel is outside the repository in the system temp directory. |

### M2 closure verification (current tree)

The rows above retain the pre-install audit trail. The following commands supersede their Polars-blocked results.

| Check | Result |
|---|---|
| Official locked wheel resumed from the partial artifact with `curl.exe --fail --location --retry 10 --retry-all-errors --retry-delay 5 --connect-timeout 60 --continue-at -` | Pass; `polars-1.30.0-cp39-abi3-win_amd64.whl`, 36,363,630 bytes, SHA-256 `c26b633a9bd530c5fc09d317fca3bb3e16c772bd7df7549a9d8ec1934773cc5d`, exactly matching `uv.lock`. |
| `uv pip install --python .\\.venv\\Scripts\\python.exe <verified-local-wheel>`; `uv sync --all-packages --group dev --frozen --offline` | Pass; `polars==1.30.0` imports under Python 3.12.11. No pin or lockfile changed. |
| `uv run pytest tests/data/test_kaggle_ultimate_ingestion.py -q` | Pass; 8 tests. The first run exposed a read-only `fsync` descriptor on Windows; the corrected read/write descriptor preserves the durability barrier. |
| `uv run pytest -q` | Pass; 37 tests, including live Compose PostgreSQL/Redis migration, durable-ingestion, and application-profile tests. |
| `uv run ruff format --check apps/api/src services/ml/src tests scripts`; `uv run ruff check apps/api/src services/ml/src tests scripts`; `uv run mypy` | Pass; 68 files formatted, Ruff clean, mypy clean across 64 source files before the M3 slice. |
| `uv run python scripts/check_architecture.py`; `uv run python scripts/check_repository_policy.py`; `git diff --check`; `docker compose config --quiet` | Pass. |
| `uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head --sql` | Pass; renders through `0004_dataset_license_policy`. |
| Fixture CLI replay: `uv run ufc-predictor ingest-kaggle-ultimate --incoming-directory <temporary fixture copy> --raw-root <temporary raw root> --interim-root <temporary interim root>` | Pass; first run published two accepted rows, rerun replayed the same run ID without re-ingestion. Raw SHA-256 `e8be33f0c53180428a4fb0d6826f412e33e12844f013e40f50ecbf3b16717324` matched the incoming bytes and manifest. |
| Direct generated-Parquet inspection with Polars | Pass; the 15-column schema contains only context/provenance fields. `Winner`, finish fields, `R_`/`B_` source ordering, current statistics/records, odds, and other quarantined names are absent; each row records the quarantined source columns. |
| Static local-adapter scan and fixture execution | Pass; the local adapter/CLI has no HTTP client and contains no Kaggle/UFCStats fetch path. The only UFCStats occurrence is an explicit no-contact documentation statement. |
| Final repository verification after the M3 slice: `uv run ruff format --check apps/api/src services/ml/src tests scripts`; `uv run ruff check apps/api/src services/ml/src tests scripts`; `uv run mypy`; `uv run pytest -q`; architecture/repository checks; `docker compose config --quiet`; Alembic SQL | Pass; 70 files formatted, Ruff clean, mypy clean across 66 source files, 42 tests passed, documentation/policy/Compose checks passed, and migrations render through `0004_dataset_license_policy`. |
| M3 candidate/review continuation: the same repository-wide command set | Pass; 74 files formatted, Ruff clean, mypy clean across 70 source files, 47 tests passed, documentation/policy/Compose checks passed, and migrations still render through `0004_dataset_license_policy`. |
| M3 catalog-identity persistence continuation: the same repository-wide command set | Pass; 77 files formatted, Ruff clean, mypy clean across 73 source files, 51 tests passed, documentation/policy/Compose checks passed, and migrations render through `0005_catalog_identity`. |
| M3 reviewed-resolution application continuation: `uv run ruff format --check apps/api/src services/ml/src tests scripts`; `uv run ruff check apps/api/src services/ml/src tests scripts`; `uv run mypy`; `uv run pytest -q`; architecture/repository-policy checks; `git diff --check`; `docker compose config --quiet`; and Alembic offline SQL | Pass; 77 files formatted, Ruff clean, mypy clean across 73 source files, and 53 tests passed. Live Compose tests prove exact-evidence application, idempotent replay, durable quarantine, and append-only terminal outcomes; migration SQL renders through `0006_identity_resolution_app`. |
| M3 alias-correction continuation: `uv run ruff format ...`; `uv run ruff check ...`; `uv run mypy`; Alembic offline SQL; and `uv run pytest -q tests/api/test_fighter_identity_models.py tests/integration/test_ingestion_persistence.py tests/integration/test_compose_health.py` | Pass; Ruff clean, mypy clean across 73 source files, offline migration SQL renders through `0007_alias_supersession`, and 12 focused tests pass. Live PostgreSQL coverage proves current aliases close, replacements are current for the corrected fighter, old-to-new ledger links persist, replay is idempotent, and ledger mutation is rejected. |
| Final M3 alias-correction repository gate: `uv run ruff format --check apps/api/src services/ml/src tests scripts`; `uv run ruff check apps/api/src services/ml/src tests scripts`; `uv run mypy`; `uv run pytest -q`; architecture/repository-policy checks; `git diff --check`; `docker compose config --quiet`; and Alembic offline SQL | Pass; 77 files formatted, Ruff clean, mypy clean across 73 source files, and 54 tests passed. Architecture/policy, Compose, and migration SQL checks pass through `0007_alias_supersession`. |
| M3 merge/split continuation: `uv run pytest -q tests/data/test_identity_candidate_review.py tests/api/test_fighter_identity_models.py tests/integration/test_ingestion_persistence.py` | Pass; 17 tests, including live PostgreSQL migration through `0008_identity_merge_split`. Fixture evidence proves an applied merge and a superseding split are idempotent, aliases remain on their original fighter records, malformed merge evidence quarantines, and direct alias mutation, unreviewed restoration, or direct re-merge after a split is rejected. |
| Live forward-migration replay: `alembic downgrade 0007_alias_supersession`; `alembic upgrade head`; `uv run pytest -q tests/integration/test_ingestion_persistence.py tests/integration/test_compose_health.py` | Pass; the revised `0008_identity_merge_split` migration was applied live from its predecessor, and all 8 affected Compose/PostgreSQL tests passed. |
| Final M3 merge/split repository gate: `uv run ruff format --check apps/api/src services/ml/src tests scripts`; `uv run ruff check apps/api/src services/ml/src tests scripts`; `uv run mypy`; `uv run pytest -q`; architecture/repository-policy checks; `git diff --check`; `docker compose config --quiet`; and Alembic offline SQL | Pass; 78 files formatted, Ruff clean, mypy clean across 74 source files, and 57 tests passed. The first complete run exposed the stale Compose migration assertion, which now expects the actual `0008_identity_merge_split` head and ledger tables; the rerun passed. Architecture/policy, Compose, and migration SQL all pass through `0008_identity_merge_split`. |
| M3 canonical mapping/taxonomy repository gate: `uv run ruff format --check apps/api/src services/ml/src tests scripts`; `uv run ruff check apps/api/src services/ml/src tests scripts`; `uv run mypy`; `uv run pytest -q`; architecture/repository-policy checks; `git diff --check`; `docker compose config --quiet`; and Alembic offline SQL | Pass; 83 files formatted, Ruff clean, mypy clean across 79 source files, and 61 tests passed. Four fixture-backed canonical tests prove complete raw-linked mapping, outcome-independent slots, deterministic immutable Parquet replay, no default taxonomy interpretation, unresolved alias/taxonomy quarantine, partial-publication rejection, duplicate canonical-fight detection, and conflicting taxonomy rejection. Architecture/policy, Compose, and migration SQL all pass through `0008_identity_merge_split`. |
| M3 relational canonical catalog repository gate: `uv run ruff format --check apps/api/src services/ml/src tests scripts`; `uv run ruff check apps/api/src services/ml/src tests scripts`; `uv run mypy`; `uv run pytest -q`; architecture/repository-policy checks; `git diff --check`; `docker compose config --quiet`; and Alembic offline SQL | Pass; 86 files formatted, Ruff clean, mypy clean across 82 source files, and 63 tests passed. Live PostgreSQL fixture coverage proves transactional source-reference/fight/participant/identity-evidence/result publication and idempotent replay. The source's missing event identifier remains `not_observed`; database constraints reject mismatched identity evidence and an incomplete published participant set. Architecture/policy, Compose, and migration SQL all pass through `0009_canonical_bout_catalog`. |
| M3 durable canonical conflict/quarantine gate: `docker compose up -d --wait postgres redis`; `uv run ruff format --check apps/api/src services/ml/src tests scripts`; `uv run ruff check apps/api/src services/ml/src tests scripts`; `uv run mypy`; `uv run pytest -q`; architecture/repository-policy checks; `git diff --check`; `docker compose config --quiet`; and Alembic offline SQL | Pass; 87 files formatted, Ruff clean, mypy clean across 83 source files, and 66 tests passed. Fixture and live PostgreSQL coverage proves each mapping quarantine has an audit issue, report evidence retains source-record/checksum provenance, catalog writes roll back, and repeated mapping or replay conflicts aggregate into one blocking report. Migration SQL renders through `0010_canonical_quality_issues`. |
| Live forward migration validation | Pass; after restoring the healthy local Compose dependencies, `.venv\\Scripts\\alembic.exe -c apps/api/alembic.ini upgrade head` and `current` report `0010_canonical_quality_issues (head)`. An earlier `uv run` invocation correctly timed out because the test suite had already removed its temporary Compose database; no migration failure occurred. |

## Data and ML integrity

- The initial UFCStats scope is red, not approved: no automated source access, adapter, fixture, raw retention, or field may be enabled. R-001 and R-003 remain open critical risks until a licensed alternative is approved.
- The strict feature invariant `latest_source_timestamp < target_fight_timestamp` is not implemented because Milestone 4 has not started. There is no canonical data, feature code, or training path, so no current-fight, future, post-fight, late-odds, winner-first, or test data can enter training features today.
- M2 persistence does not authorize unbounded network access. UFCStats remains disabled and absent from the registry. The one enabled policy is a bounded local-file read backed by a licensed Kaggle audit; it contains no credentials and no download/scraping logic. Tests use only synthetic payloads.
- The strict feature invariant `latest_source_timestamp < target_fight_timestamp` remains an M4 hard gate. The local adapter does not construct features or train models: it quarantines results/finishes, odds, R/B stats, records, ranks, streaks, differences, supplied aggregates, unreviewed fields, and unverified source orientation.
- `0001_governance_raw.py` combines the handoff's planned governance and raw-quality scopes. It was not rewritten; provenance correction is a forward `0002` migration.

## Remaining blockers

1. A real local ingestion still requires the user to manually acquire the reviewed Kaggle file and place `ufc-master.csv` in `data/incoming/ultimate-ufc-dataset/`; no source data is present in this workspace. M3 cannot complete real-source acceptance until observed source labels receive reviewed taxonomy decisions and its fighter aliases receive reviewed resolution decisions. This does not block fixture-backed M2 acceptance.
2. Install `just` to verify the canonical local task-runner entrypoint. The underlying direct checks, API image recipe, Compose profile, migrations, and health probes are verified; this remains an M1 tooling gap rather than an M2 gate.
3. Review and commit the untracked implementation; otherwise a fresh clone of `main` contains none of this work.

## Exact next development task

When the manually acquired approved Kaggle file is available, ingest it through the local-only pipeline, generate the M3 review queues from its observed aliases and labels, obtain reviewer-attributed identity and taxonomy decisions, then run the complete M3 acceptance gate. Keep event/source-event references empty until an audited source supplies them; do not infer events, add taxonomy defaults, start temporal features, or train models.

## M3 dual-source continuation (2026-07-17)

- Verified and copied the supplied Ultimate file byte-for-byte to its required
  ignored incoming path. SHA-256:
  `deb1cd9a7014c08a538875e2b585e6f51fbf8f7a6d3f981eb684db1bd7242dc5`.
  Local ingestion run `5aa550c81d624934b62ea93dffc84739` published all
  7,177 rows from 118 columns (3,198,027 bytes); no rows were quarantined.
  This is row-level accounting: all 7,177 rows retain a 111-field quarantine
  list, while those 111 source fields are absent from the restricted output and
  forbidden by the pre-fight/model-ready schema gate.
- Added the local-only pinned UFC-DataLab raw adapter and CLI. It preserves raw
  bytes first; validates semicolon rows, dates, participants, outcomes, rounds,
  finish combinations, and unordered duplicates; then publishes a source-shaped
  Parquet with `post_fight_fact` detailed statistics.
- Added candidate-only identity and taxonomy queues, traceable non-destructive
  reconciliation, and strict-before-target historical aggregation with Red/Blue
  values and project-owned differences. The Ultimate source produced 47
  identity review items (12 known-variant/Bruno cases) and 40 taxonomy review
  items affecting 19,701 retained observations; all remain pending review.
  Reviewer-ready proposals are in `data/quarantine/reviews/`; the Bruno Silva
  item explicitly requires separate Flyweight and Middleweight identities.
- Git clone acquisition is blocked by an empty temporary pack/invalid HEAD and
  stale shallow lock. The execution host refused removal of the verified cache
  directory, so the exact retry reports a non-empty destination. No real UFC-DataLab commit/checksum/dimensions,
  reconciliation count, or review count is fabricated. M3 is **partial**:
  deterministic code is complete; real-source intake and review remain pending.

## UFC-DataLab M3 completion continuation (2026-07-18)

- The valid cached checkout is pinned at `3268146c05211de9deab8b9b4c0bb4a954815f0b`.
  Its MIT-licensed `data/stats/stats_raw.csv` was copied byte-for-byte into the
  commit-pinned incoming path. Source SHA-256 is
  `26a49b01247a1f51c0553fbcfd3d1dc6529b4fae3b145799d7433270bafeae10`;
  size is 4,258,380 bytes, 8,737 rows × 60 columns, semicolon/UTF-8-SIG.
- Local-only ingestion run `22ea088e-6af0-57bd-ac84-faacf4c70ac5` published
  all source rows as post-fight facts. One same-day legacy duplicate is a
  retained review item, not a dropped source record. Provenance records the
  repository URL, commit, MIT license, upstream UFCStats attribution, and run.
- Candidate-only reconciliation: exact 2,176; normalized 3; corner-swapped 0;
  probable 0; ambiguous 0; conflict 4,664; Ultimate-only 334; DataLab-only
  1,894. No candidate match created a canonical alias or overwrote a source.
- Strictly-prior, candidate-unreviewed history proposals have 8,737 × 51
  dimensions. They use only event dates strictly before the target and are not
  model-ready/training features while identity review is pending.
- New reviewer proposals: 37 UFC-DataLab identity and 24 taxonomy items,
  stored under `data/quarantine/reviews/`; all remain pending. M3 is
  **conditionally complete**: deterministic two-source work is complete, but
  reviewed identity/taxonomy and reconciliation-conflict decisions are needed
  before canonical/model use.
