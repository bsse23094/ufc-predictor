# ADR-0004: Hybrid in-process model serving

Status: Accepted  
Date: 2026-07-17

## Context

Interactive predictions need low latency; explanations, large Monte Carlo runs, bulk snapshots, and feature builds can be slow. A dedicated model microservice could scale independently but adds a network boundary, deployment, protocol, and failure mode before scale is known.

## Decision

Load trusted approved model bundles inside each FastAPI process for bounded low-latency inference. Execute both orientations, calibration, reconciliation, and confidence there. Queue expensive/long/bulk operations to Celery workers that load the same versioned bundle. Hide serving behind a PredictionPort so it can later become a network client.

## Rationale

Tabular CPU models are expected to fit in API memory and run quickly. Avoiding a network hop simplifies the MVP and improves latency/reliability. Workers isolate resource-heavy paths without requiring a separate inference product.

## Consequences

Positive:

- simple deployment/debugging and low interactive latency;
- exact bundle/contract shared by API and workers;
- no distributed inference API to operate.

Negative:

- model memory is duplicated per API replica;
- app and model releases/capability readiness are coupled;
- hot promotion requires atomic load/smoke/swap logic;
- CPU inference must not starve async request handling.

Bundles are bounded/cached, loaded by digest, warmed before readiness/swap, and kept behind an interface.

## Alternatives

- Dedicated inference service now: independent scaling/isolation but added latency and distributed version/failure complexity.
- All inference through workers: simple API memory but poor interactive latency and queue dependence.
- Client-side inference: exposes artifacts, breaks governance, and is unsuitable for canonical feature access.

## Revisit

Extract a service if model memory/hardware, independent scale/release cadence, multiple consumers, or security isolation is measured. The extraction requires a versioned internal protocol and new ADR.

