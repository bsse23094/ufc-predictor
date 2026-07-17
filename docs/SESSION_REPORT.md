# Session report

Date: 2026-07-17
Starting Git commit: `d688ce2` (`Add UFC predictor architecture`)
Ending Git commit: unchanged; no commit was created.

## Audit outcome

The committed repository is architecture-only. The working tree contains a substantial, untracked M1/M2 implementation. After inspecting the architecture contract, repository state, source, migrations, scripts, configuration, tests, and actual command results, M2 is complete for its approved local-file Kaggle scope. The completed UFCStats audit remains an explicit red/no-go decision; it does not authorize an adapter, scrape, raw retention, or feature use.

Milestone 1 is partial, not complete: its direct checks and API image recipe now pass, but the canonical `just` entrypoint remains unavailable in this environment. M2's licensed, manually acquired Kaggle local-file path has no network scraper, feature construction, or model training authority; its locked Polars dependency, fixture suite, full Python suite, migrations, policy checks, and local CLI replay now pass. M3 now includes candidate-only alias normalization, durable human review evidence, reviewed alias application/correction, guarded canonical merge/split transitions, a conservative canonical Parquet mapping boundary, and relational canonical loading; it remains incomplete.

## Functionality completed this session

- Added `apps/api/src/ufc_api/data/repository.py`, which implements the ML package's declared ingestion persistence port without making ML import API internals.
- Persists and validates the durable source policy before each run; records `IngestionRun`, `RawObject`, and append-only `RawRetrieval` metadata after exact raw bytes are stored and before parsing.
- Persists terminal row accounting, quality issues, failure state, and checkpoint publication in short PostgreSQL transactions. Published idempotent replays return the stored run without fetching again.
- Supports retrying quarantined/failed identical runs with an incremented attempt while keeping checkpoint visibility closed until a successful publication.
- Added `0002_raw_object_source_scope`, a forward migration that changes raw-object uniqueness to `(source_id, storage_namespace, sha256)`. This prevents the first source of identical bytes from owning another source's provenance record; the storage backend can still checksum-deduplicate bytes.
- Added live Compose/PostgreSQL tests for durable retry persistence, replay idempotency, quarantine recovery, retrieval metadata redaction, raw provenance, quality issue persistence, and atomic checkpoint behavior.
- Fixed the API/worker read-only filesystem startup failure by directing uv's runtime cache to the existing `/tmp` tmpfs in both the image recipe and Compose profile. Added a bounded API-health polling integration test; the Compose API/web profile now starts and serves API `/health`, `/readiness`, and the web shell.
- Completed the initial UFCStats access review as an explicit red/no-go decision. The published UFC terms prohibit the contemplated automation; the source hostname's own terms, robots policy, licence, retention allowance, rate ceiling, and schemas could not be verified. No response was retained and no source adapter was added.
- Rebuilt the API image successfully after the Dockerfile cache change and restarted the rebuilt API/web profile. The API health endpoint returned `ok` and the web shell returned HTTP `200` before teardown.
- Audited Kaggle's public `mdabbert/ultimate-ufc-dataset` metadata and recorded its CC BY 4.0 licence, CC attribution duties, owner `mdabbert`, version 181, update `2026-04-01T23:37:51.8Z`, `ufc-master.csv` completed-bout contract, version-pinned manual CLI command, and stated upstream provenance. The file-list API did not enumerate files; the documented `kaggle datasets files` command is therefore an operator evidence requirement.
- Added an enabled local-read-only Kaggle source policy and the `ingest-kaggle-ultimate` CLI. The adapter accepts only `data/incoming/ultimate-ufc-dataset/ufc-master.csv`, copies exact bytes into immutable raw storage before parsing, and records source identifier, declared licence, attribution, retrieval timestamp, original filename, SHA-256, schema version, and ingestion-run ID.
- Added source-specific validation for required columns, ISO dates, positive scheduled rounds, allowed result values, and duplicate unordered bouts. Published source-shaped Parquet retains neutral fighter-pair context only. Results/finishes, odds, R/B statistics, records, ranks, streaks, differences, supplied aggregates, unreviewed fields, and unverified R/B source ordering are quarantined from features.
- Added fixture tests for successful ingestion, raw checksum/immutability, duplicate and schema quarantine, idempotent reruns, leakage classification, policy provenance, and the CLI. Added durable-policy/raw-manifest provenance fields and forward migrations `0003_kaggle_local_provenance` and `0004_dataset_license_policy`.
- Resumed the exact `polars==1.30.0` Windows wheel from its partial download, verified SHA-256 `c26b633a9bd530c5fc09d317fca3bb3e16c772bd7df7549a9d8ec1934773cc5d` against `uv.lock`, installed it locally, and completed a frozen offline workspace sync without changing the pin or lockfile.
- Fixed the genuine Windows Parquet-publication defect found by the fixture suite: `fsync` now receives a read/write staging descriptor after Polars closes its writer. Immutable write-once publication remains unchanged.
- Updated the stale foundation CLI safety assertion to match the current contract: network ingestion stays disabled while audited local-file commands remain explicit.
- Began M3 identity work with candidate-only fighter-alias normalization. It preserves exact source aliases and raw SHA-256 provenance, folds Unicode/punctuation only into a comparison key, groups candidates without auto-linking them, and rejects untraceable/incomplete source rows.
- Added reviewed-link application as the next M3 vertical slice. Only an explicit, append-only `propose_link` review decision whose six retained source/raw evidence fields match exactly may create source aliases for an existing unmerged canonical fighter. Each decision has one append-only terminal application record; invalid, conflicting, non-link, or unavailable-target attempts quarantine instead. Replays are idempotent, and PostgreSQL rejects mutation of application outcomes.
- Added bitemporal reviewed-alias correction as the next M3 vertical slice. A correction is a new `propose_link` decision that explicitly supersedes the original review. It must match the prior decision's exact source/raw evidence, close only its current aliases, create replacements for a different unmerged fighter, and persist immutable old-to-new supersession links. Invalid attempts quarantine; no historical decision or alias is rewritten.
- Added reviewed canonical merge/split safeguards. An original `propose_merge` decision must exactly identify one current reviewed alias on each selected active fighter; the applied merge preserves aliases in place, marks only the current identity edge, and appends immutable evidence. A `propose_split` must supersede that exact active merge decision and preserve matching reviewed aliases before it can restore the absorbed fighter. PostgreSQL rejects direct merge/retarget/restoration and alias reassignment/deletion; invalid operations quarantine and all valid operations replay idempotently.
- Added typed canonical mapping and publication modules. `canonicalize_kaggle_ultimate_records` consumes only accepted raw-linked adapter records plus exact reviewed aliases and a versioned, reviewer-attributed source/schema taxonomy. It has no default label interpretation: missing outcome/method/division decisions, unresolved aliases, malformed fields, or canonical duplicate collisions quarantine the entire record. Fully mapped rows retain raw labels/references and separate outcome fields from future features; only a zero-quarantine result can publish idempotent canonical Parquet plus an immutable manifest.
- Added `0009_canonical_bout_catalog` and `ufc_api.fights`. `CanonicalCatalogRepository` atomically publishes only a zero-quarantine mapped result to raw-linked source references, taxonomy divisions, fights, deterministic participant slots, applied identity evidence, and result facts; replay is idempotent. PostgreSQL requires two participants and one current result before publication, checks result-winner ownership, and rejects identity evidence that does not match an applied canonical fighter decision. The approved source has no event identifier, so those rows remain explicitly `event_context_status = not_observed` rather than being grouped into fabricated events.

