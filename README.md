# UFC Predictor

UFC Predictor is a reproducible, audit-first UFC analytics platform for producing pre-fight probability estimates. It is intentionally **not** a betting product: it does not make wagering recommendations, promise outcomes, or hide missing data behind overconfident predictions.

The project is a Python/TypeScript monorepo with a governed local-data pipeline, canonical fight-history materialization, a pure winner model, FastAPI, and a Next.js interface. The supported local prediction requires the accepted data generation and champion bundle.

**Current scope:** Pure winner probabilities work for known canonical fighters
with accepted, strictly pre-fight history. Method, round, duration, and market predictions; durable
prediction snapshots; and a verified future event feed remain incomplete. See the
[2026-10-08 implementation audit](docs/IMPLEMENTATION_AUDIT_2026-10-08.md).

## What is implemented

| Area | Included today | Boundary |
| --- | --- | --- |
| Repository foundation | Locked Python and Node workspaces, Docker Compose, migrations, CI-oriented checks, API and web health shells | Not yet a complete user-facing product |
| Data ingestion | Local-file-only adapters for approved sources, immutable raw evidence, checksums, schema validation, quarantine, and durable run metadata | No web scraping or automatic source downloads |
| Canonical data (M3) | Reviewed identity authority, cross-source reconciliation, atomic generation publication, provenance coverage, pre-fight history/performance/pairwise features, and model-ready binary rows | Real-source taxonomy and identity decisions are explicit review artifacts, never name-only automatic merges |
| Model development (M4) | Deterministic chronological baselines, symmetry-aware XGBoost candidates, opponent-strength and opponent-adjusted features, bounded Optuna evaluation, calibration/blending and confidence-coverage studies, plus an immutable champion bundle | Training outputs are local, ignored artifacts; only the accepted champion is eligible for inference |
| API and web | FastAPI catalog and pure winner endpoints, Parquet fallback, Next.js exploration pages, shared packages | Secondary outcomes and durable product workflows remain open; unavailable results are surfaced rather than synthesized |

The current M3 acceptance record is documented in [docs/M3_ACCEPTANCE_REPORT.md](docs/M3_ACCEPTANCE_REPORT.md). Its accepted generation contains 9,068 reconciled historical bouts and an 8,912-row model-ready binary projection; the underlying artifacts and M4/M5 model artifacts are deliberately not committed.

## Design principles

- Preserve immutable raw inputs, checksums, retrieval metadata, and source lineage.
- Require reviewer-attributed identity and taxonomy decisions before canonical publication.
- Build features from information available strictly before the bout being modeled.
- Maintain fighter-orientation symmetry so swapping competitors produces complementary probabilities.
- Use chronological splits and deterministic, versioned artifacts for model evaluation.
- Surface uncertainty, data quality, freshness, and responsible-use limitations.

See [the architecture overview](docs/architecture/SYSTEM_OVERVIEW.md), [implementation roadmap](docs/architecture/IMPLEMENTATION_ROADMAP.md), and [data-source audit](docs/architecture/DATA_SOURCE_AUDIT.md) for the full contract.

## Repository layout

```text
apps/api/              FastAPI application, SQLAlchemy models, Alembic migrations
apps/web/              Next.js application foundation
services/ml/           Ingestion, reconciliation, materialization, and training package
packages/shared-types/ OpenAPI snapshot and generated TypeScript contract target
packages/ui/           Shared design tokens and UI primitives
data/                  Local-only raw, quarantine, interim, and processed data planes
models/                Local-only model-artifact cache
docs/                  Architecture, acceptance, deployment, and operational documentation
tests/                 API, data, ML, integration, and architecture tests
scripts/               Bootstrap, validation, and generation commands
```

## Prerequisites

