"""Generic validation and row-accounting primitives for ingestion runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ufc_predictor.ingestion.base import ParsedRecord, SchemaFingerprint


class IssueSeverity(StrEnum):
    """Disposition severity, ordered by publication impact rather than aesthetics."""

    WARNING = "warning"
    QUARANTINE = "quarantine"
    BLOCKING = "blocking"


class RecordDisposition(StrEnum):
    """The mutually exclusive, auditable outcome for one parsed source record."""

    ACCEPTED = "accepted"
    QUARANTINED = "quarantined"
    FILTERED = "filtered"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Machine-readable validation outcome with an optional raw reference."""

    rule_id: str
    severity: IssueSeverity
    summary: str
    raw_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_id or not self.summary:
            raise ValueError("rule_id and summary are required")


@dataclass(frozen=True, slots=True)
class ValidatedRecord:
    """A parsed record plus its explicit validation disposition and reason(s)."""

    record: ParsedRecord
    disposition: RecordDisposition
    issues: tuple[ValidationIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.disposition is RecordDisposition.ACCEPTED:
            return
        if not self.issues:
            raise ValueError("filtered or quarantined records require a validation issue")
        if self.disposition is RecordDisposition.QUARANTINED and not any(
            issue.severity in {IssueSeverity.QUARANTINE, IssueSeverity.BLOCKING}
            for issue in self.issues
        ):
            raise ValueError("quarantined records require a quarantine or blocking issue")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Complete run-level report; callers must not silently discard records."""

    issues: tuple[ValidationIssue, ...] = ()

    @property
    def has_blocking_issue(self) -> bool:
        return any(issue.severity is IssueSeverity.BLOCKING for issue in self.issues)

    @property
    def requires_quarantine(self) -> bool:
        return any(issue.severity is IssueSeverity.QUARANTINE for issue in self.issues)

    @property
    def allows_publication(self) -> bool:
        return not self.has_blocking_issue and not self.requires_quarantine


@dataclass(frozen=True, slots=True)
class RowAccounting:
    """Explicit accounting required before any checkpoint can advance."""

    input_count: int
    accepted_count: int
    quarantined_count: int
    filtered_count: int

    def __post_init__(self) -> None:
        if any(
            count < 0
            for count in (
                self.input_count,
                self.accepted_count,
                self.quarantined_count,
                self.filtered_count,
            )
        ):
            raise ValueError("row accounting counts must be non-negative")

    @property
    def output_count(self) -> int:
        return self.accepted_count + self.quarantined_count + self.filtered_count

    @property
    def delta(self) -> int:
        return self.input_count - self.output_count

    def assert_balanced(self) -> None:
        """Raise rather than permit a silently lost or fabricated row."""

        if self.delta:
            raise ValueError(
                "row accounting does not balance: "
                f"input={self.input_count}, output={self.output_count}, delta={self.delta}"
            )


@dataclass(frozen=True, slots=True)
class SchemaGate:
    """Allow only adapter fingerprints established by an approved source audit."""

    known_fingerprints: frozenset[str] = field(default_factory=frozenset)

    def assess(self, fingerprint: SchemaFingerprint, *, raw_sha256: str) -> ValidationReport:
        """Quarantine an unknown structure and prevent its run from publishing."""

        if fingerprint.value in self.known_fingerprints:
            return ValidationReport()
        return ValidationReport(
            issues=(
                ValidationIssue(
                    rule_id="DAT-003.unknown_schema_fingerprint",
                    severity=IssueSeverity.QUARANTINE,
                    summary=f"unknown schema fingerprint: {fingerprint.value}",
                    raw_sha256=raw_sha256,
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class TransportPolicy:
    """Source-neutral maximum response guard; source-specific policy may be stricter."""

    max_response_bytes: int

    def __post_init__(self) -> None:
        if self.max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")

    def assess(self, *, status_code: int, byte_length: int) -> ValidationReport:
        """Report unsafe transport outcomes without trying to parse them."""

        issues: list[ValidationIssue] = []
        if not 200 <= status_code < 300:
            issues.append(
                ValidationIssue(
                    rule_id="DAT-001.http_status",
                    severity=IssueSeverity.BLOCKING,
                    summary=f"unexpected HTTP status: {status_code}",
                )
            )
        if byte_length > self.max_response_bytes:
            issues.append(
                ValidationIssue(
                    rule_id="DAT-001.response_too_large",
                    severity=IssueSeverity.BLOCKING,
                    summary=f"response size {byte_length} exceeds configured maximum",
                )
            )
        return ValidationReport(issues=tuple(issues))
