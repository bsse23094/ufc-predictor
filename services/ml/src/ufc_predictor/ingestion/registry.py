"""Source-policy registry that keeps every source disabled until approved."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ufc_predictor.ingestion.base import require_utc
from ufc_predictor.ingestion.rate_limit import RateLimitPolicy


class SourceAuditState(StrEnum):
    """Evidence state for a potential data source."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SourcePolicyError(RuntimeError):
    """Raised before any work can start for a source without a complete policy."""


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    """Audited policy metadata; credentials intentionally have no place here."""

    source_key: str
    audit_state: SourceAuditState = SourceAuditState.PENDING
    enabled: bool = False
    dataset_license: str | None = None
    terms_policy_version: str | None = None
    retention_classification: str | None = None
    approved_at: datetime | None = None
    audit_evidence_ref: str | None = None
    rate_limit: RateLimitPolicy | None = None
    attribution: str | None = None

    def __post_init__(self) -> None:
        if not self.source_key:
            raise ValueError("source_key is required")
        if self.approved_at is not None:
            object.__setattr__(self, "approved_at", require_utc(self.approved_at))
        if self.audit_state is SourceAuditState.APPROVED:
            required = {
                "terms_policy_version": self.terms_policy_version,
                "retention_classification": self.retention_classification,
                "approved_at": self.approved_at,
                "audit_evidence_ref": self.audit_evidence_ref,
            }
            missing = [field for field, value in required.items() if not value]
            if missing:
                raise ValueError(f"approved source policy is missing: {', '.join(missing)}")
        if self.enabled and self.audit_state is not SourceAuditState.APPROVED:
            raise ValueError("a source cannot be enabled before its audit is approved")

    def assert_fetch_permitted(self) -> None:
        """Fail closed unless both audit evidence and explicit enablement exist."""

        if self.audit_state is not SourceAuditState.APPROVED:
            raise SourcePolicyError(f"source '{self.source_key}' has no approved audit")
        if not self.enabled:
            raise SourcePolicyError(f"source '{self.source_key}' is disabled by policy")
        if self.rate_limit is None:
            raise SourcePolicyError(f"source '{self.source_key}' has no audited rate policy")


class SourceRegistry:
    """In-memory policy lookup; durable policy records are added with API persistence."""

    def __init__(self, policies: Iterable[SourcePolicy] = ()) -> None:
        self._policies: dict[str, SourcePolicy] = {}
        for policy in policies:
            self.register(policy)

    def register(self, policy: SourcePolicy) -> None:
        """Register one unique policy record without automatically enabling it."""

        if policy.source_key in self._policies:
            raise ValueError(f"duplicate source policy: {policy.source_key}")
        self._policies[policy.source_key] = policy

    def get(self, source_key: str) -> SourcePolicy:
        """Return configured policy or a non-enabling error."""

        try:
            return self._policies[source_key]
        except KeyError as exc:
            raise SourcePolicyError(f"source '{source_key}' is not registered") from exc

    def require_enabled(self, source_key: str) -> SourcePolicy:
        """Return only a source that is independently approved and enabled."""

        policy = self.get(source_key)
        policy.assert_fetch_permitted()
        return policy

    @property
    def enabled_source_keys(self) -> tuple[str, ...]:
        """Expose enabled keys for observability without exposing credentials."""

        return tuple(
            key
            for key, policy in self._policies.items()
            if policy.audit_state is SourceAuditState.APPROVED and policy.enabled
        )
