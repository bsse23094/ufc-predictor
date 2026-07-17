# Data dictionary

The canonical data dictionary will be generated from observed, approved source schemas during the ingestion and canonical-data milestones. It does not exist yet because the architecture explicitly forbids inventing source fields, labels, units, or merge keys.

Until source audit evidence exists, the only committed data contract is the architecture-defined category model:

- raw retrieval metadata and checksums;
- source-shaped records with raw references;
- canonical identities, events, fights, participants, and observations;
- point-in-time feature snapshots with lineage and missingness;
- immutable datasets, model bundles, and prediction snapshots.

See [DOMAIN_MODEL.md](docs/architecture/DOMAIN_MODEL.md) and [DATABASE_SCHEMA.md](docs/architecture/DATABASE_SCHEMA.md) for the planned ownership and semantics.
