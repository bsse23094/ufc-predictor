# UFC Predictor

UFC Predictor is a planned, production-quality sports analytics platform for reproducible pre-fight UFC estimates. It is an analytics product, not a betting product: it will not make wagering recommendations, claim certainty, or conceal missing data behind confident-looking outputs.

## Current status

The repository is implementing the accepted architecture in strict milestone order. Milestone 1's direct Python, web, Compose, migration, health, and API-image checks pass; the canonical local `just` entrypoint still requires its documented prerequisite. Milestone 2 has source-neutral governance plus one narrowly audited local-file adapter for Kaggle's Ultimate UFC Dataset: it reads only a user-downloaded CSV, preserves immutable raw evidence, and publishes a restricted source-shaped Parquet projection. It does not scrape UFCStats, download from Kaggle, construct features, or train models. **Milestone 2 is not accepted or complete** while its locked Parquet dependency and full verification remain blocked. See [the current progress audit](docs/CURRENT_PROGRESS.md) for verified evidence and blockers.

There is still no source data in this workspace, approved canonical dataset, trained model, catalog API, prediction endpoint, or production frontend experience. The local adapter requires a manually acquired `data/incoming/ultimate-ufc-dataset/ufc-master.csv`; its acquisition and provenance policy are documented in [the data-source audit](docs/architecture/DATA_SOURCE_AUDIT.md).

That boundary is intentional. Source access, licensing, timestamp semantics, and retention must be audited before any source can enter the system. See [the data-source audit](docs/architecture/DATA_SOURCE_AUDIT.md).

## Architecture principles

- Immutable raw inputs with checksums and retrieval metadata
- Auditable fighter identity resolution—never name-only automatic merging
- Strict point-in-time features and hard leakage checks
- Outcome-independent fighter orientation with dual inference
- Separate pure and market-informed prediction modes
- Chronological splitting, isolated calibration, and versioned artifacts
- Clear uncertainty, data-quality, freshness, and responsible-use communication

The full implementation contract is in [docs/architecture](docs/architecture), especially [the Terra handoff](docs/architecture/TERRA_HANDOFF.md), [system overview](docs/architecture/SYSTEM_OVERVIEW.md), and [implementation roadmap](docs/architecture/IMPLEMENTATION_ROADMAP.md).

## Quick start: foundation

Prerequisites: Docker Desktop, Node.js 22–24 with Corepack, PowerShell, and [`just`](https://github.com/casey/just) (for example, `winget install Casey.Just`). The bootstrap script installs the pinned `uv` tool and provisions Python 3.12.

```powershell
./scripts/bootstrap.ps1
just infra-up
just migrate
just dev-api
```

In a second terminal:

```powershell
just dev-web
```

The API foundation is available at `http://127.0.0.1:8000/health`. `/readiness` accurately reports that database checks and model serving belong to later milestones. The web page is only a keyboard-accessible foundation shell.

Run the implemented quality suite with:

```powershell
just test
```

If Docker Desktop is unavailable, the container-health integration test is skipped locally. CI runs it with `RUN_CONTAINER_TESTS=1`.

## Repository layout

```text
apps/api              FastAPI modular-monolith foundation
apps/web              Next.js accessible application foundation
services/ml           Data/ML package and guarded CLI
packages/shared-types OpenAPI snapshot and generated contract target
packages/ui           Generic visual tokens and future accessible primitives
data                  Ignored raw, quarantine, interim, and processed data zones
models                Ignored model-artifact cache zone
infrastructure        Local/deployment/observability configuration target
scripts               Safe bootstrap, checks, and generation commands
tests                 Architecture, API, ML, and integration checks
docs/architecture     Accepted implementation contract
```

## Documentation

- [Development guide](DEVELOPMENT.md)
- [Contribution policy](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Dataset policy](DATASETS.md)
- [Data-dictionary status](DATA_DICTIONARY.md)
- [Model-card status](MODEL_CARD.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Deployment status](docs/DEPLOYMENT.md)

## Responsible use

When implemented, predictions will be uncertain analytical estimates conditioned on retained historical information. They will display the model, dataset, feature, cutoff, and source-freshness versions that produced them. They are not facts, guarantees, financial advice, or betting advice.
