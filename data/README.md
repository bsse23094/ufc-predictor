# Data policy

This directory is the local/object-storage mirror for the project data planes. Its contents are deliberately ignored by Git, except for the `.gitkeep` files that preserve the directory layout.

- `raw/` is append-only evidence and must never be edited in place.
- `quarantine/` contains raw references and machine-readable quality findings.
- `interim/` contains rebuildable source-shaped outputs.
- `processed/` contains immutable, versioned datasets and feature snapshots.

No source has been approved or ingested. Source-neutral raw-storage code is contract-tested only with synthetic bytes; it is not authorization to fetch, store, or redistribute a provider's data. Do not place credentials, licensed source data, or model artifacts in this repository.
