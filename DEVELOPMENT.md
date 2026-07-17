# Development guide

## Prerequisites

- Python 3.12 (managed by `uv` during bootstrap)
- Node.js 22-24 with Corepack
- Docker Desktop for PostgreSQL and Redis integration checks
- `just` for the canonical commands (`winget install Casey.Just` on Windows)

## Bootstrap

```powershell
./scripts/bootstrap.ps1
```

The script installs the pinned `uv` bootstrap package, asks it to provision Python 3.12, syncs the Python workspace, and installs the exact pnpm lockfile. Restart PowerShell if `uv` was newly added to `PATH`.

## Foundation and guarded-ingestion workflow

```powershell
just infra-up
just migrate
just dev-api
just dev-web
```

The API currently exposes only `/health` and `/readiness`. The web app is an accessible foundation shell and contains no source-derived records or predictions. Start the API and web commands in separate terminals; `just dev-worker` is optional and has no domain task bodies yet.

Run quality checks before a review:

```powershell
just format-check
just lint
just typecheck
just test
```

If Docker Desktop is not running, the integration container-health test is skipped locally. CI enables it explicitly. Do not use `docker compose down -v` as a routine command; `just infra-down` preserves local volumes.

## Environment

Copy `.env.example` to an ignored `.env` only if you need to override local defaults. Never use example passwords, filesystem storage, wildcard CORS, or missing OIDC configuration in production. See [the architecture handoff](docs/architecture/TERRA_HANDOFF.md#12-environment-variable-contract) for the complete variable contract.

## Milestone boundaries

Source-governance, immutable raw-storage, retry, schema-gate, and row-accounting primitives are in place, but this is not a scraper. The source audit still has unresolved legal, access, timestamp, and retention decisions. Commands such as `just ingest` and `just train` therefore reject execution until their architecture gate is passed.
