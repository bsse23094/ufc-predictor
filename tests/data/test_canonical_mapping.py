from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict
from uuid import NAMESPACE_URL, UUID, uuid5

import polars as pl
import pytest

from ufc_predictor.canonical.mappers import canonicalize_kaggle_ultimate_records
from ufc_predictor.canonical.models import CanonicalMappingResult, ReviewedCanonicalAlias
from ufc_predictor.canonical.publisher import CANONICAL_SCHEMA_VERSION, publish_canonical_parquet
from ufc_predictor.canonical.taxonomy import (
    CanonicalOutcomeType,
    DivisionTaxonomyEntry,
    MethodTaxonomyEntry,
    ObservedLabelTaxonomy,
    OutcomeTaxonomyEntry,
    SourceFighterField,
    TaxonomyScope,
)
from ufc_predictor.ingestion.base import ParsedRecord
from ufc_predictor.ingestion.kaggle_ultimate import ingest_local_kaggle_ultimate_dataset
from ufc_predictor.ingestion.policies import KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY

FIXTURE = Path(__file__).parents[1] / "fixtures" / "kaggle_ultimate" / "ufc-master.csv"
INGESTED_AT = datetime(2026, 7, 17, tzinfo=UTC)


class MappingApproval(TypedDict):
    mapping_version: str
    approved_by: str
    approved_at: datetime
    rationale: str


def _incoming_fixture(tmp_path: Path) -> Path:
    incoming = tmp_path / "incoming" / "ultimate-ufc-dataset"
    incoming.mkdir(parents=True)
    shutil.copy2(FIXTURE, incoming / "ufc-master.csv")
    return incoming


def _fighter_id(alias: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"fixture-canonical-fighter:{alias}")


def _scope(records: tuple[ParsedRecord, ...]) -> TaxonomyScope:
    first = records[0]
    schema_version = first.payload["source_schema_version"]
    assert isinstance(schema_version, str)
    return TaxonomyScope(
        source_identifier=KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY,
        source_schema_version=schema_version,
    )


def _aliases(records: tuple[ParsedRecord, ...]) -> tuple[ReviewedCanonicalAlias, ...]:
    aliases: list[ReviewedCanonicalAlias] = []
    for record in records:
        fields = record.payload["source_fields"]
        schema = record.payload["source_schema_version"]
        assert isinstance(fields, dict)
        assert isinstance(schema, str)
        for field_name in ("R_fighter", "B_fighter"):
            alias_value = fields[field_name]
            assert isinstance(alias_value, str)
            aliases.append(
                ReviewedCanonicalAlias(
                    source_identifier=KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY,
                    source_schema_version=schema,
                    raw_sha256=record.raw_reference.sha256,
                    source_record_key=record.record_key,
                    source_field=field_name,
                    alias_value=alias_value,
                    fighter_id=_fighter_id(alias_value),
                    identity_resolution_decision_id=uuid5(
                        NAMESPACE_URL, f"fixture-review-decision:{record.record_key}:{field_name}"
                    ),
                )
            )
    return tuple(aliases)


def _taxonomy(scope: TaxonomyScope) -> ObservedLabelTaxonomy:
    approval: MappingApproval = {
        "mapping_version": "fixture-taxonomy-v1",
        "approved_by": "data-steward@example.test",
        "approved_at": INGESTED_AT,
        "rationale": "Synthetic fixture labels are explicitly reviewed for this test taxonomy.",
    }
    return ObservedLabelTaxonomy(
        taxonomy_version="fixture-taxonomy-v1",
        outcomes=(
            OutcomeTaxonomyEntry(
                scope=scope,
                source_label="Red",
                outcome_type=CanonicalOutcomeType.DECISIVE,
                winner_source_field=SourceFighterField.RED,
                **approval,
            ),
            OutcomeTaxonomyEntry(
                scope=scope,
                source_label="Blue",
                outcome_type=CanonicalOutcomeType.DECISIVE,
                winner_source_field=SourceFighterField.BLUE,
                **approval,
            ),
        ),
        methods=(
            MethodTaxonomyEntry(
                scope=scope,
                source_label="KO/TKO",
                canonical_method_code="knockout_or_tko",
                **approval,
            ),
            MethodTaxonomyEntry(
                scope=scope,
                source_label="U-DEC",
                canonical_method_code="unanimous_decision",
                **approval,
            ),
        ),
        divisions=(
            DivisionTaxonomyEntry(
                scope=scope,
                source_label="Lightweight",
                canonical_division_code="lightweight",
                **approval,
            ),
            DivisionTaxonomyEntry(
                scope=scope,
                source_label="Welterweight",
                canonical_division_code="welterweight",
                **approval,
            ),
        ),
    )