No source dataset bytes, canonical fact, feature, training data, model, or prediction was created. The only input fixture is synthetic and is not a redistributed source file.

## Files changed in this session

- `apps/api/pyproject.toml`
- `apps/api/Dockerfile`
- `pyproject.toml`
- `uv.lock`
- `apps/api/src/ufc_api/data/models.py`
- `apps/api/src/ufc_api/data/repository.py`
- `apps/api/migrations/versions/0002_raw_object_source_scope.py`
- `compose.yaml`
- `services/ml/src/ufc_predictor/ingestion/runner.py`
- `tests/api/test_data_governance_models.py`
- `tests/integration/test_compose_health.py`
- `tests/integration/test_ingestion_persistence.py`
- `docs/architecture/DATABASE_SCHEMA.md`
- `docs/architecture/DATA_SOURCE_AUDIT.md`
- `README.md`
- `docs/CURRENT_PROGRESS.md`
- `docs/SESSION_REPORT.md`
- `services/ml/src/ufc_predictor/ingestion/policies.py`
- `services/ml/src/ufc_predictor/ingestion/kaggle_ultimate.py`
- `services/ml/src/ufc_predictor/ingestion/{registry.py,raw_store.py}`
- `services/ml/src/ufc_predictor/cli.py`
- `services/ml/src/ufc_predictor/identity/normalize.py`
- `services/ml/src/ufc_predictor/identity/{candidates.py,scorer.py,review.py,resolver.py}`
- `services/ml/src/ufc_predictor/canonical/{taxonomy.py,models.py,mappers.py,publisher.py,validation.py}`
- `apps/api/src/ufc_api/fighters/{models.py,repository.py}`
- `apps/api/migrations/versions/0003_kaggle_local_provenance.py`
- `apps/api/migrations/versions/0004_dataset_license_policy.py`
- `apps/api/migrations/versions/0005_catalog_identity.py`
- `apps/api/migrations/versions/0006_identity_resolution_application.py`
- `apps/api/migrations/versions/0007_alias_supersession.py`
- `apps/api/migrations/versions/0008_identity_merge_split.py`
- `apps/api/migrations/versions/0009_canonical_bout_catalog.py`
- `apps/api/migrations/versions/0010_canonical_quality_issues.py`
- `tests/data/test_kaggle_ultimate_ingestion.py`
- `tests/data/test_identity_normalize.py`
- `tests/data/test_identity_candidate_review.py`
- `tests/data/test_canonical_mapping.py`
- `tests/api/test_fighter_identity_models.py`
- `docs/architecture/IMPLEMENTATION_ROADMAP.md`
- `data/incoming/.gitkeep`
- `data/incoming/ultimate-ufc-dataset/.gitkeep`

