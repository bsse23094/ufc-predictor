# Architecture decision record index

## Policy

ADRs are immutable decision history. A changed decision receives a new ADR that supersedes the old one; do not rewrite an accepted decision to erase context. Each ADR states context, decision, rationale, positive/negative consequences, alternatives, and revisit triggers.

Implementation must follow accepted ADRs and TERRA_HANDOFF. A divergence requires an accepted superseding ADR and updates to affected contracts, migrations, tests, risks, and roadmap.

## Accepted decisions

| ADR | Decision | Status |
|---|---|---|
| [ADR-0001](adr/0001-monorepo-structure.md) | Use a polyglot modular monorepo | Accepted |
| [ADR-0002](adr/0002-postgresql-primary-store.md) | Use PostgreSQL as the production relational/serving store | Accepted |
| [ADR-0003](adr/0003-duckdb-parquet-analytical-plane.md) | Use DuckDB and Parquet for local/offline analytics | Accepted |
| [ADR-0004](adr/0004-hybrid-model-serving.md) | Use hybrid in-process inference and asynchronous workers | Accepted |
| [ADR-0005](adr/0005-celery-background-jobs.md) | Use Celery with Redis for background work | Accepted |
| [ADR-0006](adr/0006-fighter-orientation-symmetry.md) | Use canonical orientation, dual training, and swap-averaged inference | Accepted |
| [ADR-0007](adr/0007-temporal-feature-snapshots.md) | Use immutable point-in-time feature snapshots with bitemporal lineage | Accepted |
| [ADR-0008](adr/0008-model-calibration.md) | Use dedicated chronological calibration artifacts | Accepted |
| [ADR-0009](adr/0009-pure-and-market-models.md) | Keep pure and market-informed winner models separate | Accepted |
| [ADR-0010](adr/0010-frontend-state-management.md) | Use TanStack Query, URL state, and local UI state | Accepted |
| [ADR-0011](adr/0011-progressive-deployment.md) | Deploy local-first, low-cost managed MVP, then scale by evidence | Accepted |

## Decisions intentionally pending

These require empirical/source evidence and are not silently resolved:

- exact data providers and enabled feature families;
- event/bout target timestamp fallback;
- identity matching thresholds;
- canonical source-label mappings;
- numerical model promotion/calibration gates;
- hosting vendor and IaC tool;
- whether/when to extract an inference service;
- whether/when pgvector or an approximate-neighbor engine is needed;
- whether Model E can leave shadow status.

Pending decisions are captured as milestone gates in IMPLEMENTATION_ROADMAP and risks in RISK_REGISTER. Create new ADRs when evidence is available.

