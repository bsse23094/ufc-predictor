# ADR-0001: Polyglot modular monorepo

Status: Accepted  
Date: 2026-07-17

## Context

The product requires a Python data/ML system and FastAPI backend, a TypeScript/Next.js frontend, shared API contracts, infrastructure, tests, and extensive documentation. A small initial team needs atomic cross-layer changes and one reproducible implementation sequence.

## Decision

Use one repository with:

- apps/api and apps/web as deployable applications;
- services/ml as an installable Python package/service-job codebase;
- packages/shared-types generated from OpenAPI and packages/ui for frontend components;
- infrastructure, scripts, tests, docs, ignored data zones, and ignored model cache/artifacts.

Maintain module ownership and dependency rules even though files share a repository. API domain modules form a modular monolith; ML has declared interfaces rather than importing API internals.

## Rationale

One change can update OpenAPI, generated types, frontend, migration, tests, and documentation atomically. CI and developer setup are centralized, which is more valuable than independent repositories at the current team/scale.

## Consequences

Positive:

- easier discovery, refactoring, version coordination, and end-to-end CI;
- one ADR/roadmap/release history;
- shared local environment and consistent security scanning.

Negative:

- CI can become slow without path-aware caching;
- Python and Node tooling coexist;
- access boundaries are organizational, not repository-enforced;
- careless imports can create coupling.

Controls include workspace-specific locks, dependency rules, path-aware CI, CODEOWNERS, and deployable-specific images.

## Alternatives

- Separate web/API/ML repositories: stronger independent lifecycle but high contract/release coordination cost now.
- One undifferentiated application tree: simpler initially but erodes domain/deploy boundaries.

## Revisit

Revisit only when independent teams/releases/security boundaries or repository scale demonstrably make coordinated monorepo work slower. A split requires an ADR and contract/version migration.

