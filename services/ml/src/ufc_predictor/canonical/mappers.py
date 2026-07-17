"""Map accepted Kaggle source records to typed canonical bout observations.

The mapper accepts only exact, already-reviewed alias evidence and an explicit
observed-label taxonomy.  It never resolves a name, guesses an outcome/method/
division label, or emits a partial canonical fact.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from uuid import UUID

from ufc_predictor.canonical.models import (
    CanonicalFightObservation,
    CanonicalMappingIssue,
    CanonicalMappingResult,
    ReviewedCanonicalAlias,
)
from ufc_predictor.canonical.taxonomy import (
    ObservedLabel,
    ObservedLabelTaxonomy,
    SourceFighterField,
    TaxonomyScope,
)
from ufc_predictor.ingestion.base import ParsedRecord
from ufc_predictor.ingestion.policies import KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY

_REQUIRED_TAXONOMY_FIELDS = ("Winner", "finish", "weight_class")


def canonicalize_kaggle_ultimate_records(
    records: Iterable[ParsedRecord],
    *,
    reviewed_aliases: Iterable[ReviewedCanonicalAlias],
    taxonomy: ObservedLabelTaxonomy,
    ingested_at: datetime,
) -> CanonicalMappingResult:
    """Map accepted Kaggle records or quarantine every unresolved/conflicting row.

    ``ingested_at`` is the known platform timestamp, not an invented source
    observation time.  Milestone 4 must still decide temporal eligibility for
    every future feature use.
    """

    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise ValueError("ingested_at must be timezone-aware")
    alias_index = _alias_index(reviewed_aliases)
    accepted: list[CanonicalFightObservation] = []
    quarantined: list[str] = []
    issues: list[CanonicalMappingIssue] = []
    observed_labels: list[ObservedLabel] = []
    seen_fights: set[tuple[date, UUID, UUID, str]] = set()

    for record in records:
        observation, record_issues, record_labels = _map_record(
            record,
            alias_index=alias_index,
            taxonomy=taxonomy,
            ingested_at=ingested_at,
        )
        observed_labels.extend(record_labels)
        if record_issues:
            quarantined.append(record.record_key)
            issues.extend(record_issues)
            continue
        if observation is None:
            raise AssertionError("a canonical record without issues must map")
        duplicate_key = (
            observation.fight_date,
            observation.fighter_one_id,
            observation.fighter_two_id,
            observation.canonical_division_code,
        )
        if duplicate_key in seen_fights:
            quarantined.append(record.record_key)
            issues.append(
                _issue(
                    record,
                    "CAN-004.duplicate_canonical_fight",
                    "canonical fighter pair/date/division collides with an earlier accepted record",
                )
            )
            continue
        seen_fights.add(duplicate_key)
        accepted.append(observation)

    return CanonicalMappingResult(
        accepted=tuple(accepted),
        quarantined_record_keys=tuple(quarantined),
        issues=tuple(issues),
        observed_labels=tuple(observed_labels),
    )


def _map_record(
    record: ParsedRecord,
    *,
    alias_index: Mapping[tuple[str, str, str, str, str, str], ReviewedCanonicalAlias],
    taxonomy: ObservedLabelTaxonomy,
    ingested_at: datetime,
) -> tuple[
    CanonicalFightObservation | None, tuple[CanonicalMappingIssue, ...], tuple[ObservedLabel, ...]
]:
    fields = _source_fields(record)
    source_schema_version = _required_text(record.payload, "source_schema_version")
    scope = TaxonomyScope(
        source_identifier=KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY,
        source_schema_version=source_schema_version,
    )
    issues: list[CanonicalMappingIssue] = []
    labels = _observed_labels(record, fields, scope)
    red_name = _field_text(fields, "R_fighter", record, issues)
    blue_name = _field_text(fields, "B_fighter", record, issues)
    fight_date = _field_date(fields, "date", record, issues)
    scheduled_rounds = _field_positive_int(fields, "no_of_rounds", record, issues)
    title_bout = _field_bool(fields, "title_bout", record, issues)
    outcome_label = _field_text(fields, "Winner", record, issues)
    method_label = _field_text(fields, "finish", record, issues)
    division_label = _field_text(fields, "weight_class", record, issues)

    red_alias = _alias_for(
        record,
        source_schema_version=source_schema_version,
        source_field=SourceFighterField.RED.value,
        alias_value=red_name,
        alias_index=alias_index,
        issues=issues,
    )
    blue_alias = _alias_for(
        record,
        source_schema_version=source_schema_version,
        source_field=SourceFighterField.BLUE.value,
        alias_value=blue_name,
        alias_index=alias_index,
        issues=issues,
    )

    outcome = taxonomy.outcome_for(scope, outcome_label) if outcome_label is not None else None
    if outcome_label is not None and outcome is None:
        issues.append(
            _issue(
                record, "CAN-003.unmapped_outcome_label", "outcome label requires reviewed taxonomy"
            )
        )
    method = taxonomy.method_for(scope, method_label) if method_label is not None else None
    if method_label is not None and method is None:
        issues.append(
            _issue(
                record, "CAN-003.unmapped_method_label", "method label requires reviewed taxonomy"
            )
        )
    division = taxonomy.division_for(scope, division_label) if division_label is not None else None
    if division_label is not None and division is None:
        issues.append(
            _issue(
                record,
                "CAN-003.unmapped_division_label",
                "division label requires reviewed taxonomy",
            )
        )
    if issues:
        return None, tuple(issues), labels
    if (
        red_alias is None
        or blue_alias is None
        or fight_date is None
        or scheduled_rounds is None
        or outcome is None
        or method is None
        or division is None
        or outcome_label is None
        or method_label is None
        or division_label is None
    ):
        raise AssertionError("a source row without mapping issues has incomplete canonical fields")

    fighter_one_id, fighter_two_id = sorted((red_alias.fighter_id, blue_alias.fighter_id), key=str)
    winner_fighter_id = None
    if outcome.winner_source_field is SourceFighterField.RED:
        winner_fighter_id = red_alias.fighter_id
    elif outcome.winner_source_field is SourceFighterField.BLUE:
        winner_fighter_id = blue_alias.fighter_id
    identity_decisions = (
        (red_alias.identity_resolution_decision_id, blue_alias.identity_resolution_decision_id)
        if str(red_alias.identity_resolution_decision_id)
        <= str(blue_alias.identity_resolution_decision_id)
        else (blue_alias.identity_resolution_decision_id, red_alias.identity_resolution_decision_id)
    )
    return (
        CanonicalFightObservation(
            canonical_source_fight_key=(
                f"{KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY}:{record.raw_reference.sha256}:"
                f"{record.record_key}"
            ),
            source_identifier=KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY,
            source_schema_version=source_schema_version,
            source_record_key=record.record_key,
            raw_reference=record.raw_reference,
            fighter_one_id=fighter_one_id,
            fighter_two_id=fighter_two_id,
            fight_date=fight_date,
            scheduled_rounds=scheduled_rounds,
            canonical_division_code=division.canonical_division_code,
            source_division_label=division_label,
            location=_optional_text(fields.get("location")),
            country=_optional_text(fields.get("country")),
            title_bout=title_bout,
            outcome_type=outcome.outcome_type,
            winner_fighter_id=winner_fighter_id,
            source_outcome_label=outcome_label,
            canonical_method_code=method.canonical_method_code,
            source_method_label=method_label,
            ingested_at=ingested_at,
            identity_resolution_decision_ids=identity_decisions,
            taxonomy_version=taxonomy.taxonomy_version,
        ),
        (),
        labels,
    )


def _alias_index(
    reviewed_aliases: Iterable[ReviewedCanonicalAlias],
) -> dict[tuple[str, str, str, str, str, str], ReviewedCanonicalAlias]:
    indexed: dict[tuple[str, str, str, str, str, str], ReviewedCanonicalAlias] = {}
    for alias in reviewed_aliases:
        key = (
            alias.source_identifier,
            alias.source_schema_version,
            alias.raw_sha256,
            alias.source_record_key,
            alias.source_field,
            alias.alias_value,
        )
        existing = indexed.setdefault(key, alias)
        if existing != alias:
            raise ValueError("conflicting reviewed aliases share exact source evidence")
    return indexed


def _alias_for(
    record: ParsedRecord,
    *,
    source_schema_version: str,
    source_field: str,
    alias_value: str | None,
    alias_index: Mapping[tuple[str, str, str, str, str, str], ReviewedCanonicalAlias],
    issues: list[CanonicalMappingIssue],
) -> ReviewedCanonicalAlias | None:
    if alias_value is None:
        return None
    key = (
        KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY,
        source_schema_version,
        record.raw_reference.sha256,
        record.record_key,
        source_field,
        alias_value,
    )
    alias = alias_index.get(key)
    if alias is None:
        issues.append(
            _issue(
                record,
                "CAN-002.unresolved_fighter_alias",
                f"{source_field} has no exact reviewed canonical alias",
            )
        )
    return alias


def _observed_labels(
    record: ParsedRecord,
    fields: Mapping[str, object],
    scope: TaxonomyScope,
) -> tuple[ObservedLabel, ...]:
    return tuple(
        ObservedLabel(
            scope=scope,
            record_key=record.record_key,
            raw_sha256=record.raw_reference.sha256,
            field_name=field_name,
            original_value=value,
        )
        for field_name in _REQUIRED_TAXONOMY_FIELDS
        if (value := _optional_text(fields.get(field_name))) is not None
    )


def _source_fields(record: ParsedRecord) -> Mapping[str, object]:
    fields = record.payload.get("source_fields")
    if not isinstance(fields, Mapping):
        raise ValueError("source record has no source_fields mapping")
    return fields


def _required_text(payload: Mapping[str, object], field_name: str) -> str:
    value = _optional_text(payload.get(field_name))
    if value is None:
        raise ValueError(f"source record has no {field_name}")
    return value


def _field_text(
    fields: Mapping[str, object],
    field_name: str,
    record: ParsedRecord,
    issues: list[CanonicalMappingIssue],
) -> str | None:
    value = _optional_text(fields.get(field_name))
    if value is None:
        issues.append(_issue(record, "CAN-001.required_source_field", f"{field_name} is required"))
    return value


def _field_date(
    fields: Mapping[str, object],
    field_name: str,
    record: ParsedRecord,
    issues: list[CanonicalMappingIssue],
) -> date | None:
    value = _optional_text(fields.get(field_name))
    if value is None:
        issues.append(_issue(record, "CAN-001.required_source_field", f"{field_name} is required"))
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        issues.append(_issue(record, "CAN-001.invalid_fight_date", "date must be ISO-8601"))
        return None


def _field_positive_int(
    fields: Mapping[str, object],
    field_name: str,
    record: ParsedRecord,
    issues: list[CanonicalMappingIssue],
) -> int | None:
    value = _optional_text(fields.get(field_name))
    if value is None or not value.isdecimal() or int(value) < 1:
        issues.append(
            _issue(record, "CAN-001.invalid_scheduled_rounds", "scheduled rounds must be positive")
        )
        return None
    return int(value)


def _field_bool(
    fields: Mapping[str, object],
    field_name: str,
    record: ParsedRecord,
    issues: list[CanonicalMappingIssue],
) -> bool | None:
    value = _optional_text(fields.get(field_name))
    if value is None:
        return None
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    issues.append(_issue(record, "CAN-001.invalid_title_bout", "title_bout must be true or false"))
    return None


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _issue(record: ParsedRecord, rule_id: str, summary: str) -> CanonicalMappingIssue:
    return CanonicalMappingIssue(
        rule_id=rule_id,
        source_record_key=record.record_key,
        raw_sha256=record.raw_reference.sha256,
        summary=summary,
    )
