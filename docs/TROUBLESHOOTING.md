# Troubleshooting

## `uv` is not found after bootstrap

Restart PowerShell so the user scripts directory is refreshed in `PATH`, then run `uv --version`. The bootstrap script can also be rerun safely.

## Docker integration check is skipped

Start Docker Desktop and run `docker info`. The test is intentionally skipped when container infrastructure is unavailable locally; CI sets `RUN_CONTAINER_TESTS=1`.

## A Milestone command reports unavailable

This is expected before its owning architecture gate has passed. For example, ingestion cannot run while source access and terms are unaudited. Do not bypass the guard with an ad hoc script.

## Configuration fails in production mode

Production intentionally requires explicit CORS, database/Redis, OIDC, trusted model-prefix, and audit-key settings. Review `.env.example` and the [environment contract](architecture/TERRA_HANDOFF.md#12-environment-variable-contract); never substitute wildcard CORS or example secrets.