Pre-existing working-tree implementation and the modified `README.md` / `docs/architecture/DATA_SOURCE_AUDIT.md` were inspected and preserved.

## Commands and results

The first group records the verified source-neutral foundation before this Kaggle/Polars change. The later Kaggle rows are the current-tree evidence and supersede any earlier full-suite/type/migration claim that now depends on Polars or the new migrations.

- `git status --short`, `git log --oneline -15`, `git diff`, and unfinished-work search: completed before implementation.
- `uv run ruff format --check apps/api/src services/ml/src tests scripts`: pass.
- `uv run ruff check apps/api/src services/ml/src tests scripts`: pass.
- `uv run mypy`: pass (61 source files).
- Targeted persistence checks: pass (10 tests, then 7 migration/persistence checks after the forward migration).
- `uv run pytest`: pass (29 tests), including Docker Compose health, live migrations, durable PostgreSQL persistence, and API/web profile startup.
- `corepack pnpm lint`, `typecheck`, `test`, `build`, and `check:generated`: pass; web tests: 2 passed.
- `docker compose config --quiet`: pass.
- `uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head --sql`: pass; emits the forward `0002_raw_object_source_scope` SQL.
- `uv run python scripts/check_architecture.py` and `uv run python scripts/check_repository_policy.py`: pass after documentation updates.
- `uv run pytest tests/architecture/test_repository_contract.py`: pass (4 tests) after the UFCStats decision-record update.
- `corepack pnpm audit --prod --audit-level high`: pass; no known vulnerabilities.
- `docker compose --profile app build api`: pass; rebuilt the image with the Dockerfile `/tmp` cache setting after dependency sync completed.
- `docker compose --profile app up -d --wait api web` with the rebuilt image and direct probes: pass (`health=ok`, web `200`); the profile was then torn down. The integration suite repeats the startup check with bounded health polling.
- `just --version` / `just test`: blocked because `just` is not installed or on `PATH`.
- `uv lock` after moving `polars==1.30.0` into the ML base dependencies: pass.
- `uv run ruff format ...`, `uv run ruff check apps/api/src services/ml/src tests scripts`, and `uv run python -m py_compile ...kaggle_ultimate.py ...policies.py ...cli.py`: pass for the new implementation.
- `uv run ruff format --check apps/api/src services/ml/src tests scripts`: pass (68 files). `uv run pytest tests/data/test_ingestion_contract.py tests/data/test_raw_store.py`: pass (10 tests). `uv run pytest tests/api/test_data_governance_models.py tests/architecture/test_repository_contract.py`: pass (7 tests).
- `uv run pytest tests/data/test_kaggle_ultimate_ingestion.py`: blocked at collection because Polars is not installed; no test was bypassed or weakened.
- Full `pytest` is blocked at the same collection import (29 other tests collected). Mypy now reports only the missing Polars implementation in the new adapter and test after a duplicate-key typing issue found during this session was corrected.
- `.venv\\Scripts\\alembic.exe -c apps/api/alembic.ini upgrade head --sql`: pass through `0004_dataset_license_policy`. The repository `uv run --project apps/api` spelling is currently blocked before Alembic by the same dependency download; the direct virtualenv command verifies the actual SQL migration chain without changing dependency state.
- `.venv\\Scripts\\python.exe scripts/check_architecture.py`, `scripts/check_repository_policy.py`, `docker compose config --quiet`, and `git diff --check`: pass.
- `uv sync --all-packages --group dev --frozen`: blocked while downloading the pinned Polars wheel. A direct download also timed out after 180 seconds with 4,259,840 of 36,363,630 bytes received. The partial file is outside the repository in the system temporary directory.

