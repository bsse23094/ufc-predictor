# Contributing

Contributions follow the accepted architecture in [docs/architecture](docs/architecture). The repository has a verified non-container foundation and a partial, source-neutral Milestone 2 ingestion slice. No source is approved or enabled; source ingestion, data publication, and predictions are not authorized or implemented. See [the current progress audit](docs/CURRENT_PROGRESS.md) before choosing work.

## Before opening a change

1. Keep work within the next unblocked milestone in `TERRA_HANDOFF.md`.
2. Do not commit source data, credentials, model binaries, generated caches, or `.env` files.
3. Use a new ADR for any change to an accepted architectural decision, including temporal semantics, orientation, storage ownership, calibration, model separation, or deployment topology.
4. Keep public copy clear that the product is analytical and not betting advice.
5. Add or update tests and documentation with the implementation.

## Local quality checks

After [bootstrap](DEVELOPMENT.md), run:

```powershell
just format-check
just lint
just typecheck
just test
```

`just test` only succeeds for implemented suites. Commands for later milestones fail explicitly instead of pretending the capability exists.

## Data and migrations

- Raw evidence is append-only and outside Git. Never edit `data/raw` content in place.
- Do not enable a source before its legal, retention, timestamp, and schema audit is complete.
- Migrations are additive and reviewed. Never edit an applied revision; use expand/backfill/contract changes.
- Identity ambiguity and temporal-leakage failures are release blockers, not cleanup work.

## Review expectations

Reviewers verify bounded-context ownership, UTC/time semantics, lineage, orientation, split/fit isolation, error safety, generated contracts, security, and rollback impact. See the full checklist in [TERRA_HANDOFF.md](docs/architecture/TERRA_HANDOFF.md).
