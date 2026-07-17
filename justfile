set shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

default:
  @just --list

bootstrap:
  powershell.exe -ExecutionPolicy Bypass -File scripts/bootstrap.ps1

infra-up:
  docker compose up -d postgres redis

infra-down:
  docker compose down

migrate:
  uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head

seed-test-data:
  uv run python scripts/tasks.py seed-test-data

dev-api:
  uv run --project apps/api uvicorn ufc_api.main:create_app --factory --reload --host 127.0.0.1 --port 8000

dev-worker:
  uv run --project apps/api celery -A ufc_api.worker:celery_app worker --loglevel=INFO

dev-web:
  pnpm --filter @ufc-predictor/web dev

dev:
  @Write-Error "Run 'just infra-up' and start 'just dev-api', 'just dev-web', and optionally 'just dev-worker' in separate terminals."
  exit 1

lint:
  uv run ruff check apps/api/src services/ml/src tests scripts
  pnpm lint

format-check:
  uv run ruff format --check apps/api/src services/ml/src tests scripts

typecheck:
  uv run mypy
  pnpm typecheck

test-unit:
  uv run pytest -m "not integration"
  pnpm test

test-integration:
  uv run pytest -m integration

test-contract:
  just openapi
  pnpm check:generated

test-e2e:
  @Write-Error "E2E tests are introduced with the web and catalog milestones; no suite exists in M1."
  exit 1

test-accessibility:
  @Write-Error "Accessibility tests are introduced with reusable UI components in M9; M1 includes a keyboard-safe shell only."
  exit 1

test-load-smoke:
  @Write-Error "Load tests require catalog/prediction endpoints and begin after M7."
  exit 1

test-security:
  uv run python scripts/check_repository_policy.py
  corepack pnpm audit --prod --audit-level high

test:
  just format-check
  just lint
  just typecheck
  just test-unit
  just test-integration
  just test-contract
  just test-security
  just docs-check

openapi:
  uv run python scripts/generate_openapi.py

generate-types:
  pnpm generate:types

check-generated:
  pnpm check:generated

ingest SOURCE MODE RANGE:
  uv run python scripts/tasks.py ingest {{SOURCE}} {{MODE}} {{RANGE}}

build-dataset CONFIG:
  uv run python scripts/tasks.py unavailable build-dataset {{CONFIG}}

build-features CONFIG:
  uv run python scripts/tasks.py unavailable build-features {{CONFIG}}

train MODEL_CONFIG:
  uv run python scripts/tasks.py unavailable train {{MODEL_CONFIG}}

evaluate RUN_ID:
  uv run python scripts/tasks.py unavailable evaluate {{RUN_ID}}

model-smoke MODEL_VERSION:
  uv run python scripts/tasks.py unavailable model-smoke {{MODEL_VERSION}}

snapshot-event EVENT_ID AS_OF MODE:
  uv run python scripts/tasks.py unavailable snapshot-event {{EVENT_ID}} {{AS_OF}} {{MODE}}

docs-check:
  uv run python scripts/check_architecture.py

build-images:
  docker compose --profile app build api web

staging-smoke:
  @Write-Error "Staging is a Milestone 14 deployment gate and cannot run from the M1 foundation."
  exit 1

restore-drill ENV:
  uv run python scripts/tasks.py restore-drill {{ENV}}