### M2 closure continuation

- The normal `uv sync --all-packages --group dev --frozen` retry did not make byte progress. The official locked wheel was resumed with `curl.exe --fail --location --retry 10 --retry-all-errors --retry-delay 5 --connect-timeout 60 --continue-at -`; it completed at 36,363,630 bytes and the SHA-256 exactly matched the lock.
- `uv pip install --python .\\.venv\\Scripts\\python.exe <verified-local-wheel>` and `uv sync --all-packages --group dev --frozen --offline`: pass; `polars==1.30.0` imports on Python 3.12.11.
- `uv run pytest tests/data/test_kaggle_ultimate_ingestion.py -q`: pass, 8 tests after the Windows `fsync` correction.
- `uv run pytest -q`: pass, 37 tests, including live PostgreSQL/Redis, Alembic, durable-ingestion, and Compose application-profile coverage.
- `uv run ruff format --check apps/api/src services/ml/src tests scripts`, `uv run ruff check apps/api/src services/ml/src tests scripts`, and `uv run mypy`: pass before the M3 slice (68 files; 64 source files for mypy).
- `uv run python scripts/check_architecture.py`, `uv run python scripts/check_repository_policy.py`, `git diff --check`, `docker compose config --quiet`, and `uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head --sql`: pass; migration SQL renders through `0004_dataset_license_policy`.
- Fixture-backed CLI ingestion into a temporary directory published two rows and a later identical rerun replayed the same run ID. Its raw SHA-256 was `e8be33f0c53180428a4fb0d6826f412e33e12844f013e40f50ecbf3b16717324`, equal to the untouched fixture bytes and manifest. Polars inspection confirmed only the restricted 15-column context/provenance schema; outcome, finish, odds, ordering, current-statistic, and record fields are quarantined and absent from output.
- Final M2/M3 repository run: `uv run ruff format --check apps/api/src services/ml/src tests scripts`, `uv run ruff check apps/api/src services/ml/src tests scripts`, `uv run mypy`, `uv run pytest -q`, architecture/repository-policy checks, `docker compose config --quiet`, and Alembic offline SQL all pass. The final results are 70 formatted files, mypy clean across 66 source files, and 42 passed tests; migration SQL renders through `0004_dataset_license_policy`.
- M3 candidate/review continuation: `identity/candidates.py` creates only cross-record, equal-normalized-alias pairs; `identity/scorer.py` records versioned evidence and always returns `review_required` with no auto-link threshold; `identity/review.py` produces stable review keys and validates explicit reviewer/timestamp/rationale audit fields. The final repository-wide verification is 74 formatted files, mypy clean across 70 source files, and 47 passed tests; policy, Compose, and Alembic SQL checks remain green.
- M3 catalog-identity persistence continuation: `0005_catalog_identity` adds canonical fighters, reviewed source aliases, and append-only identity-resolution decisions. Fighter aliases require canonical fighter, audited source, and raw object lineage; self-merges are rejected; provider external IDs are unique only when present; decisions are blocked from update/delete by a PostgreSQL trigger. `FighterIdentityRepository` persists explicit review evidence without applying it to a canonical fighter. A live Compose/PostgreSQL test proves the record retains both raw SHA-256 values and mutation fails. Final verification: 77 formatted files, mypy clean across 73 source files, and 51 tests passed; policy, Compose, and Alembic SQL render through `0005_catalog_identity`.
- M3 reviewed-resolution application continuation: `0006_identity_resolution_app` adds one immutable terminal outcome per durable decision. `FighterIdentityRepository.apply_proposed_link` requires exact source identifier, raw SHA-256, record key, field, original alias, and normalized alias evidence; it returns the stored result on replay, creates aliases only for explicit validated links to an unmerged fighter, and otherwise quarantines. Final repository verification: 77 formatted files, mypy clean across 73 source files, and 53 tests passed; architecture/policy, Compose, and Alembic SQL checks pass through `0006_identity_resolution_app`.
- M3 bitemporal alias-correction continuation: `0007_alias_supersession` records append-only old-to-new alias links. `FighterIdentityRepository.supersede_reviewed_aliases` requires an explicit superseding review decision and exact prior evidence, closes only active aliases created by that earlier decision, creates reviewed replacements for a different unmerged fighter, and quarantines invalid correction requests. Focused verification: Ruff clean, mypy clean across 73 source files, offline SQL renders through `0007_alias_supersession`, and 12 API/Compose-backed tests prove the correction history, current projection, idempotent replay, and immutable ledger.
- Final M3 alias-correction repository verification: `uv run ruff format --check apps/api/src services/ml/src tests scripts`, `uv run ruff check apps/api/src services/ml/src tests scripts`, `uv run mypy`, `uv run pytest -q`, architecture/repository-policy checks, `git diff --check`, `docker compose config --quiet`, and Alembic offline SQL all pass. Final results: 77 formatted files, mypy clean across 73 source files, 54 tests passed, and migrations render through `0007_alias_supersession`.
- M3 merge/split continuation: `uv run pytest -q tests/data/test_identity_candidate_review.py tests/api/test_fighter_identity_models.py tests/integration/test_ingestion_persistence.py` passes 17 tests through live PostgreSQL and migration `0008_identity_merge_split`. The fixture proves merge/split replay, exact reviewed-alias evidence, immutable ledgers, no alias movement, durable quarantine, and database rejection of direct merge-state, alias mutation, and direct re-merge after a split.
- Live migration replay: Compose PostgreSQL was upgraded from `0007_alias_supersession` to the revised `0008_identity_merge_split` after a controlled local downgrade, then `tests/integration/test_ingestion_persistence.py` and `tests/integration/test_compose_health.py` passed together (8 tests).
- Final M3 merge/split repository verification: 78 files are formatted, Ruff is clean, mypy is clean across 74 source files, and `uv run pytest -q` passes 57 tests. The first whole-suite run found only a stale Compose expectation for migration `0007`; the integration assertion now expects the actual `0008_identity_merge_split` head and both ledgers, and the rerun passes. Architecture/policy checks, `git diff --check`, Compose validation, and Alembic offline SQL all pass through `0008_identity_merge_split`.
- M3 canonical mapping/taxonomy repository verification: 83 files are formatted, Ruff is clean, mypy is clean across 79 source files, and `uv run pytest -q` passes 61 tests. Architecture/policy checks, `git diff --check`, Compose validation, and Alembic offline SQL all pass through `0008_identity_merge_split`. The four fixture-backed canonical tests prove raw provenance, stable outcome-independent participants, explicit taxonomy decisions, no partial publication, immutable Parquet replay, identity/taxonomy quarantine, canonical duplicate detection, and mapping-conflict rejection.
- M3 relational canonical catalog repository verification: 86 files are formatted, Ruff is clean, mypy is clean across 82 source files, and `uv run pytest -q` passes 63 tests. Architecture/policy checks, `git diff --check`, Compose validation, and Alembic offline SQL all pass through `0009_canonical_bout_catalog`. Live PostgreSQL fixture coverage proves atomic raw-linked source-reference/fight/participant/identity-evidence/result publication, replay idempotency, explicit event absence, and rejection of mismatched identity evidence or an incomplete published participant set.
- M3 durable conflict/quarantine reporting continuation: `canonical/validation.py` makes every mapping quarantine auditable and blocks it before publication. Migration `0010_canonical_quality_issues` adds a source-scoped partial unique issue key. `CanonicalCatalogRepository` records mapper quarantines and relational or conflicting-replay failures as blocking `data_quality_issues` with source-record/raw-checksum evidence; repeat failures update `occurrence_count` while the catalog transaction rolls back. Full verification passes: 87 formatted files, Ruff clean, mypy clean across 83 source files, and 66 tests passed. Architecture/policy, Compose, `git diff --check`, and Alembic offline SQL pass through `0010_canonical_quality_issues`.
- Live forward migration validation: after restoring the Compose dependencies that the integration suite had removed, `.venv\\Scripts\\alembic.exe -c apps/api/alembic.ini upgrade head` and `current` pass and report `0010_canonical_quality_issues (head)`. The earlier `uv run` attempt timed out only because it began after that temporary database was removed.

