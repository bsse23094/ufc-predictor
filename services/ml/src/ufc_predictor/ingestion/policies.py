"""Audited source-policy entries owned by Milestone 2 ingestion.

Only local files acquired through the documented Kaggle dataset page are enabled
here.  This module intentionally contains neither credentials nor a network
download implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ufc_predictor.ingestion.rate_limit import RateLimitPolicy
from ufc_predictor.ingestion.registry import SourceAuditState, SourcePolicy

KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY = "kaggle-ultimate-ufc-dataset"
KAGGLE_ULTIMATE_UFC_DATASET_REF = "mdabbert/ultimate-ufc-dataset"
KAGGLE_ULTIMATE_UFC_DATASET_LICENSE = "CC-BY-4.0"
KAGGLE_ULTIMATE_UFC_DATASET_TERMS_VERSION = "CC-BY-4.0/kaggle-v181-2026-04-01"
KAGGLE_ULTIMATE_UFC_DATASET_ATTRIBUTION = (
    "Ultimate UFC Dataset by mdabbert, via Kaggle, licensed CC BY 4.0; "
    "https://www.kaggle.com/datasets/mdabbert/ultimate-ufc-dataset "
    "(local normalization changes are documented in the interim manifest)."
)

UFC_DATALAB_SOURCE_KEY = "ufc-datalab"
UFC_DATALAB_REPOSITORY_URL = "https://github.com/komaksym/UFC-DataLab.git"
UFC_DATALAB_LICENSE = "MIT"
UFC_DATALAB_TERMS_VERSION = "repository-mit-local-pinned-raw-v1"
UFC_DATALAB_ATTRIBUTION = (
    "UFC-DataLab by komaksym, pinned local Git checkout; licensed MIT; "
    "https://github.com/komaksym/UFC-DataLab. Upstream attribution: UFC Official Fight "
    "Statistics (UFCStats), as documented by the pinned repository README; this project "
    "retains only the local pinned copy and makes no direct UFCStats request."
)


def kaggle_ultimate_ufc_dataset_policy() -> SourcePolicy:
    """Return the approved local-file policy for Kaggle dataset version 181.

    The rate cap is a one-file-at-a-time local-read cap, not a claimed Kaggle
    API allowance.  Downloading remains a manual, user-authorized operation.
    """

    return SourcePolicy(
        source_key=KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY,
        audit_state=SourceAuditState.APPROVED,
        enabled=True,
        dataset_license=KAGGLE_ULTIMATE_UFC_DATASET_LICENSE,
        terms_policy_version=KAGGLE_ULTIMATE_UFC_DATASET_TERMS_VERSION,
        retention_classification="cc-by-4.0-local-raw-with-attribution",
        approved_at=datetime(2026, 7, 17, tzinfo=UTC),
        audit_evidence_ref="docs/architecture/DATA_SOURCE_AUDIT.md#kaggle-ultimate-ufc-dataset",
        rate_limit=RateLimitPolicy(requests_per_minute=60, max_concurrency=1),
        attribution=KAGGLE_ULTIMATE_UFC_DATASET_ATTRIBUTION,
    )


def ufc_datalab_policy() -> SourcePolicy:
    """Return the local-copy-only policy for the approved raw stats file.

    This policy permits neither GitHub calls nor UFCStats access at ingestion
    time. Acquisition is a separate, manually recorded cache operation.
    """

    return SourcePolicy(
        source_key=UFC_DATALAB_SOURCE_KEY,
        audit_state=SourceAuditState.APPROVED,
        enabled=True,
        dataset_license=UFC_DATALAB_LICENSE,
        terms_policy_version=UFC_DATALAB_TERMS_VERSION,
        retention_classification="mit-local-raw-pinned-repository-copy",
        approved_at=datetime(2026, 7, 17, tzinfo=UTC),
        audit_evidence_ref="docs/architecture/DATA_SOURCE_AUDIT.md#ufc-datalab",
        rate_limit=RateLimitPolicy(requests_per_minute=60, max_concurrency=1),
        attribution=UFC_DATALAB_ATTRIBUTION,
    )
