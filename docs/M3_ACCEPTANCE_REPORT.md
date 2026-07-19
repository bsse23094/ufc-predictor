# M3 final acceptance report

Status: **accepted and verified** (2026-07-19).

The machine-readable source of record is the deterministic, immutable
[`m3_final_acceptance_report.json`](../data/processed/m3-v6/.m3-generations/m3-74eeb9b7f49b5adca45e461a/m3_final_acceptance_report.json)
in generation `m3-74eeb9b7f49b5adca45e461a`. It inventories every published
Parquet artifact and normalized provenance with their schema, row count, and
SHA-256; it intentionally does not checksum itself.

| Check | Verified value |
| --- | --- |
| Ultimate raw SHA-256 | `deb1cd9a7014c08a538875e2b585e6f51fbf8f7a6d3f981eb684db1bd7242dc5` |
| UFC-DataLab raw SHA-256 | `26a49b01247a1f51c0553fbcfd3d1dc6529b4fae3b145799d7433270bafeae10` |
| v6 ledger | 34 records; `e4092ca73c5d15dc8695db33c291f6a472b5fe0e36b0d705a19fc64fa37215bb` |
| Supplemental ledger | 102 records; `c3afdcca5efc88f2c24654618d29bae7f809cf6ce1e040a5eca216bc3e2a0fba` |
| Authority resolution | 62 / 62 exact ledger references resolved |
| Canonical output | 2,790 fighters; 9,068 reconciled and historical bouts |
| Feature output | 18,136 fighter-history; 18,136 performance; 9,068 pairwise rows |
| Model-ready binary | 8,912 rows, 138 columns, 130 prediction-safe features; 4,610 target 1 / 4,302 target 0 |
| Eligibility | `9,068 - 65 draws - 91 no contests = 8,912` |
| Provenance | 150,162 unique output rows covered (100%); 501,589 physical lineage rows |
| Audit | 0 unresolved conflicts, invalid floats, target nulls, missingness mismatches, or provenance orphans |

The two reviewed Ultimate records are retained as traceable exclusions.
Reviewed source authority consolidates Roldan Sangcha-an/Sangcha'an while
keeping Flyweight and Middleweight Bruno Silva identities separate. The
model projection excludes draws and no-contests only; its feature list has no
outcome/winner, finish, round/time, odds, ranking, source-corner, or
same-fight-performance field.

The final acceptance test verifies the JSON is canonical sorted compact UTF-8,
is artifact-derived, and matches the manifest, raw sources, immutable ledgers,
coverage, model targets, eligibility equation, and zero-count audits. Existing
Phase 2C coverage executes all three atomic publication failure injections
(`after_staging_before_validation`, `after_validation_before_commit`, and
`during_publication_before_pointer`) and proves the prior generation remains
unchanged.

Verification completed: the complete M3 data suite passed (`71 passed`), the
acceptance report replayed byte-identically (SHA-256
`5844d6b59ea693c8620a3443d82f4d704254023eba32e8967d1d280c9cc02c5c`), and
repository formatting, Ruff, mypy, architecture/docs and repository-policy
checks, `git diff --check`, and `docker compose config --quiet` passed.