## Remaining blockers

1. A real ingestion requires a user-downloaded version-181 `ufc-master.csv` in `data/incoming/ultimate-ufc-dataset/`; Kaggle CLI and credentials are unavailable here, and no alternative download path was used. M3 real-source acceptance additionally requires reviewer-attributed decisions for observed fighter aliases and outcome/method/division labels. Fixture-backed M2 acceptance is complete.
2. `just` must be installed to verify the canonical local task-runner entrypoint. The API image recipe and rebuilt Compose app profile passed; this is an M1 tooling gap, not an M2 blocker.
3. All implementation remains untracked against the only committed architecture revision; it must be intentionally reviewed and committed.

## Next exact task

When the approved local Kaggle file is supplied, ingest it with the local-only command, generate review queues from observed aliases and labels, obtain reviewer-attributed identity/taxonomy decisions, and run the M3 acceptance gate. Keep event/source-event references empty until an audited source supplies them; do not infer events, add real-source taxonomy defaults, start temporal features, or train models.

## M3 dual-source implementation update

Implemented the deterministic M3 continuation: explicit local-only
`ingest-ufc-datalab`, immutable raw provenance and semicolon parsing,
candidate-only identity/taxonomy review queues, traceable non-concatenating
reconciliation, and strict prior-history feature construction. Tests cover
immutable input/replay/provenance, malformed rows, known name variants and
Bruno Silva separation, queues, reconciliation, same/future leakage exclusion,
and corner-swap difference negation.