@pytest.mark.anyio
async def test_canonical_mapping_uses_ingested_records_and_publishes_provenance_complete_parquet(
    tmp_path: Path,
) -> None:
    ingestion = await ingest_local_kaggle_ultimate_dataset(
        incoming_directory=_incoming_fixture(tmp_path),
        raw_root=tmp_path / "raw",
        interim_root=tmp_path / "interim",
    )
    records = ingestion.execution.records
    mapped = canonicalize_kaggle_ultimate_records(
        records,
        reviewed_aliases=_aliases(records),
        taxonomy=_taxonomy(_scope(records)),
        ingested_at=INGESTED_AT,
    )

    assert mapped.input_count == 2
    assert not mapped.quarantined_record_keys
    assert len(mapped.accepted) == 2
    first, second = mapped.accepted
    assert first.winner_fighter_id == _fighter_id("Alpha Fighter")
    assert second.winner_fighter_id == _fighter_id("Delta Fighter")
    assert first.fighter_one_id != first.fighter_two_id
    assert str(first.fighter_one_id) < str(first.fighter_two_id)
    assert first.source_outcome_label == "Red"
    assert first.canonical_method_code == "knockout_or_tko"
    assert first.raw_reference.sha256 == records[0].raw_reference.sha256
    assert {label.field_name for label in mapped.observed_labels} == {
        "Winner",
        "finish",
        "weight_class",
    }

    published = publish_canonical_parquet(mapped, canonical_root=tmp_path / "canonical")
    replay = publish_canonical_parquet(mapped, canonical_root=tmp_path / "canonical")
    frame = pl.read_parquet(published.parquet_path)
    manifest = json.loads(published.manifest_path.read_text(encoding="utf-8"))

    assert replay.replayed is True
    assert frame.height == 2
    assert {
        "source_raw_sha256",
        "raw_object_uri",
        "winner_fighter_id",
        "source_outcome_label",
        "canonical_method_code",
    } <= set(frame.columns)
    assert manifest["canonical_schema_version"] == CANONICAL_SCHEMA_VERSION
    assert manifest["taxonomy_version"] == "fixture-taxonomy-v1"
    assert manifest["raw_references"][0]["sha256"] == records[0].raw_reference.sha256


@pytest.mark.anyio
async def test_unmapped_taxonomy_or_aliases_quarantine_rows_without_partial_publication(
    tmp_path: Path,
) -> None:
    ingestion = await ingest_local_kaggle_ultimate_dataset(
        incoming_directory=_incoming_fixture(tmp_path),
        raw_root=tmp_path / "raw",
        interim_root=tmp_path / "interim",
    )
    records = ingestion.execution.records
    unmapped = canonicalize_kaggle_ultimate_records(
        records,
        reviewed_aliases=_aliases(records),
        taxonomy=ObservedLabelTaxonomy(taxonomy_version="empty-taxonomy-v1"),
        ingested_at=INGESTED_AT,
    )

    assert not unmapped.accepted
    assert unmapped.input_count == 2
    assert len(unmapped.quarantined_record_keys) == 2
    assert {issue.rule_id for issue in unmapped.issues} >= {
        "CAN-003.unmapped_outcome_label",
        "CAN-003.unmapped_method_label",
        "CAN-003.unmapped_division_label",
    }
    with pytest.raises(ValueError, match="quarantined"):
        publish_canonical_parquet(unmapped, canonical_root=tmp_path / "canonical")

    missing_alias = canonicalize_kaggle_ultimate_records(
        records,
        reviewed_aliases=_aliases(records)[1:],
        taxonomy=_taxonomy(_scope(records)),
        ingested_at=INGESTED_AT,
    )
    assert missing_alias.input_count == 2
    assert len(missing_alias.accepted) == 1
    assert len(missing_alias.quarantined_record_keys) == 1
    assert "CAN-002.unresolved_fighter_alias" in {issue.rule_id for issue in missing_alias.issues}


@pytest.mark.anyio
async def test_canonical_duplicate_collision_is_quarantined_after_identity_resolution(
    tmp_path: Path,
) -> None:
    ingestion = await ingest_local_kaggle_ultimate_dataset(
        incoming_directory=_incoming_fixture(tmp_path),
        raw_root=tmp_path / "raw",
        interim_root=tmp_path / "interim",
    )
    first, second = ingestion.execution.records
    source_fields = second.payload["source_fields"]
    assert isinstance(source_fields, dict)
    second_fields = dict(source_fields)
    second_fields["date"] = "2024-01-20"
    second_fields["weight_class"] = "Lightweight"
    colliding_second = replace(second, payload={**second.payload, "source_fields": second_fields})
    aliases = list(_aliases((first, colliding_second)))
    aliases[2] = replace(aliases[2], fighter_id=_fighter_id("Alpha Fighter"))
    aliases[3] = replace(aliases[3], fighter_id=_fighter_id("Beta Fighter"))

    mapped = canonicalize_kaggle_ultimate_records(
        (first, colliding_second),
        reviewed_aliases=aliases,
        taxonomy=_taxonomy(_scope((first, colliding_second))),
        ingested_at=INGESTED_AT,
    )

    assert len(mapped.accepted) == 1
    assert mapped.quarantined_record_keys == (colliding_second.record_key,)
    assert {issue.rule_id for issue in mapped.issues} == {"CAN-004.duplicate_canonical_fight"}


def test_conflicting_taxonomy_entries_are_rejected_deterministically() -> None:
    scope = TaxonomyScope(
        source_identifier=KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY,
        source_schema_version="fixture-schema-v1",
    )
    approval: MappingApproval = {
        "mapping_version": "fixture-taxonomy-v1",
        "approved_by": "data-steward@example.test",
        "approved_at": INGESTED_AT,
        "rationale": "Fixture review.",
    }
    red = OutcomeTaxonomyEntry(
        scope=scope,
        source_label="Red",
        outcome_type=CanonicalOutcomeType.DECISIVE,
        winner_source_field=SourceFighterField.RED,
        **approval,
    )
    conflicting_red = replace(red, winner_source_field=SourceFighterField.BLUE)

    with pytest.raises(ValueError, match="conflicting taxonomy"):
        ObservedLabelTaxonomy(
            taxonomy_version="fixture-taxonomy-v1", outcomes=(red, conflicting_red)
        )


def test_canonical_mapping_quarantine_cannot_omit_its_audit_issue() -> None:
    with pytest.raises(ValueError, match="requires an issue"):
        CanonicalMappingResult(
            accepted=(),
            quarantined_record_keys=("fixture-row-1",),
            issues=(),
            observed_labels=(),
        )