- Windows PowerShell (the supplied bootstrap command is PowerShell-based)
- Python 3.12
- Node.js 22–24 with Corepack
- Docker Desktop for PostgreSQL/Redis and integration checks
- [`uv`](https://docs.astral.sh/uv/) and `pnpm` (the bootstrap script provisions `uv`)
- [`just`](https://github.com/casey/just) for the convenience task runner

## Quick start

```powershell
./scripts/bootstrap.ps1
corepack enable
uv sync --all-packages --group dev
corepack pnpm install --frozen-lockfile
just infra-up
just migrate
just dev-api
```

Start the web application from a second terminal:

```powershell
just dev-web
```

The API health endpoint is `http://127.0.0.1:8000/health`. To start the prediction API, the accepted local M3/M4 artifacts and immutable champion bundle must already exist at `CHAMPION_BUNDLE_PATH` (see `.env.example`); startup validates their checksums and contracts before accepting requests.

## Champion prediction API

`POST /api/v1/predictions/fight` returns a symmetrized pre-fight probability for two canonical fighter IDs and a target date. It accepts only prediction-safe, strictly pre-fight feature materializations: unknown fighters or unavailable source history receive a `422` response rather than a fabricated estimate.

```json
{
  "fighter_a_id": "canonical-fighter-a-id",
  "fighter_b_id": "canonical-fighter-b-id",
  "target_fight_date": "2026-08-01"
}
```

Responses include complementary win probabilities, the predicted winner when the probability is not exactly even, confidence coverage, model and feature-schema versions, bundle provenance, history counts, and any insufficient-history indicators. The runtime preserves native XGBoost missing-value behavior; missing values are never replaced with zero.

## Quality checks

Run the primary suite with:

```powershell
just test
```

Useful focused checks are:

```powershell
uv run pytest -q
uv run ruff format --check apps/api/src services/ml/src tests scripts
uv run ruff check apps/api/src services/ml/src tests scripts
uv run mypy
corepack pnpm lint
corepack pnpm typecheck
corepack pnpm test
corepack pnpm build
docker compose config --quiet
```

## Local data and training workflow

Raw inputs and generated artifacts are excluded from version control. Acquire approved source files manually and place them in their documented `data/incoming/` locations; never add source data, generated Parquet, model binaries, or reviewer outputs to Git.

The ML CLI exposes explicit local workflows:

```powershell
# Inspect available commands and source policy.
uv run ufc-predictor --help

# Materialize the reviewed M3 generation from local approved inputs.
uv run ufc-predictor materialize-m3-v6

# Train M4 phases in order from the accepted M3 generation.
uv run ufc-predictor train-m4-baselines
uv run ufc-predictor train-m4-symmetry
uv run ufc-predictor train-m4-xgboost
uv run ufc-predictor train-m4-opponent-strength
uv run ufc-predictor train-m4-opponent-ablation
uv run ufc-predictor train-m4-opponent-adjusted-performance
uv run ufc-predictor train-m4-optuna
uv run ufc-predictor train-m4-calibration-blending
uv run ufc-predictor evaluate-m4-confidence-coverage
uv run ufc-predictor finalize-m4-champion
```

Each stage writes a generation-scoped manifest, feature contract, metrics, predictions, and lineage information beneath `data/processed/`. M4 phase 1 establishes chronological logistic-regression and histogram-gradient-boosting baselines; phase 2 enforces orientation symmetry; later phases evaluate opponent-aware features, bounded tuning, calibration/blending, and confidence coverage. `finalize-m4-champion` creates the checksum-verified immutable bundle consumed by the M5 runtime. These remain local research/evaluation artifacts, not a betting product.

## Data governance

- Approved adapters read user-provided local files only.
- UFCStats automated collection is explicitly out of scope.
- Raw bytes are checksum-addressed and immutable; unsafe or mismatched records are quarantined.
- Identity matching is candidate/review-driven and retains raw source evidence.
- Canonical publication is atomic and refuses partial or conflicting results.
- All real data, credentials, reviewer decisions, derived datasets, and trained model artifacts remain untracked.

Consult [DATASETS.md](DATASETS.md), [DATA_DICTIONARY.md](DATA_DICTIONARY.md), [the source audit](docs/architecture/DATA_SOURCE_AUDIT.md), and [the M3 acceptance report](docs/M3_ACCEPTANCE_REPORT.md) before working with data.

## Documentation

- [Development guide](DEVELOPMENT.md)
- [Contribution guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Deployment status](docs/DEPLOYMENT.md)
- [System overview](docs/architecture/SYSTEM_OVERVIEW.md)
- [Model card status](MODEL_CARD.md)

## Responsible use

Any eventual prediction is an uncertain analytical estimate conditioned on retained historical information. It is not a fact, guarantee, financial advice, or betting advice. A future product must expose the dataset, feature, model, cutoff, and source-freshness versions used to produce every result.