The real Ultimate input generated 47 candidate identity review items (12
known-variant/Bruno cases) and 40 taxonomy review items affecting 19,701
observations; none were auto-resolved.

The Ultimate source was copied unchanged to the required incoming location;
its SHA-256 matched
`deb1cd9a7014c08a538875e2b585e6f51fbf8f7a6d3f981eb684db1bd7242dc5`.
The local-only run `5aa550c81d624934b62ea93dffc84739` published 7,177 of
7,177 rows from 118 columns with zero quarantines.
This is row-level: 111 unsafe source fields are quarantined from every row's
model-ready projection and are rejected by the hard pre-fight schema gate.
UFC-DataLab acquisition remains blocked: the shallow clone left an empty
temporary pack/invalid HEAD and retry found a stale shallow lock. The host
refused the explicitly scoped cache-directory deletion, so the exact clone
retry failed on its non-empty destination. No source artifact, commit SHA,
dimensions, or reconciliation counts were fabricated.

Reviewer-ready Markdown proposals were produced under
`data/quarantine/reviews/`: 47 identity items and 40 taxonomy items. Bruno
Silva is explicitly represented as a separate Flyweight/Middleweight review,
and no proposal was applied.

## UFC-DataLab M3 completion continuation (2026-07-18)

Verified the clean cached Git checkout at
`3268146c05211de9deab8b9b4c0bb4a954815f0b`. Copied only
`data/stats/stats_raw.csv` to the commit-pinned incoming zone; it is MIT
repository data, 4,258,380 bytes, SHA-256
`26a49b01247a1f51c0553fbcfd3d1dc6529b4fae3b145799d7433270bafeae10`,
8,737 rows × 60 columns, semicolon-delimited UTF-8-SIG. Provenance records
the repository URL, pinned commit, upstream UFC Official Fight Statistics
(UFCStats) attribution from the repository README, and no direct UFCStats use.

`ingest-ufc-datalab` run `22ea088e-6af0-57bd-ac84-faacf4c70ac5` published
the restricted post-fight-fact Parquet. A retained legacy duplicate candidate
is review-only. Candidate reconciliation yielded exact 2,176, normalized 3,
corner-swapped 0, probable 0, ambiguous 0, conflict 4,664, Ultimate-only 334,
and DataLab-only 1,894. The strict-date candidate prior-history proposal is
8,737 × 51 and is explicitly not training/model-ready. UFC-DataLab introduced
37 identity and 24 taxonomy review items; none was applied.

M3 is conditionally complete: source acquisition, local ingestion,
reconciliation, review artifacts, and leakage-safe proposal generation are
complete. Canonical/model publication remains gated on human review of aliases,
taxonomy, and 4,664 source conflicts.
