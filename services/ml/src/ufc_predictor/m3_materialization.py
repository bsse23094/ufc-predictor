"""Derived, replayable M3 post-review canonical materialization."""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, uuid5

import polars as pl

from ufc_predictor.identity.normalize import normalize_fighter_alias
from ufc_predictor.validation_support import content_sha256


@dataclass(frozen=True, slots=True)
class AuthorityRecord:
    authority_id: str
    ledger_identifier: str
    payload: dict[str, str]


@dataclass(frozen=True, slots=True)
class TaxonomyAuthority:
    """One reviewed taxonomy decision and its retained-source applicability."""

    authority_id: str
    ledger_identifier: str
    source_name: str
    source_schema_version: str
    field_name: str
    raw_value: str | None
    canonical_value: str | None
    is_null_policy: bool
    decision_reference: str
    decision_action: str
    category: str
    source_evidence_sha256: str
    classification: str


@dataclass(frozen=True, slots=True)
class SourceOutcome:
    outcome: str
    winner_fighter_id: str | None
    loser_fighter_id: str | None
    is_no_contest: bool
    is_draw: bool


class AuthorityIndex:
    """Exact immutable-authority lookup; IDs may exist in one ledger only."""

    def __init__(self, records: tuple[AuthorityRecord, ...]) -> None:
        grouped: defaultdict[str, list[AuthorityRecord]] = defaultdict(list)
        for record in records:
            grouped[record.authority_id].append(record)
        duplicates = [key for key, values in grouped.items() if len(values) != 1]
        if duplicates:
            raise ValueError(f"authority ID resolves to multiple ledgers: {duplicates[0]}")
        self._records = {key: values[0] for key, values in grouped.items()}

    @property
    def record_count(self) -> int:
        return len(self._records)

    @property
    def records(self) -> tuple[AuthorityRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def count_for_ledger(self, ledger_identifier: str) -> int:
        return sum(
            record.ledger_identifier == ledger_identifier for record in self._records.values()
        )

    def resolve(self, authority_id: str, ledger_identifier: str) -> AuthorityRecord:
        record = self._records.get(authority_id)
        if record is None:
            raise ValueError(f"authority ID resolves to zero ledger records: {authority_id}")
        if record.ledger_identifier != ledger_identifier:
            raise ValueError(f"authority ledger mismatch for ID: {authority_id}")
        return record


V6_LEDGER_IDENTIFIER = "m3-corrections-v6/m3_imported_decisions.jsonl"
SUPPLEMENTAL_LEDGER_IDENTIFIER = (
    "m3-corrections-v6/authority-migration-v1/m3_supplemental_legacy_authorities.jsonl"
)
M3_PHASE2C_SCHEMA_VERSION = "m3-phase3a-v1"
_CURRENT_GENERATION_POINTER = "m3_phase2_current.json"
_GENERATION_DIRECTORY = ".m3-generations"

_RECONCILIATION_SCHEMA: dict[str, type[pl.DataType]] = {
    "canonical_bout_id": pl.String,
    "fight_date": pl.Date,
    "canonical_fighter_a_id": pl.String,
    "canonical_fighter_b_id": pl.String,
    "fighter_orientation": pl.String,
    "source_presence": pl.String,
    "ultimate_source_row_id": pl.String,
    "ufc_datalab_source_row_id": pl.String,
    "ultimate_outcome_raw": pl.String,
    "ufc_datalab_outcome_raw": pl.String,
    "canonical_outcome": pl.String,
    "winner_canonical_fighter_id": pl.String,
    "loser_canonical_fighter_id": pl.String,
    "is_no_contest": pl.Boolean,
    "is_draw": pl.Boolean,
    "canonical_finish_method": pl.String,
    "canonical_finish_round": pl.Int64,
    "canonical_finish_time": pl.String,
    "canonical_scheduled_format": pl.String,
    "reconciliation_status": pl.String,
    "outcome_authority_id": pl.String,
    "authority_ledger_identifier": pl.String,
    "decision_reference": pl.String,
    "evidence_sha256": pl.String,
}

_EXCLUSION_SCHEMA: dict[str, type[pl.DataType]] = {
    "source_name": pl.String,
    "source_schema_version": pl.String,
    "source_row_id": pl.String,
    "exclusion_reason_code": pl.String,
    "exclusion_reason": pl.String,
    "authority_id": pl.String,
    "ledger_identifier": pl.String,
    "decision_reference": pl.String,
    "source_evidence_sha256": pl.String,
    "evidence_sha256": pl.String,
}

_DUPLICATE_SCHEMA: dict[str, type[pl.DataType]] = {
    "source_name": pl.String,
    "source_schema_version": pl.String,
    "duplicate_source_row_id": pl.String,
    "retained_source_row_id": pl.String,
    "canonical_bout_id": pl.String,
    "duplicate_reason": pl.String,
    "compared_fighter_a_normalized": pl.String,
    "compared_fighter_b_normalized": pl.String,
    "compared_fight_date": pl.String,
    "lineage_type": pl.String,
    "authority_id": pl.String,
    "ledger_identifier": pl.String,
    "deterministic_rule_id": pl.String,
    "evidence_sha256": pl.String,
}

# This is deliberately a completed-bout history rather than a model projection.
# The per-row classification is carried with the table so later feature work has
# a machine-readable boundary between pre-fight context and post-fight facts.
_HISTORICAL_FIELD_CLASSIFICATION = json.dumps(
    {
        "canonical_bout_id": "identity or chronology",
        "fight_date": "identity or chronology",
        "event_context": "prediction-time-safe bout context",
        "event_context_source": "identity or chronology",
        "event_identifier": "identity or chronology",
        "within_event_order_key": "identity or chronology",
        "global_chronological_key": "identity or chronology",
        "chronology_granularity": "identity or chronology",
        "ordering_confidence": "identity or chronology",
        "same_date_history_policy": "identity or chronology",
        "canonical_fighter_a_id": "identity or chronology",
        "canonical_fighter_b_id": "identity or chronology",
        "fighter_orientation": "identity or chronology",
        "source_presence": "identity or chronology",
        "canonical_scheduled_format": "prediction-time-safe bout context",
        "scheduled_rounds": "prediction-time-safe bout context",
        "canonical_outcome": "post-bout label",
        "winner_canonical_fighter_id": "post-bout label",
        "loser_canonical_fighter_id": "post-bout label",
        "is_no_contest": "post-bout label",
        "is_draw": "post-bout label",
        "canonical_finish_method": "post-bout descriptive field",
        "canonical_finish_round": "post-bout descriptive field",
        "canonical_finish_time": "post-bout descriptive field",
        "outcome_authority_id": "identity or chronology",
        "authority_ledger_identifier": "identity or chronology",
        "decision_reference": "identity or chronology",
        "reconciliation_evidence_sha256": "identity or chronology",
        "field_classification": "identity or chronology",
    },
    sort_keys=True,
    separators=(",", ":"),
)

_HISTORICAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "canonical_bout_id": pl.String,
    "fight_date": pl.Date,
    "event_context": pl.String,
    "event_context_source": pl.String,
    "event_identifier": pl.String,
    "within_event_order_key": pl.String,
    "global_chronological_key": pl.String,
    "chronology_granularity": pl.String,
    "ordering_confidence": pl.String,
    "same_date_history_policy": pl.String,
    "canonical_fighter_a_id": pl.String,
    "canonical_fighter_b_id": pl.String,
    "fighter_orientation": pl.String,
    "source_presence": pl.String,
    "canonical_scheduled_format": pl.String,
    "scheduled_rounds": pl.Int64,
    "canonical_outcome": pl.String,
    "winner_canonical_fighter_id": pl.String,
    "loser_canonical_fighter_id": pl.String,
    "is_no_contest": pl.Boolean,
    "is_draw": pl.Boolean,
    "canonical_finish_method": pl.String,
    "canonical_finish_round": pl.Int64,
    "canonical_finish_time": pl.String,
    "outcome_authority_id": pl.String,
    "authority_ledger_identifier": pl.String,
    "decision_reference": pl.String,
    "reconciliation_evidence_sha256": pl.String,
    "field_classification": pl.String,
}

_PREFIGHT_CUTOFF_POLICY = "strict_fight_date_lt_target_date_v1"
_PREFIGHT_FEATURE_POLICIES = {
    "cutoff_policy": _PREFIGHT_CUTOFF_POLICY,
    "career_win_loss_rate_denominator": "prior_decisive_bouts_wins_plus_losses",
    "recent_five_win_rate_denominator": "recent_five_decisive_bouts_wins_plus_losses",
    "finish_win_rate_denominator": "prior_wins",
    "zero_denominator_rates": "null",
    "streak_policy": {
        "win": "consecutive trailing wins; draws and no-contests reset",
        "loss": "consecutive trailing losses; draws and no-contests reset",
        "unbeaten": "consecutive trailing wins_or_draws; no-contests reset",
        "winless": "consecutive trailing losses_or_draws; no-contests reset",
    },
}

_PREFIGHT_SCHEMA: dict[str, type[pl.DataType]] = {
    "canonical_bout_id": pl.String,
    "canonical_fighter_id": pl.String,
    "opponent_canonical_fighter_id": pl.String,
    "target_fight_date": pl.Date,
    "fighter_slot": pl.String,
    "history_cutoff_date": pl.Date,
    "cutoff_policy_id": pl.String,
    "cold_start": pl.Boolean,
    "prior_bouts": pl.Int64,
    "prior_wins": pl.Int64,
    "prior_losses": pl.Int64,
    "prior_draws": pl.Int64,
    "prior_no_contests": pl.Int64,
    "prior_decisive_bouts": pl.Int64,
    "prior_win_rate": pl.Float64,
    "prior_loss_rate": pl.Float64,
    "days_since_previous_bout": pl.Int64,
    "prior_bouts_180_days": pl.Int64,
    "prior_bouts_365_days": pl.Int64,
    "prior_bouts_730_days": pl.Int64,
    "recent_five_observed_bouts": pl.Int64,
    "recent_five_wins": pl.Int64,
    "recent_five_losses": pl.Int64,
    "recent_five_draws": pl.Int64,
    "recent_five_no_contests": pl.Int64,
    "recent_five_win_rate": pl.Float64,
    "current_win_streak": pl.Int64,
    "current_loss_streak": pl.Int64,
    "current_unbeaten_streak": pl.Int64,
    "current_winless_streak": pl.Int64,
    "prior_knockout_tko_wins": pl.Int64,
    "prior_submission_wins": pl.Int64,
    "prior_decision_wins": pl.Int64,
    "prior_other_finish_wins": pl.Int64,
    "prior_finish_win_rate": pl.Float64,
    "snapshot_evidence_sha256": pl.String,
}

_PERFORMANCE_METRICS = (
    "knockdowns",
    "significant_strikes_landed",
    "significant_strikes_attempted",
    "total_strikes_landed",
    "total_strikes_attempted",
    "takedowns_landed",
    "takedowns_attempted",
    "submission_attempts",
    "reversals",
    "control_seconds",
)
_PERFORMANCE_POLICY_ID = "m3.phase3b2a.raw_stats_field_reconciliation.v1"
_PERFORMANCE_SCHEMA: dict[str, type[pl.DataType]] = {
    "canonical_bout_id": pl.String,
    "canonical_fighter_id": pl.String,
    "opponent_canonical_fighter_id": pl.String,
    "fight_date": pl.Date,
    "fighter_slot": pl.String,
    "source_presence": pl.String,
    "ultimate_source_row_id": pl.String,
    "ufc_datalab_source_row_id": pl.String,
    "source_side": pl.String,
    "contributing_sources": pl.String,
    "reconciliation_policy_id": pl.String,
    "field_classification": pl.String,
    "performance_evidence_sha256": pl.String,
}
for _metric in _PERFORMANCE_METRICS:
    _PERFORMANCE_SCHEMA.update(
        {
            _metric: pl.Int64,
            f"ultimate_{_metric}": pl.Int64,
            f"ufc_datalab_{_metric}": pl.Int64,
            f"{_metric}_available": pl.Boolean,
            f"{_metric}_reconciliation_status": pl.String,
        }
    )

_PREFIGHT_PERFORMANCE_POLICY_ID = "m3.phase3b2b.strict_prior_performance.v1"
_PREFIGHT_PERFORMANCE_SCHEMA: dict[str, type[pl.DataType]] = {
    "canonical_bout_id": pl.String,
    "canonical_fighter_id": pl.String,
    "opponent_canonical_fighter_id": pl.String,
    "target_fight_date": pl.Date,
    "cutoff_policy_id": pl.String,
    "feature_policy_id": pl.String,
    "cold_start": pl.Boolean,
    "eligible_prior_performance_bouts": pl.Int64,
    "snapshot_evidence_sha256": pl.String,
}
for _metric in _PERFORMANCE_METRICS:
    for _prefix in ("career", "recent_3", "recent_5", "days_365", "days_730"):
        _PREFIGHT_PERFORMANCE_SCHEMA.update(
            {
                f"{_prefix}_{_metric}_observed_count": pl.Int64,
                f"{_prefix}_{_metric}_missing_count": pl.Int64,
                f"{_prefix}_{_metric}_sum": pl.Int64,
                f"{_prefix}_{_metric}_mean": pl.Float64,
            }
        )
for _rate in ("significant_strike_accuracy", "total_strike_accuracy", "takedown_accuracy"):
    _PREFIGHT_PERFORMANCE_SCHEMA[f"career_{_rate}"] = pl.Float64
for _metric in (
    "knockdowns",
    "significant_strikes_landed",
    "total_strikes_landed",
    "takedowns_landed",
    "takedowns_attempted",
    "submission_attempts",
    "control_seconds",
):
    _PREFIGHT_PERFORMANCE_SCHEMA[f"career_opponent_{_metric}_observed_count"] = pl.Int64
    _PREFIGHT_PERFORMANCE_SCHEMA[f"career_opponent_{_metric}_missing_count"] = pl.Int64
    _PREFIGHT_PERFORMANCE_SCHEMA[f"career_{_metric}_absorbed_sum"] = pl.Int64
    _PREFIGHT_PERFORMANCE_SCHEMA[f"career_{_metric}_absorbed_per_observed_bout"] = pl.Float64
for _name in (
    "significant_strike_defense",
    "takedown_defense",
    "significant_strikes_landed_per_minute",
    "total_strikes_landed_per_minute",
    "takedown_attempts_per_15_minutes",
    "submission_attempts_per_15_minutes",
    "control_seconds_per_fight_minute",
):
    _PREFIGHT_PERFORMANCE_SCHEMA[f"career_{_name}"] = pl.Float64
_PREFIGHT_PERFORMANCE_SCHEMA["career_valid_duration_observed_count"] = pl.Int64
_PREFIGHT_PERFORMANCE_SCHEMA["career_excluded_duration_prior_bout_count"] = pl.Int64

_PAIRWISE_ORIENTATION_POLICY_ID = "m3.phase3c1.canonical_historical_fighter_a_b.v1"
_PAIRWISE_FEATURE_SCHEMA_VERSION = "m3.phase3c1.pairwise_registry.v1"
_MODEL_READY_SCHEMA_VERSION = "m3.phase3c2.binary_projection.v1"
_MODEL_READY_PROJECTION_POLICY_ID = "m3.phase3c2.decisions_only_binary_target.v1"
# This is deliberately small and reviewed: it is not an automatic numeric-column projection.
_PAIRWISE_FEATURE_REGISTRY: tuple[dict[str, str], ...] = (
    *(
        {
            "source_artifact": "m3_prefight_fighter_history.parquet",
            "source_column": name,
            "description": "pre-fight historical fighter context",
            "data_type": dtype,
            "null_policy": "preserve_null_with_fighter_specific_indicator",
            "transformation_policy": "a_b_and_signed_difference",
            "swap_behavior": "swap_values_negate_difference",
        }
        for name, dtype in (
            ("prior_bouts", "int"),
            ("prior_decisive_bouts", "int"),
            ("prior_win_rate", "float"),
            ("prior_loss_rate", "float"),
            ("days_since_previous_bout", "int"),
            ("prior_bouts_365_days", "int"),
            ("recent_five_win_rate", "float"),
            ("current_win_streak", "int"),
            ("current_loss_streak", "int"),
            ("prior_finish_win_rate", "float"),
            ("cold_start", "bool"),
        )
    ),
    *(
        {
            "source_artifact": "m3_prefight_performance_history.parquet",
            "source_column": name,
            "description": "strictly-prior aggregated performance history",
            "data_type": dtype,
            "null_policy": "preserve_null_with_fighter_specific_indicator",
            "transformation_policy": "a_b_and_signed_difference",
            "swap_behavior": "swap_values_negate_difference",
        }
        for name, dtype in (
            ("eligible_prior_performance_bouts", "int"),
            ("career_significant_strikes_landed_mean", "float"),
            ("career_significant_strike_accuracy", "float"),
            ("career_total_strike_accuracy", "float"),
            ("career_takedowns_attempted_mean", "float"),
            ("career_takedown_accuracy", "float"),
            ("career_submission_attempts_mean", "float"),
            ("career_knockdowns_mean", "float"),
            ("career_control_seconds_mean", "float"),
            ("career_significant_strike_defense", "float"),
            ("career_takedown_defense", "float"),
            ("career_significant_strikes_landed_per_minute", "float"),
            ("career_takedown_attempts_per_15_minutes", "float"),
            ("career_valid_duration_observed_count", "int"),
            ("career_significant_strikes_landed_observed_count", "int"),
        )
    ),
)

_PROVENANCE_SCHEMA: dict[str, type[pl.DataType]] = {
    "output_artifact": pl.String,
    "output_schema_version": pl.String,
    "output_row_key": pl.String,
    "lineage_type": pl.String,
    "upstream_artifact": pl.String,
    "upstream_row_key": pl.String,
    "source_dataset": pl.String,
    "source_schema_version": pl.String,
    "source_row_id": pl.String,
    "raw_artifact_path": pl.String,
    "raw_artifact_sha256": pl.String,
    "ingestion_reference": pl.String,
    "transformation_schema_version": pl.String,
    "authority_id": pl.String,
    "authority_ledger_identifier": pl.String,
    "authority_decision_reference": pl.String,
    "deterministic_rule_id": pl.String,
    "evidence_sha256": pl.String,
}

_PUBLISHED_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("m3_semantic_bout_groups.parquet", "semantic_groups"),
    ("m3_source_bout_crosswalk.parquet", "crosswalk"),
    ("m3_canonical_fighters.parquet", "m3_fighters"),
    ("m3_canonical_fighter_aliases.parquet", "m3_aliases"),
    ("m3_taxonomy_authorities.parquet", "m3_taxonomy"),
    ("m3_bout_reconciliation.parquet", "reconciliation"),
    ("m3_reviewed_exclusions.parquet", "reviewed_exclusions"),
    ("m3_duplicate_collapses.parquet", "duplicate_collapses"),
    ("m3_canonical_historical_bouts.parquet", "historical_bouts"),
    ("m3_prefight_fighter_history.parquet", "prefight_fighter_history"),
    ("m3_fighter_bout_performance.parquet", "fighter_bout_performance"),
    ("m3_prefight_performance_history.parquet", "prefight_performance_history"),
    ("m3_prefight_pairwise_features.parquet", "pairwise_features"),
    ("m3_model_ready_binary.parquet", "model_ready_binary"),
)


def load_authority_index(v6_dir: Path) -> AuthorityIndex:
    """Index the two immutable approved-authority ledgers by their exact review IDs."""
    sources = (
        (V6_LEDGER_IDENTIFIER, v6_dir / "m3_imported_decisions.jsonl", "review_id"),
        (
            SUPPLEMENTAL_LEDGER_IDENTIFIER,
            v6_dir / "authority-migration-v1/m3_supplemental_legacy_authorities.jsonl",
            "legacy_review_id",
        ),
    )
    records: list[AuthorityRecord] = []
    for ledger_identifier, path, id_column in sources:
        for row in _jsonl(path):
            authority_id = row.get(id_column, "")
            if not authority_id:
                raise ValueError(f"authority ledger row has no {id_column}: {path}")
            records.append(AuthorityRecord(authority_id, ledger_identifier, row))
    return AuthorityIndex(tuple(records))


def identity_context_key(raw_name: str, division_context: str) -> str:
    """Use the approved Bruno homonym rule; all other identities are exact normalized names."""
    # This is deliberately an explicit approved alias pair, not a general
    # punctuation-insensitive identity merge.
    roldan_alias = "".join(raw_name.casefold().split()).replace("-", "").replace("'", "")
    if roldan_alias == "roldansangchaan":
        return "roldan sangcha an"
    normalized = normalize_fighter_alias(raw_name).normalized_value
    if normalized == "bruno silva":
        context = division_context.casefold()
        division = next(
            (value for value in ("flyweight", "middleweight", "bantamweight") if value in context),
            "unresolved-division-context",
        )
        return f"bruno silva|{division}"
    return normalized


def taxonomy_authority_coverage(
    *, ultimate_csv: Path, datalab_csv: Path, v6_dir: Path
) -> tuple[TaxonomyAuthority, ...]:
    """Classify every immutable taxonomy authority against retained raw fields."""
    authority_index = load_authority_index(v6_dir)
    source_values = _retained_taxonomy_values(ultimate_csv=ultimate_csv, datalab_csv=datalab_csv)
    candidates: list[TaxonomyAuthority] = []
    for record in authority_index.records:
        if not _is_taxonomy_authority(record):
            continue
        source_name, field_name, raw_value, canonical_value, is_null_policy = _taxonomy_scope(
            record
        )
        schema_version = "completed-bouts-v1" if source_name == "ultimate" else "stats-raw-v1"
        active = _is_active_taxonomy_authority(record)
        applicable = active and _taxonomy_value_is_retained(
            source_values, source_name, field_name, raw_value, is_null_policy
        )
        candidates.append(
            TaxonomyAuthority(
                authority_id=record.authority_id,
                ledger_identifier=record.ledger_identifier,
                source_name=source_name,
                source_schema_version=schema_version,
                field_name=field_name,
                raw_value=raw_value,
                canonical_value=canonical_value,
                is_null_policy=is_null_policy,
                decision_reference=record.authority_id,
                decision_action=record.payload.get("reviewer_decision", "approve"),
                category=record.payload["category"],
                source_evidence_sha256=record.payload["source_evidence_sha256"],
                classification=(
                    "active_and_applicable"
                    if applicable
                    else "active_but_not_applicable_to_retained_approved_source_fields"
                    if active
                    else "retired_or_deferred"
                ),
            )
        )
    return _classify_taxonomy_duplicates(candidates)


def _retained_taxonomy_values(
    *, ultimate_csv: Path, datalab_csv: Path
) -> dict[tuple[str, str], set[str]]:
    ultimate = list(csv.DictReader(ultimate_csv.open(encoding="utf-8-sig", newline="")))
    datalab = list(
        csv.DictReader(datalab_csv.open(encoding="utf-8-sig", newline=""), delimiter=";")
    )
    return {
        ("ultimate", "finish"): {row["finish"] for row in ultimate},
        ("ultimate", "weight_class"): {row["weight_class"] for row in ultimate},
        ("ultimate", "country"): {row["country"] for row in ultimate},
        ("ultimate", "stance"): {
            value for row in ultimate for value in (row["R_Stance"], row["B_Stance"])
        },
        ("ufc-datalab", "method"): {row["method"] for row in datalab},
        ("ufc-datalab", "bout_type"): {row["bout_type"] for row in datalab},
    }


def _is_taxonomy_authority(record: AuthorityRecord) -> bool:
    return record.payload.get("category", "").startswith("taxonomy.") and (
        record.ledger_identifier == V6_LEDGER_IDENTIFIER
        or record.payload.get("authority_kind") == "taxonomy"
    )


def _is_active_taxonomy_authority(record: AuthorityRecord) -> bool:
    if record.ledger_identifier == SUPPLEMENTAL_LEDGER_IDENTIFIER:
        return record.payload.get("record_type") == "m3_supplemental_legacy_authority"
    return record.payload.get("reviewer_decision") in {
        "approve_corrected_mapping",
        "preserve_null",
    }


def _taxonomy_scope(record: AuthorityRecord) -> tuple[str, str, str | None, str | None, bool]:
    source_value = record.payload["source_values"]
    source_name, raw_value = _single_taxonomy_source_value(source_value)
    category = record.payload["category"]
    is_null_policy = category == "taxonomy.missing_stance_policy"
    if is_null_policy:
        return "ultimate", "stance", None, None, True
    if "country_whitespace" in category:
        field_name = "country"
    elif "division" in category:
        field_name = "weight_class" if source_name == "ultimate" else "bout_type"
    elif "stance" in category:
        field_name = "stance"
    elif "finish" in category:
        field_name = "finish" if source_name == "ultimate" else "method"
    else:
        raise ValueError(f"unsupported taxonomy authority category: {category}")
    return source_name, field_name, raw_value, _canonical_taxonomy_value(record), False


def _single_taxonomy_source_value(value: str) -> tuple[str, str]:
    if " || " in value:
        # Only the reviewed missing-stance policy spans sources.  Its materialized
        # scope is Ultimate because UFC-DataLab retains no stance field.
        value = value.split(" || ", maxsplit=1)[0]
    source_name, raw_value = value.split(": ", maxsplit=1)
    return source_name, raw_value


def _canonical_taxonomy_value(record: AuthorityRecord) -> str:
    proposed = record.payload["proposed_canonical_value_or_action"]
    return proposed.removeprefix("review exact taxonomy mapping to: ")


def _taxonomy_value_is_retained(
    source_values: dict[tuple[str, str], set[str]],
    source_name: str,
    field_name: str,
    raw_value: str | None,
    is_null_policy: bool,
) -> bool:
    values = source_values.get((source_name, field_name))
    if values is None:
        return False
    return "" in values if is_null_policy else raw_value in values


def _classify_taxonomy_duplicates(
    candidates: list[TaxonomyAuthority],
) -> tuple[TaxonomyAuthority, ...]:
    grouped: defaultdict[tuple[str, str, str, str | None], list[TaxonomyAuthority]] = defaultdict(
        list
    )
    for candidate in candidates:
        if candidate.classification == "active_and_applicable":
            grouped[
                (
                    candidate.source_name,
                    candidate.source_schema_version,
                    candidate.field_name,
                    candidate.raw_value,
                )
            ].append(candidate)
    classified: list[TaxonomyAuthority] = []
    for candidate in candidates:
        matches = grouped.get(
            (
                candidate.source_name,
                candidate.source_schema_version,
                candidate.field_name,
                candidate.raw_value,
            ),
            [],
        )
        if len(matches) < 2:
            classified.append(candidate)
            continue
        preferred = sorted(
            matches,
            key=lambda item: (item.ledger_identifier != V6_LEDGER_IDENTIFIER, item.authority_id),
        )[0]
        if candidate == preferred:
            classified.append(candidate)
        elif candidate.canonical_value == preferred.canonical_value:
            classified.append(
                _replace_taxonomy_classification(
                    candidate, "duplicate_of_another_immutable_authority"
                )
            )
        else:
            classified.append(_replace_taxonomy_classification(candidate, "superseded"))
    return tuple(sorted(classified, key=lambda item: item.authority_id))


def _replace_taxonomy_classification(
    authority: TaxonomyAuthority, classification: str
) -> TaxonomyAuthority:
    return TaxonomyAuthority(
        authority_id=authority.authority_id,
        ledger_identifier=authority.ledger_identifier,
        source_name=authority.source_name,
        source_schema_version=authority.source_schema_version,
        field_name=authority.field_name,
        raw_value=authority.raw_value,
        canonical_value=authority.canonical_value,
        is_null_policy=authority.is_null_policy,
        decision_reference=authority.decision_reference,
        decision_action=authority.decision_action,
        category=authority.category,
        source_evidence_sha256=authority.source_evidence_sha256,
        classification=classification,
    )


def _outcome_authorities(index: AuthorityIndex) -> dict[tuple[str, str], AuthorityRecord]:
    authorities: dict[tuple[str, str], AuthorityRecord] = {}
    for record in index.records:
        if not record.payload.get("category", "").startswith("outcome."):
            continue
        action = record.payload.get("reviewer_decision")
        if action not in {"confirm_overturned", "select_ufc_datalab"}:
            raise ValueError(f"invalid reviewed outcome action: {record.authority_id}")
        ultimate_row = _source_row_from_evidence(record.payload["source_values"], "ufc-master.csv")
        datalab_row = _source_row_from_evidence(record.payload["source_values"], "stats_raw.csv")
        key = (ultimate_row, datalab_row)
        if key in authorities:
            raise ValueError(f"duplicate reviewed outcome authority: {record.authority_id}")
        authorities[key] = record
    if len(authorities) != 14:
        raise ValueError(f"expected 14 reviewed outcome authorities, found {len(authorities)}")
    return authorities


def _source_row_from_evidence(source_values: str, source_file: str) -> str:
    marker = f"{source_file}:row-"
    if marker not in source_values:
        raise ValueError(f"review evidence lacks {source_file}: {source_values}")
    return "row-" + source_values.split(marker, maxsplit=1)[1].split()[0]


def _source_outcome(
    raw_outcome: str,
    red_fighter_id: str,
    blue_fighter_id: str,
) -> SourceOutcome:
    normalized = raw_outcome.strip().casefold().replace(" ", "_")
    if normalized in {"red", "red_win"}:
        return SourceOutcome("win", red_fighter_id, blue_fighter_id, False, False)
    if normalized in {"blue", "blue_win"}:
        return SourceOutcome("win", blue_fighter_id, red_fighter_id, False, False)
    if normalized in {"draw", "draws"}:
        return SourceOutcome("draw", None, None, False, True)
    if normalized in {"no_contest", "nc", "overturned"}:
        return SourceOutcome("no_contest", None, None, True, False)
    raise ValueError(f"unrecognized source outcome: {raw_outcome}")


def _outcomes_agree(left: SourceOutcome, right: SourceOutcome) -> bool:
    return (
        left.outcome,
        left.winner_fighter_id,
        left.loser_fighter_id,
        left.is_no_contest,
        left.is_draw,
    ) == (
        right.outcome,
        right.winner_fighter_id,
        right.loser_fighter_id,
        right.is_no_contest,
        right.is_draw,
    )


def _reconciliation_evidence_hash(row: dict[str, object]) -> str:
    payload = {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in sorted(row.items())
        if key != "evidence_sha256"
    }
    return content_sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def _reconciliation_rows(
    *,
    crosswalk: pl.DataFrame,
    ultimate_by_row: dict[str, dict[str, str]],
    datalab_by_row: dict[str, dict[str, str]],
    outcome_authorities: dict[tuple[str, str], AuthorityRecord],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    used_authorities: set[str] = set()
    for group_key, group in crosswalk.group_by("canonical_bout_id", maintain_order=True):
        canonical_bout_id = group_key[0] if isinstance(group_key, tuple) else group_key
        records = group.sort("source_name").to_dicts()
        if len(records) not in {1, 2}:
            raise ValueError(
                f"invalid retained source count for {canonical_bout_id}: {len(records)}"
            )
        references = {str(record["source_name"]): record for record in records}
        ultimate_ref = references.get("ultimate")
        datalab_ref = references.get("ufc-datalab")
        anchor = datalab_ref or ultimate_ref
        if anchor is None:
            raise ValueError(f"semantic group has no source reference: {canonical_bout_id}")
        fighter_a = str(anchor["canonical_fighter_a_id"])
        fighter_b = str(anchor["canonical_fighter_b_id"])
        ultimate_outcome: SourceOutcome | None = None
        datalab_outcome: SourceOutcome | None = None
        ultimate_row: dict[str, str] | None = None
        datalab_row: dict[str, str] | None = None
        ultimate_source_row_id = str(ultimate_ref["source_row_id"]) if ultimate_ref else None
        datalab_source_row_id = str(datalab_ref["source_row_id"]) if datalab_ref else None
        if ultimate_ref:
            ultimate_row = ultimate_by_row[str(ultimate_ref["source_row_id"])]
            ultimate_outcome = _source_outcome(
                ultimate_row["Winner"],
                _fighter(ultimate_row["R_fighter"], ultimate_row["weight_class"])[0],
                _fighter(ultimate_row["B_fighter"], ultimate_row["weight_class"])[0],
            )
        if datalab_ref:
            datalab_row = datalab_by_row[str(datalab_ref["source_row_id"])]
            datalab_outcome = _source_outcome(
                datalab_row["fight_outcome"],
                _fighter(datalab_row["red_fighter_name"], datalab_row["bout_type"])[0],
                _fighter(datalab_row["blue_fighter_name"], datalab_row["bout_type"])[0],
            )
        authority: AuthorityRecord | None = None
        if ultimate_ref and datalab_ref:
            if ultimate_source_row_id is None or datalab_source_row_id is None:
                raise ValueError(f"dual-source group has missing source IDs: {canonical_bout_id}")
            authority = outcome_authorities.get((ultimate_source_row_id, datalab_source_row_id))
        canonical_outcome: SourceOutcome
        if authority is not None:
            used_authorities.add(authority.authority_id)
            if authority.payload["reviewer_decision"] == "confirm_overturned":
                canonical_outcome = SourceOutcome("no_contest", None, None, True, False)
                status = "canonical_no_contest"
            else:
                if datalab_outcome is None:
                    raise ValueError(f"reviewed outcome lacks UFC-DataLab row: {canonical_bout_id}")
                canonical_outcome = datalab_outcome
                status = "reviewed_override"
        elif ultimate_outcome is not None and datalab_outcome is not None:
            if not _outcomes_agree(ultimate_outcome, datalab_outcome):
                raise ValueError(
                    "unresolved source conflict for "
                    f"{canonical_bout_id}: {ultimate_source_row_id} / {datalab_source_row_id}"
                )
            canonical_outcome = datalab_outcome
            status = "source_agreement"
        else:
            single_source_outcome = ultimate_outcome or datalab_outcome
            if single_source_outcome is None:
                raise ValueError(f"missing source outcome for {canonical_bout_id}")
            canonical_outcome = single_source_outcome
            status = "single_source_retained"
        if canonical_outcome.winner_fighter_id not in {None, fighter_a, fighter_b}:
            raise ValueError(f"outcome winner is outside semantic group: {canonical_bout_id}")
        if canonical_outcome.loser_fighter_id not in {None, fighter_a, fighter_b}:
            raise ValueError(f"outcome loser is outside semantic group: {canonical_bout_id}")
        if datalab_row is not None:
            finish_method = datalab_row["method"]
            finish_round = int(datalab_row["round"]) if datalab_row["round"].isdecimal() else None
            finish_time = datalab_row["time"]
            scheduled_format = datalab_row["time_format"]
            fight_date = _iso(datalab_row["event_date"])
        elif ultimate_row is not None:
            finish_method = ultimate_row["finish"]
            finish_round = _int(ultimate_row["finish_round"])
            finish_time = ultimate_row["finish_round_time"]
            scheduled_format = ultimate_row["no_of_rounds"]
            fight_date = ultimate_row["date"]
        else:
            raise ValueError(f"missing retained source row for {canonical_bout_id}")
        row: dict[str, object] = {
            "canonical_bout_id": str(canonical_bout_id),
            "fight_date": fight_date,
            "canonical_fighter_a_id": fighter_a,
            "canonical_fighter_b_id": fighter_b,
            "fighter_orientation": "canonical_fighter_a_id_ascending",
            "source_presence": (
                "dual_source"
                if ultimate_ref and datalab_ref
                else "ultimate_only"
                if ultimate_ref
                else "ufc_datalab_only"
            ),
            "ultimate_source_row_id": ultimate_source_row_id,
            "ufc_datalab_source_row_id": datalab_source_row_id,
            "ultimate_outcome_raw": ultimate_row["Winner"] if ultimate_row else None,
            "ufc_datalab_outcome_raw": datalab_row["fight_outcome"] if datalab_row else None,
            "canonical_outcome": canonical_outcome.outcome,
            "winner_canonical_fighter_id": canonical_outcome.winner_fighter_id,
            "loser_canonical_fighter_id": canonical_outcome.loser_fighter_id,
            "is_no_contest": canonical_outcome.is_no_contest,
            "is_draw": canonical_outcome.is_draw,
            "canonical_finish_method": (
                "Overturned" if canonical_outcome.is_no_contest else finish_method
            ),
            "canonical_finish_round": (None if canonical_outcome.is_no_contest else finish_round),
            "canonical_finish_time": (None if canonical_outcome.is_no_contest else finish_time),
            "canonical_scheduled_format": scheduled_format,
            "reconciliation_status": status,
            "outcome_authority_id": authority.authority_id if authority else None,
            "authority_ledger_identifier": authority.ledger_identifier if authority else None,
            "decision_reference": authority.authority_id if authority else None,
            "evidence_sha256": "",
        }
        row["fight_date"] = date.fromisoformat(str(row["fight_date"]))
        row["evidence_sha256"] = _reconciliation_evidence_hash(row)
        rows.append(row)
    if used_authorities != {record.authority_id for record in outcome_authorities.values()}:
        missing = {
            record.authority_id for record in outcome_authorities.values()
        } - used_authorities
        raise ValueError(f"reviewed outcome authorities not applied: {sorted(missing)}")
    return rows


def _reviewed_exclusion_rows(
    index: AuthorityIndex, crosswalk: pl.DataFrame
) -> list[dict[str, object]]:
    exclusions: list[dict[str, object]] = []
    expected = {"row-5170", "row-5658"}
    for record in index.records:
        if record.payload.get("category") != "bout_format.unresolved_cross_source_match":
            continue
        if record.payload.get("reviewer_decision") != "exclude_affected_record":
            raise ValueError(f"invalid exclusion action: {record.authority_id}")
        row_id = _source_row_from_evidence(record.payload["source_values"], "ufc-master.csv")
        if row_id not in expected:
            raise ValueError(f"unexpected reviewed exclusion row: {row_id}")
        if crosswalk.filter(
            (pl.col("source_name") == "ultimate") & (pl.col("source_row_id") == row_id)
        ).height:
            raise ValueError(f"excluded row leaked into crosswalk: {row_id}")
        row: dict[str, object] = {
            "source_name": "ultimate",
            "source_schema_version": "completed-bouts-v1",
            "source_row_id": row_id,
            "exclusion_reason_code": "unresolved_cross_source_match",
            "exclusion_reason": record.payload["representative_evidence"],
            "authority_id": record.authority_id,
            "ledger_identifier": record.ledger_identifier,
            "decision_reference": record.authority_id,
            "source_evidence_sha256": record.payload["source_evidence_sha256"],
            "evidence_sha256": "",
        }
        row["evidence_sha256"] = _reconciliation_evidence_hash(row)
        exclusions.append(row)
    if {str(row["source_row_id"]) for row in exclusions} != expected:
        raise ValueError("reviewed exclusions do not exactly match row-5170 and row-5658")
    return sorted(exclusions, key=lambda row: str(row["source_row_id"]))


def _duplicate_collapse_rows(
    collapsed: list[dict[str, str]], crosswalk: pl.DataFrame
) -> list[dict[str, object]]:
    if len(collapsed) != 1 or collapsed[0]["duplicate_source_row_id"] != "row-8604":
        raise ValueError("expected exactly the reviewed duplicate collapse row-8604")
    collapse = collapsed[0]
    retained = crosswalk.filter(
        (pl.col("source_name") == "ufc-datalab")
        & (pl.col("source_row_id") == collapse["retained_source_row_id"])
    )
    if retained.height != 1:
        raise ValueError(f"duplicate retained source row is not traceable: {collapse}")
    row: dict[str, object] = {
        "source_name": "ufc-datalab",
        "source_schema_version": "stats-raw-v1",
        "duplicate_source_row_id": collapse["duplicate_source_row_id"],
        "retained_source_row_id": collapse["retained_source_row_id"],
        "canonical_bout_id": retained.item(0, "canonical_bout_id"),
        "duplicate_reason": "duplicate_normalized_candidate_key",
        "compared_fighter_a_normalized": collapse["fighter_a_normalized"],
        "compared_fighter_b_normalized": collapse["fighter_b_normalized"],
        "compared_fight_date": collapse["fight_date"],
        "lineage_type": "deterministic_rule",
        "authority_id": None,
        "ledger_identifier": None,
        "deterministic_rule_id": "m3.phase1.normalized_candidate_key.v1",
        "evidence_sha256": "",
    }
    row["evidence_sha256"] = _reconciliation_evidence_hash(row)
    return [row]


def _scheduled_rounds(value: object) -> int | None:
    """Extract only the explicitly supplied scheduled-round count."""
    text = str(value or "").strip()
    if text.isdecimal():
        return int(text)
    # UFC-DataLab's approved raw value is e.g. ``3 Rnd (5-5-5)``.
    first = text.split(maxsplit=1)[0] if text else ""
    return int(first) if first.isdecimal() else None


def _canonical_historical_bout_rows(
    *,
    reconciliation: pl.DataFrame,
    ultimate_by_row: dict[str, dict[str, str]],
    datalab_by_row: dict[str, dict[str, str]],
    canonical_fighter_ids: set[str],
) -> list[dict[str, object]]:
    """Project reconciled bouts into conservative, source-order-independent history.

    No raw outcome is consulted here: Phase 2B supplies every outcome label.
    Exact bout order inside a dated event is not present in the approved sources,
    therefore every row explicitly blocks same-date prior-history use.
    """
    rows: list[dict[str, object]] = []
    for record in reconciliation.to_dicts():
        datalab_row_id = record["ufc_datalab_source_row_id"]
        ultimate_row_id = record["ultimate_source_row_id"]
        if datalab_row_id is not None:
            source_row = datalab_by_row[str(datalab_row_id)]
            source_pairs = (
                (
                    _fighter(source_row["red_fighter_name"], source_row["bout_type"])[0],
                    _canonical_fighter(source_row["red_fighter_name"], source_row["bout_type"])[0],
                ),
                (
                    _fighter(source_row["blue_fighter_name"], source_row["bout_type"])[0],
                    _canonical_fighter(source_row["blue_fighter_name"], source_row["bout_type"])[0],
                ),
            )
            event_context = source_row["event_name"].strip()
            event_context_source = "ufc_datalab_event_name"
        elif ultimate_row_id is not None:
            source_row = ultimate_by_row[str(ultimate_row_id)]
            source_pairs = (
                (
                    _fighter(source_row["R_fighter"], source_row["weight_class"])[0],
                    _canonical_fighter(source_row["R_fighter"], source_row["weight_class"])[0],
                ),
                (
                    _fighter(source_row["B_fighter"], source_row["weight_class"])[0],
                    _canonical_fighter(source_row["B_fighter"], source_row["weight_class"])[0],
                ),
            )
            # The Ultimate source has no event ID. Location is retained only as
            # a weak context label, never as evidence of an exact order.
            event_context = source_row["location"].strip()
            event_context_source = "ultimate_location_only"
        else:
            raise ValueError("reconciliation row has no source row")
        canonical_by_phase1_id = dict(source_pairs)
        fighter_ids = sorted(canonical_by_phase1_id.values())
        if len(fighter_ids) != 2 or fighter_ids[0] == fighter_ids[1]:
            raise ValueError(f"invalid canonical fighter projection: {record['canonical_bout_id']}")
        if not set(fighter_ids).issubset(canonical_fighter_ids):
            raise ValueError(f"historical fighter does not resolve: {record['canonical_bout_id']}")
        winner = record["winner_canonical_fighter_id"]
        loser = record["loser_canonical_fighter_id"]
        canonical_winner = canonical_by_phase1_id.get(str(winner)) if winner is not None else None
        canonical_loser = canonical_by_phase1_id.get(str(loser)) if loser is not None else None
        if (winner is None) != (canonical_winner is None) or (loser is None) != (
            canonical_loser is None
        ):
            raise ValueError(
                f"outcome fighter cannot be canonically projected: {record['canonical_bout_id']}"
            )
        is_no_contest = bool(record["is_no_contest"])
        is_draw = bool(record["is_draw"])
        if (is_no_contest or is_draw) and (
            canonical_winner is not None or canonical_loser is not None
        ):
            raise ValueError(
                f"non-decisive historical outcome has a winner: {record['canonical_bout_id']}"
            )
        fight_date = cast(date, record["fight_date"])
        event_identifier = content_sha256(
            f"{fight_date.isoformat()}|{event_context_source}|{event_context}".encode()
        )
        bout_id = str(record["canonical_bout_id"])
        row: dict[str, object] = {
            "canonical_bout_id": bout_id,
            "fight_date": fight_date,
            "event_context": event_context,
            "event_context_source": event_context_source,
            "event_identifier": event_identifier,
            "within_event_order_key": bout_id,
            "global_chronological_key": f"{fight_date.isoformat()}|{event_identifier}|{bout_id}",
            "chronology_granularity": "date_only_with_event_context",
            "ordering_confidence": "ambiguous_same_date",
            "same_date_history_policy": "exclude_same_fight_date_bouts",
            "canonical_fighter_a_id": fighter_ids[0],
            "canonical_fighter_b_id": fighter_ids[1],
            "fighter_orientation": "canonical_fighter_id_ascending",
            "source_presence": record["source_presence"],
            "canonical_scheduled_format": record["canonical_scheduled_format"],
            "scheduled_rounds": _scheduled_rounds(record["canonical_scheduled_format"]),
            "canonical_outcome": record["canonical_outcome"],
            "winner_canonical_fighter_id": canonical_winner,
            "loser_canonical_fighter_id": canonical_loser,
            "is_no_contest": is_no_contest,
            "is_draw": is_draw,
            "canonical_finish_method": record["canonical_finish_method"],
            "canonical_finish_round": record["canonical_finish_round"],
            "canonical_finish_time": record["canonical_finish_time"],
            "outcome_authority_id": record["outcome_authority_id"],
            "authority_ledger_identifier": record["authority_ledger_identifier"],
            "decision_reference": record["decision_reference"],
            "reconciliation_evidence_sha256": record["evidence_sha256"],
            "field_classification": _HISTORICAL_FIELD_CLASSIFICATION,
        }
        rows.append(row)
    return rows


def _fighter_outcome(record: dict[str, object], fighter_id: str) -> str:
    if bool(record["is_no_contest"]):
        return "no_contest"
    if bool(record["is_draw"]):
        return "draw"
    if record["winner_canonical_fighter_id"] == fighter_id:
        return "win"
    if record["loser_canonical_fighter_id"] == fighter_id:
        return "loss"
    raise ValueError(f"historical bout has no fighter outcome: {record['canonical_bout_id']}")


def _finish_category(method: object) -> str:
    value = str(method or "").casefold()
    if "ko" in value or "tko" in value:
        return "knockout_tko"
    if "sub" in value:
        return "submission"
    if "dec" in value:
        return "decision"
    return "other_finish"


def _trailing_streak(history: list[dict[str, object]], accepted: set[str]) -> int:
    count = 0
    for record in reversed(history):
        if str(record["fighter_outcome"]) not in accepted:
            break
        count += 1
    return count


def _prefight_snapshot_row(
    *, target: dict[str, object], prior: list[dict[str, object]]
) -> dict[str, object]:
    target_date = cast(date, target["target_fight_date"])
    outcomes = [str(record["fighter_outcome"]) for record in prior]
    wins = outcomes.count("win")
    losses = outcomes.count("loss")
    draws = outcomes.count("draw")
    no_contests = outcomes.count("no_contest")
    decisive = wins + losses
    recent = prior[-5:]
    recent_outcomes = [str(record["fighter_outcome"]) for record in recent]
    recent_wins = recent_outcomes.count("win")
    recent_losses = recent_outcomes.count("loss")
    recent_decisive = recent_wins + recent_losses
    finish_wins = [
        str(record["finish_category"]) for record in prior if record["fighter_outcome"] == "win"
    ]
    previous_date = cast(date, prior[-1]["target_fight_date"]) if prior else None
    evidence = {
        "canonical_bout_id": target["canonical_bout_id"],
        "canonical_fighter_id": target["canonical_fighter_id"],
        "cutoff_policy_id": _PREFIGHT_CUTOFF_POLICY,
        "eligible_prior_bout_ids": [record["canonical_bout_id"] for record in prior],
    }
    return {
        **target,
        "history_cutoff_date": target_date,
        "cutoff_policy_id": _PREFIGHT_CUTOFF_POLICY,
        "cold_start": not prior,
        "prior_bouts": len(prior),
        "prior_wins": wins,
        "prior_losses": losses,
        "prior_draws": draws,
        "prior_no_contests": no_contests,
        "prior_decisive_bouts": decisive,
        "prior_win_rate": wins / decisive if decisive else None,
        "prior_loss_rate": losses / decisive if decisive else None,
        "days_since_previous_bout": (target_date - previous_date).days if previous_date else None,
        "prior_bouts_180_days": sum(
            (target_date - cast(date, record["target_fight_date"])).days <= 180 for record in prior
        ),
        "prior_bouts_365_days": sum(
            (target_date - cast(date, record["target_fight_date"])).days <= 365 for record in prior
        ),
        "prior_bouts_730_days": sum(
            (target_date - cast(date, record["target_fight_date"])).days <= 730 for record in prior
        ),
        "recent_five_observed_bouts": len(recent),
        "recent_five_wins": recent_wins,
        "recent_five_losses": recent_losses,
        "recent_five_draws": recent_outcomes.count("draw"),
        "recent_five_no_contests": recent_outcomes.count("no_contest"),
        "recent_five_win_rate": recent_wins / recent_decisive if recent_decisive else None,
        "current_win_streak": _trailing_streak(prior, {"win"}),
        "current_loss_streak": _trailing_streak(prior, {"loss"}),
        "current_unbeaten_streak": _trailing_streak(prior, {"win", "draw"}),
        "current_winless_streak": _trailing_streak(prior, {"loss", "draw"}),
        "prior_knockout_tko_wins": finish_wins.count("knockout_tko"),
        "prior_submission_wins": finish_wins.count("submission"),
        "prior_decision_wins": finish_wins.count("decision"),
        "prior_other_finish_wins": finish_wins.count("other_finish"),
        "prior_finish_win_rate": (
            sum(category != "decision" for category in finish_wins) / wins if wins else None
        ),
        "snapshot_evidence_sha256": content_sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str).encode()
        ),
    }


def _prefight_fighter_history_rows(historical_bouts: pl.DataFrame) -> list[dict[str, object]]:
    """Create strict-date, fighter-grain snapshots from accepted historical bouts only."""
    targets: list[dict[str, object]] = []
    for bout in historical_bouts.to_dicts():
        for fighter_column, opponent_column, slot in (
            ("canonical_fighter_a_id", "canonical_fighter_b_id", "canonical_fighter_a"),
            ("canonical_fighter_b_id", "canonical_fighter_a_id", "canonical_fighter_b"),
        ):
            fighter_id = str(bout[fighter_column])
            targets.append(
                {
                    "canonical_bout_id": bout["canonical_bout_id"],
                    "canonical_fighter_id": fighter_id,
                    "opponent_canonical_fighter_id": bout[opponent_column],
                    "target_fight_date": bout["fight_date"],
                    "fighter_slot": slot,
                    "fighter_outcome": _fighter_outcome(bout, fighter_id),
                    "finish_category": _finish_category(bout["canonical_finish_method"]),
                }
            )
    by_fighter: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for target in targets:
        by_fighter[str(target["canonical_fighter_id"])].append(target)
    snapshots: list[dict[str, object]] = []
    for fighter_id in sorted(by_fighter):
        history: list[dict[str, object]] = []
        grouped_by_date: defaultdict[date, list[dict[str, object]]] = defaultdict(list)
        for target in by_fighter[fighter_id]:
            grouped_by_date[cast(date, target["target_fight_date"])].append(target)
        for fight_date in sorted(grouped_by_date):
            same_date_targets = sorted(
                grouped_by_date[fight_date], key=lambda target: str(target["canonical_bout_id"])
            )
            # Snapshot the entire date before appending any same-date bouts.
            snapshots.extend(
                _prefight_snapshot_row(target=target, prior=history) for target in same_date_targets
            )
            history.extend(same_date_targets)
    for snapshot in snapshots:
        snapshot.pop("fighter_outcome")
        snapshot.pop("finish_category")
    return snapshots


def _parse_count(value: str) -> int | None:
    text = value.strip()
    if text in {"", "--", "---", "N/A"}:
        return None
    if not text.isdecimal():
        raise ValueError(f"malformed performance count: {value!r}")
    return int(text)


def _parse_pair(value: str) -> tuple[int | None, int | None]:
    text = value.strip()
    if text in {"", "--", "---", "N/A"}:
        return None, None
    parts = text.split(" of ")
    if len(parts) != 2:
        raise ValueError(f"malformed landed/attempted value: {value!r}")
    landed, attempted = (_parse_count(part) for part in parts)
    if landed is None or attempted is None or landed > attempted:
        raise ValueError(f"invalid landed/attempted value: {value!r}")
    return landed, attempted


def _control_seconds(value: str) -> int | None:
    text = value.strip()
    if text in {"", "--", "---", "N/A"}:
        return None
    parts = text.split(":")
    if len(parts) != 2 or not all(part.isdecimal() for part in parts):
        raise ValueError(f"malformed control time: {value!r}")
    minutes, seconds = (int(part) for part in parts)
    if seconds >= 60:
        raise ValueError(f"invalid control time: {value!r}")
    return 60 * minutes + seconds


def _performance_rows(
    *,
    historical: pl.DataFrame,
    reconciliation: pl.DataFrame,
    datalab_by_row: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    reconciliation_by_bout = {
        str(row["canonical_bout_id"]): row for row in reconciliation.to_dicts()
    }
    rows: list[dict[str, object]] = []
    for bout in historical.to_dicts():
        recon = reconciliation_by_bout[str(bout["canonical_bout_id"])]
        datalab_id = recon["ufc_datalab_source_row_id"]
        raw = datalab_by_row.get(str(datalab_id)) if datalab_id else None
        source_sides: dict[str, tuple[str, str]] = {}
        if raw is not None:
            source_sides = {
                _canonical_fighter(raw["red_fighter_name"], raw["bout_type"])[0]: (
                    "red",
                    "red_fighter",
                ),
                _canonical_fighter(raw["blue_fighter_name"], raw["bout_type"])[0]: (
                    "blue",
                    "blue_fighter",
                ),
            }
        for fighter_column, opponent_column, slot in (
            ("canonical_fighter_a_id", "canonical_fighter_b_id", "canonical_fighter_a"),
            ("canonical_fighter_b_id", "canonical_fighter_a_id", "canonical_fighter_b"),
        ):
            fighter = str(bout[fighter_column])
            if raw is not None and fighter not in source_sides:
                raise ValueError(f"cannot assign UFC-DataLab statistics: {datalab_id} / {fighter}")
            side = source_sides[fighter][0] if raw is not None else None
            values: dict[str, int | None] = {metric: None for metric in _PERFORMANCE_METRICS}
            if raw is not None and side is not None:
                prefix = f"{side}_fighter_"
                values["knockdowns"] = _parse_count(raw[prefix + "KD"])
                values["significant_strikes_landed"], values["significant_strikes_attempted"] = (
                    _parse_pair(raw[prefix + "sig_str"])
                )
                values["total_strikes_landed"], values["total_strikes_attempted"] = _parse_pair(
                    raw[prefix + "total_str"]
                )
                values["takedowns_landed"], values["takedowns_attempted"] = _parse_pair(
                    raw[prefix + "TD"]
                )
                values["submission_attempts"] = _parse_count(raw[prefix + "sub_att"])
                values["reversals"] = _parse_count(raw[prefix + "rev"])
                values["control_seconds"] = _control_seconds(raw[prefix + "ctrl"])
            row: dict[str, object] = {
                "canonical_bout_id": bout["canonical_bout_id"],
                "canonical_fighter_id": fighter,
                "opponent_canonical_fighter_id": bout[opponent_column],
                "fight_date": bout["fight_date"],
                "fighter_slot": slot,
                "source_presence": bout["source_presence"],
                "ultimate_source_row_id": recon["ultimate_source_row_id"],
                "ufc_datalab_source_row_id": datalab_id,
                "source_side": side,
                "contributing_sources": "ufc_datalab" if raw is not None else "",
                "reconciliation_policy_id": _PERFORMANCE_POLICY_ID,
                "field_classification": "post_bout_performance_observation",
                "performance_evidence_sha256": "",
            }
            for metric, value in values.items():
                row[metric] = value
                row[f"ultimate_{metric}"] = None
                row[f"ufc_datalab_{metric}"] = value
                row[f"{metric}_available"] = value is not None
                row[f"{metric}_reconciliation_status"] = (
                    "ufc_datalab_only" if value is not None else "unavailable"
                )
            evidence = {
                key: value for key, value in row.items() if key != "performance_evidence_sha256"
            }
            row["performance_evidence_sha256"] = content_sha256(
                json.dumps(evidence, sort_keys=True, default=str).encode()
            )
            rows.append(row)
    return rows


def _aggregate_performance(history: list[dict[str, object]], prefix: str) -> dict[str, object]:
    rows: dict[str, object] = {}
    for metric in _PERFORMANCE_METRICS:
        values = [record[metric] for record in history if record[metric] is not None]
        rows[f"{prefix}_{metric}_observed_count"] = len(values)
        rows[f"{prefix}_{metric}_missing_count"] = len(history) - len(values)
        rows[f"{prefix}_{metric}_sum"] = sum(cast(list[int], values)) if values else None
        rows[f"{prefix}_{metric}_mean"] = (
            sum(cast(list[int], values)) / len(values) if values else None
        )
    return rows


def _completed_duration_seconds(historical_bout: dict[str, object]) -> int | None:
    """Return an observed completed duration, never a scheduled-duration proxy.

    The accepted historical artifact retains the finishing round and elapsed time
    in that round.  MMA rounds are five minutes; this calculation intentionally
    uses neither ``scheduled_rounds`` nor ``canonical_scheduled_format``.
    Invalid or non-positive durations are excluded from pace aggregates.
    """
    finish_round = historical_bout.get("canonical_finish_round")
    finish_time = historical_bout.get("canonical_finish_time")
    if not isinstance(finish_round, int) or finish_round <= 0:
        return None
    if not isinstance(finish_time, str):
        return None
    parts = finish_time.strip().split(":")
    if len(parts) != 2 or not all(part.isdecimal() for part in parts):
        return None
    minutes, seconds = (int(part) for part in parts)
    if minutes < 0 or not 0 <= seconds < 60:
        return None
    elapsed_in_round = minutes * 60 + seconds
    # A finishing clock cannot exceed one five-minute round.  This explicitly
    # rejects malformed values instead of normalizing them to a fake duration.
    if elapsed_in_round > 300:
        return None
    duration = (finish_round - 1) * 300 + elapsed_in_round
    return duration if duration > 0 else None


def _validate_performance_observation_integrity(records: list[dict[str, object]]) -> None:
    """Fail closed when a raw post-bout numerator exceeds its denominator."""
    for record in records:
        for landed, attempted in (
            ("significant_strikes_landed", "significant_strikes_attempted"),
            ("total_strikes_landed", "total_strikes_attempted"),
            ("takedowns_landed", "takedowns_attempted"),
        ):
            numerator = record.get(landed)
            denominator = record.get(attempted)
            if (
                isinstance(numerator, int)
                and isinstance(denominator, int)
                and numerator > denominator
            ):
                raise ValueError(f"performance landed total exceeds attempts: {landed}")


def _pace_rate(
    history: list[dict[str, object]],
    duration_by_bout: dict[str, int | None],
    metric: str,
    multiplier: float,
) -> float | None:
    """Calculate a duration-weighted historical pace without treating nulls as zero."""
    numerator = 0
    denominator = 0
    for record in history:
        value = record[metric]
        duration = duration_by_bout.get(str(record["canonical_bout_id"]))
        if value is None or duration is None:
            continue
        numerator += cast(int, value)
        denominator += duration
    return numerator * multiplier / denominator if denominator > 0 else None


def _prefight_performance_rows(
    performance: pl.DataFrame, historical_bouts: pl.DataFrame
) -> list[dict[str, object]]:
    records = performance.to_dicts()
    _validate_performance_observation_integrity(records)
    duration_by_bout = {
        str(record["canonical_bout_id"]): _completed_duration_seconds(record)
        for record in historical_bouts.to_dicts()
    }
    performance_bouts = {str(record["canonical_bout_id"]) for record in records}
    if set(duration_by_bout) != performance_bouts:
        raise ValueError("historical and performance bout identities differ")
    opponent_by_key = {
        (str(record["canonical_bout_id"]), str(record["canonical_fighter_id"])): record
        for record in records
    }
    by_fighter: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        by_fighter[str(record["canonical_fighter_id"])].append(record)
    output: list[dict[str, object]] = []
    for fighter, targets in sorted(by_fighter.items()):
        prior: list[dict[str, object]] = []
        by_date: defaultdict[date, list[dict[str, object]]] = defaultdict(list)
        for target in targets:
            by_date[cast(date, target["fight_date"])].append(target)
        for target_date in sorted(by_date):
            for target in sorted(
                by_date[target_date], key=lambda value: str(value["canonical_bout_id"])
            ):
                row: dict[str, object] = {
                    "canonical_bout_id": target["canonical_bout_id"],
                    "canonical_fighter_id": fighter,
                    "opponent_canonical_fighter_id": target["opponent_canonical_fighter_id"],
                    "target_fight_date": target_date,
                    "cutoff_policy_id": _PREFIGHT_CUTOFF_POLICY,
                    "feature_policy_id": _PREFIGHT_PERFORMANCE_POLICY_ID,
                    "cold_start": not prior,
                    "eligible_prior_performance_bouts": len(prior),
                    "snapshot_evidence_sha256": "",
                }
                row.update(_aggregate_performance(prior, "career"))
                row.update(_aggregate_performance(prior[-3:], "recent_3"))
                row.update(_aggregate_performance(prior[-5:], "recent_5"))
                row.update(
                    _aggregate_performance(
                        [
                            r
                            for r in prior
                            if (target_date - cast(date, r["fight_date"])).days <= 365
                        ],
                        "days_365",
                    )
                )
                row.update(
                    _aggregate_performance(
                        [
                            r
                            for r in prior
                            if (target_date - cast(date, r["fight_date"])).days <= 730
                        ],
                        "days_730",
                    )
                )
                for rate, landed, attempted in (
                    (
                        "significant_strike_accuracy",
                        "significant_strikes_landed",
                        "significant_strikes_attempted",
                    ),
                    ("total_strike_accuracy", "total_strikes_landed", "total_strikes_attempted"),
                    ("takedown_accuracy", "takedowns_landed", "takedowns_attempted"),
                ):
                    denominator = row[f"career_{attempted}_sum"]
                    numerator = row[f"career_{landed}_sum"]
                    row[f"career_{rate}"] = (
                        numerator / denominator
                        if isinstance(numerator, int)
                        and isinstance(denominator, int)
                        and denominator > 0
                        else None
                    )
                opponents = [
                    opponent_by_key[
                        (
                            str(record["canonical_bout_id"]),
                            str(record["opponent_canonical_fighter_id"]),
                        )
                    ]
                    for record in prior
                ]
                for metric in (
                    "knockdowns",
                    "significant_strikes_landed",
                    "total_strikes_landed",
                    "takedowns_landed",
                    "takedowns_attempted",
                    "submission_attempts",
                    "control_seconds",
                ):
                    values = [record[metric] for record in opponents if record[metric] is not None]
                    row[f"career_opponent_{metric}_observed_count"] = len(values)
                    row[f"career_opponent_{metric}_missing_count"] = len(opponents) - len(values)
                    row[f"career_{metric}_absorbed_sum"] = (
                        sum(cast(list[int], values)) if values else None
                    )
                    row[f"career_{metric}_absorbed_per_observed_bout"] = (
                        sum(cast(list[int], values)) / len(values) if values else None
                    )
                # Opponent attempt totals are evaluated directly because only
                # selected defensive totals are emitted.
                opponent_sig_attempted = [
                    r["significant_strikes_attempted"]
                    for r in opponents
                    if r["significant_strikes_attempted"] is not None
                ]
                opponent_td_attempted = [
                    r["takedowns_attempted"]
                    for r in opponents
                    if r["takedowns_attempted"] is not None
                ]
                sig_denominator = sum(cast(list[int], opponent_sig_attempted))
                td_denominator = sum(cast(list[int], opponent_td_attempted))
                row["career_significant_strike_defense"] = (
                    1
                    - cast(int, row["career_significant_strikes_landed_absorbed_sum"])
                    / sig_denominator
                    if sig_denominator > 0
                    and row["career_significant_strikes_landed_absorbed_sum"] is not None
                    else None
                )
                row["career_takedown_defense"] = (
                    1 - cast(int, row["career_takedowns_landed_absorbed_sum"]) / td_denominator
                    if td_denominator > 0
                    and row["career_takedowns_landed_absorbed_sum"] is not None
                    else None
                )
                valid_duration_history = [
                    record
                    for record in prior
                    if duration_by_bout[str(record["canonical_bout_id"])] is not None
                ]
                row["career_valid_duration_observed_count"] = len(valid_duration_history)
                row["career_excluded_duration_prior_bout_count"] = len(prior) - len(
                    valid_duration_history
                )
                for name, metric, multiplier in (
                    (
                        "significant_strikes_landed_per_minute",
                        "significant_strikes_landed",
                        60.0,
                    ),
                    ("total_strikes_landed_per_minute", "total_strikes_landed", 60.0),
                    ("takedown_attempts_per_15_minutes", "takedowns_attempted", 900.0),
                    ("submission_attempts_per_15_minutes", "submission_attempts", 900.0),
                    ("control_seconds_per_fight_minute", "control_seconds", 1.0),
                ):
                    row[f"career_{name}"] = _pace_rate(prior, duration_by_bout, metric, multiplier)
                row["snapshot_evidence_sha256"] = content_sha256(
                    json.dumps(
                        {
                            "target": row["canonical_bout_id"],
                            "fighter": fighter,
                            "prior": [r["canonical_bout_id"] for r in prior],
                        },
                        sort_keys=True,
                    ).encode()
                )
                output.append(row)
            prior.extend(by_date[target_date])
    return output


def _validate_prefight_performance_history(
    *, prefight_performance: pl.DataFrame, performance: pl.DataFrame
) -> None:
    """Enforce Phase 3B2B's numeric, grain, and strict-cutoff invariants."""
    if (
        prefight_performance.select(["canonical_bout_id", "canonical_fighter_id"]).unique().height
        != prefight_performance.height
    ):
        raise ValueError("pre-fight performance history has duplicate bout/fighter keys")
    if (
        not prefight_performance.group_by("canonical_bout_id")
        .len()
        .select(pl.col("len").eq(2).all())
        .item()
    ):
        raise ValueError("pre-fight performance history must contain two rows per bout")
    if prefight_performance.filter(
        pl.col("career_valid_duration_observed_count")
        + pl.col("career_excluded_duration_prior_bout_count")
        != pl.col("eligible_prior_performance_bouts")
    ).height:
        raise ValueError("duration inclusion counts do not reconcile to prior history")
    for metric in _PERFORMANCE_METRICS:
        if prefight_performance.filter(
            pl.col(f"career_{metric}_observed_count") + pl.col(f"career_{metric}_missing_count")
            != pl.col("eligible_prior_performance_bouts")
        ).height:
            raise ValueError(f"performance missingness does not reconcile: {metric}")
    rate_columns = [
        name for name in prefight_performance.columns if name.endswith(("_accuracy", "_defense"))
    ]
    rate_columns.extend(
        [
            "career_significant_strikes_landed_per_minute",
            "career_total_strikes_landed_per_minute",
            "career_takedown_attempts_per_15_minutes",
            "career_submission_attempts_per_15_minutes",
            "career_control_seconds_per_fight_minute",
        ]
    )
    if prefight_performance.select(
        pl.any_horizontal(
            [pl.col(name).is_not_null() & ~pl.col(name).is_finite() for name in rate_columns]
        ).any()
    ).item():
        raise ValueError("pre-fight performance history contains a non-finite rate")
    bounded_rates = [name for name in rate_columns if name.endswith(("_accuracy", "_defense"))]
    if prefight_performance.select(
        pl.any_horizontal(
            [
                pl.col(name).is_not_null() & ((pl.col(name) < 0) | (pl.col(name) > 1))
                for name in bounded_rates
            ]
        ).any()
    ).item():
        raise ValueError("pre-fight performance history contains an out-of-range rate")
    target_dates = performance.select(
        ["canonical_bout_id", "canonical_fighter_id", pl.col("fight_date").alias("source_date")]
    )
    expected = (
        target_dates.join(
            performance.select(
                [
                    pl.col("canonical_fighter_id"),
                    pl.col("fight_date").alias("prior_date"),
                ]
            ),
            on="canonical_fighter_id",
            how="left",
        )
        .filter(pl.col("prior_date") < pl.col("source_date"))
        .group_by(["canonical_bout_id", "canonical_fighter_id"])
        .len()
        .rename({"len": "expected_eligible_prior_bouts"})
    )
    compared = prefight_performance.join(
        expected, on=["canonical_bout_id", "canonical_fighter_id"], how="left"
    ).with_columns(pl.col("expected_eligible_prior_bouts").fill_null(0))
    if compared.filter(
        pl.col("eligible_prior_performance_bouts") != pl.col("expected_eligible_prior_bouts")
    ).height:
        raise ValueError("pre-fight performance history violates strict date cutoff")


def _pairwise_feature_columns() -> set[str]:
    columns: set[str] = set()
    for entry in _PAIRWISE_FEATURE_REGISTRY:
        name = entry["source_column"]
        columns.update(
            {f"a_{name}", f"b_{name}", f"diff_{name}", f"a_{name}_missing", f"b_{name}_missing"}
        )
    return columns


def _pairwise_rows(
    historical: pl.DataFrame, prefight: pl.DataFrame, prefight_performance: pl.DataFrame
) -> list[dict[str, object]]:
    """Join two accepted long-form snapshots in canonical historical orientation."""
    base_by_key = {
        (str(r["canonical_bout_id"]), str(r["canonical_fighter_id"])): r
        for r in prefight.to_dicts()
    }
    performance_by_key = {
        (str(r["canonical_bout_id"]), str(r["canonical_fighter_id"])): r
        for r in prefight_performance.to_dicts()
    }
    rows: list[dict[str, object]] = []
    for bout in historical.sort("canonical_bout_id").to_dicts():
        bout_id = str(bout["canonical_bout_id"])
        fighter_a = str(bout["canonical_fighter_a_id"])
        fighter_b = str(bout["canonical_fighter_b_id"])
        if fighter_a == fighter_b:
            raise ValueError("pairwise row has identical fighters")
        a_base, b_base = base_by_key[(bout_id, fighter_a)], base_by_key[(bout_id, fighter_b)]
        a_performance = performance_by_key[(bout_id, fighter_a)]
        b_performance = performance_by_key[(bout_id, fighter_b)]
        row: dict[str, object] = {
            "canonical_bout_id": bout_id,
            "fight_date": bout["fight_date"],
            "canonical_fighter_a_id": fighter_a,
            "canonical_fighter_b_id": fighter_b,
            "orientation_policy_id": _PAIRWISE_ORIENTATION_POLICY_ID,
            "feature_schema_version": _PAIRWISE_FEATURE_SCHEMA_VERSION,
            "canonical_outcome": bout["canonical_outcome"],
            "is_draw": bout["is_draw"],
            "is_no_contest": bout["is_no_contest"],
            "fighter_a_won": (
                None
                if bool(bout["is_draw"]) or bool(bout["is_no_contest"])
                else int(bout["winner_canonical_fighter_id"] == fighter_a)
            ),
            "pairwise_evidence_sha256": "",
        }
        for entry in _PAIRWISE_FEATURE_REGISTRY:
            source_a, source_b = (
                (a_base, b_base)
                if entry["source_artifact"] == "m3_prefight_fighter_history.parquet"
                else (a_performance, b_performance)
            )
            name = entry["source_column"]
            a_value, b_value = source_a[name], source_b[name]
            row[f"a_{name}"] = a_value
            row[f"b_{name}"] = b_value
            row[f"a_{name}_missing"] = a_value is None
            row[f"b_{name}_missing"] = b_value is None
            if a_value is None or b_value is None:
                row[f"diff_{name}"] = None
            elif entry["data_type"] == "bool":
                row[f"diff_{name}"] = int(bool(a_value)) - int(bool(b_value))
            else:
                row[f"diff_{name}"] = cast(int | float, a_value) - cast(int | float, b_value)
        evidence = {key: value for key, value in row.items() if key != "pairwise_evidence_sha256"}
        row["pairwise_evidence_sha256"] = content_sha256(
            json.dumps(evidence, sort_keys=True, default=str, separators=(",", ":")).encode()
        )
        rows.append(row)
    return rows


def swap_pairwise_row(row: dict[str, object]) -> dict[str, object]:
    """Apply the declared pairwise swap transformation for symmetry verification."""
    swapped = dict(row)
    swapped["canonical_fighter_a_id"], swapped["canonical_fighter_b_id"] = (
        row["canonical_fighter_b_id"],
        row["canonical_fighter_a_id"],
    )
    for entry in _PAIRWISE_FEATURE_REGISTRY:
        name = entry["source_column"]
        for suffix in ("", "_missing"):
            swapped[f"a_{name}{suffix}"], swapped[f"b_{name}{suffix}"] = (
                row[f"b_{name}{suffix}"],
                row[f"a_{name}{suffix}"],
            )
        value = row[f"diff_{name}"]
        swapped[f"diff_{name}"] = -cast(int | float, value) if value is not None else None
    label = row["fighter_a_won"]
    swapped["fighter_a_won"] = 1 - cast(int, label) if label is not None else None
    return swapped


def _model_ready_feature_columns() -> list[str]:
    names = [entry["source_column"] for entry in _PAIRWISE_FEATURE_REGISTRY]
    return (
        [f"a_{name}" for name in names]
        + [f"b_{name}" for name in names]
        + [f"diff_{name}" for name in names]
        + [f"a_{name}_missing" for name in names]
        + [f"b_{name}_missing" for name in names]
    )


def _model_ready_binary(
    pairwise: pl.DataFrame, *, validate_cardinality: bool = True
) -> pl.DataFrame:
    """Project decisive pairwise rows without changing their feature values."""
    metadata = [
        "canonical_bout_id",
        "fight_date",
        "canonical_fighter_a_id",
        "canonical_fighter_b_id",
        "orientation_policy_id",
        "feature_schema_version",
        "pairwise_evidence_sha256",
    ]
    features = _model_ready_feature_columns()
    if set(features) != _pairwise_feature_columns() or len(features) != 130:
        raise ValueError("model-ready feature registry is incomplete or duplicated")
    result = (
        pairwise.filter(~pl.col("is_draw") & ~pl.col("is_no_contest"))
        .select(metadata + features + [pl.col("fighter_a_won").alias("target_fighter_a_won")])
        .sort("canonical_bout_id")
    )
    if validate_cardinality and (
        result.height != 8912 or result["canonical_bout_id"].n_unique() != 8912
    ):
        raise ValueError("model-ready projection has an invalid decisive-bout grain")
    if result["target_fighter_a_won"].null_count() or not set(
        result["target_fighter_a_won"]
    ).issubset({0, 1}):
        raise ValueError("model-ready binary target is invalid")
    for entry in _PAIRWISE_FEATURE_REGISTRY:
        name = entry["source_column"]
        for side in ("a", "b"):
            value, missing = f"{side}_{name}", f"{side}_{name}_missing"
            if result.filter(pl.col(missing) != pl.col(value).is_null()).height:
                raise ValueError(f"model-ready missingness indicator disagrees: {value}")
    return result


def swap_model_ready_row(row: dict[str, object]) -> dict[str, object]:
    """Swap an eligible binary row under the accepted pairwise swap contract."""
    swapped = dict(row)
    swapped["canonical_fighter_a_id"], swapped["canonical_fighter_b_id"] = (
        row["canonical_fighter_b_id"],
        row["canonical_fighter_a_id"],
    )
    for entry in _PAIRWISE_FEATURE_REGISTRY:
        name = entry["source_column"]
        for suffix in ("", "_missing"):
            swapped[f"a_{name}{suffix}"], swapped[f"b_{name}{suffix}"] = (
                row[f"b_{name}{suffix}"],
                row[f"a_{name}{suffix}"],
            )
        value = row[f"diff_{name}"]
        swapped[f"diff_{name}"] = -cast(int | float, value) if value is not None else None
    swapped["target_fighter_a_won"] = 1 - cast(int, row["target_fighter_a_won"])
    return swapped


def _build_m3_artifact_set(
    *, ultimate_csv: Path, datalab_csv: Path, v6_dir: Path, output_dir: Path
) -> dict[str, object]:
    """Materialize only derived, source-provenance-complete M3 outputs."""
    ledger = _jsonl(v6_dir / "m3_imported_decisions.jsonl")
    supplemental = _jsonl(
        v6_dir / "authority-migration-v1/m3_supplemental_legacy_authorities.jsonl"
    )
    if len(ledger) != 34 or len(supplemental) != 102:
        raise ValueError("M3 authority ledgers are incomplete")
    authority_index = load_authority_index(v6_dir)
    # These are the only reviewed identity exceptions used in this Phase 2A
    # foundation.  Resolving them here makes a missing, copied, or mismatched
    # authority record fail materialization instead of silently changing an ID.
    bruno_authority = authority_index.resolve("M3-ID-8956BE143EA0", SUPPLEMENTAL_LEDGER_IDENTIFIER)
    roldan_authority = authority_index.resolve("M3-ID-524AA01602F1", V6_LEDGER_IDENTIFIER)
    outcome_authorities = _outcome_authorities(authority_index)
    taxonomy_authorities = taxonomy_authority_coverage(
        ultimate_csv=ultimate_csv, datalab_csv=datalab_csv, v6_dir=v6_dir
    )
    excluded = {"row-5170", "row-5658"}
    outcomes = {
        "row-" + r["source_values"].split("stats_raw.csv:row-")[1].split()[0]: r[
            "reviewer_decision"
        ]
        for r in ledger
        if r["category"].startswith("outcome.")
    }
    ultimate = list(csv.DictReader(ultimate_csv.open(encoding="utf-8-sig", newline="")))
    datalab = list(
        csv.DictReader(datalab_csv.open(encoding="utf-8-sig", newline=""), delimiter=";")
    )
    seen: set[tuple[str, tuple[str, str]]] = set()
    bouts: list[dict[str, object]] = []
    crosswalk: list[dict[str, object]] = []
    primary_by_key: dict[tuple[str, tuple[str, str]], dict[str, object]] = {}
    collapsed_duplicates: list[dict[str, str]] = []
    primary_row_by_key: dict[tuple[str, tuple[str, str]], str] = {}
    canonical_identities: dict[str, tuple[str, str]] = {}
    alias_observations: list[dict[str, str]] = []
    for row_number, row in enumerate(datalab, start=2):
        key = _bout_key(_iso(row["event_date"]), row["red_fighter_name"], row["blue_fighter_name"])
        if key in seen:
            collapsed_duplicates.append(
                {
                    "duplicate_source_row_id": f"row-{row_number}",
                    "retained_source_row_id": primary_row_by_key[key],
                    "fight_date": key[0],
                    "fighter_a_normalized": key[1][0],
                    "fighter_b_normalized": key[1][1],
                }
            )
            continue
        seen.add(key)
        record_key = f"row-{row_number}"
        primary_row_by_key[key] = record_key
        red, blue = (
            _fighter(row["red_fighter_name"], row.get("bout_type", "")),
            _fighter(row["blue_fighter_name"], row.get("bout_type", "")),
        )
        canonical_red = _canonical_fighter(row["red_fighter_name"], row.get("bout_type", ""))
        canonical_blue = _canonical_fighter(row["blue_fighter_name"], row.get("bout_type", ""))
        canonical_identities[canonical_red[0]] = (canonical_red[1], canonical_red[2])
        canonical_identities[canonical_blue[0]] = (canonical_blue[1], canonical_blue[2])
        alias_observations.extend(
            (
                _alias_observation(
                    "ufc-datalab", record_key, row["red_fighter_name"], red[0], canonical_red[0]
                ),
                _alias_observation(
                    "ufc-datalab", record_key, row["blue_fighter_name"], blue[0], canonical_blue[0]
                ),
            )
        )
        outcome = (
            "no_contest"
            if outcomes.get(record_key) == "confirm_overturned"
            else row["fight_outcome"]
        )
        bout = _bout(
            record_key,
            "ufc-datalab",
            _iso(row["event_date"]),
            red[0],
            blue[0],
            outcome,
            row["method"],
            int(row["round"]) if row["round"].isdigit() else None,
            row["time_format"],
            row["event_name"],
            row["event_location"],
        )
        bouts.append(bout)
        primary_by_key[key] = bout
        crosswalk.append(
            _crosswalk(
                "ufc-datalab",
                record_key,
                bout,
                row["red_fighter_name"],
                row["blue_fighter_name"],
                "ufc_datalab_only",
            )
        )
    for row_number, row in enumerate(ultimate, start=2):
        record_key = f"row-{row_number}"
        if record_key in excluded:
            continue
        key = _bout_key(row["date"], row["R_fighter"], row["B_fighter"])
        red, blue = (
            _fighter(row["R_fighter"], row.get("weight_class", "")),
            _fighter(row["B_fighter"], row.get("weight_class", "")),
        )
        canonical_red = _canonical_fighter(row["R_fighter"], row.get("weight_class", ""))
        canonical_blue = _canonical_fighter(row["B_fighter"], row.get("weight_class", ""))
        canonical_identities[canonical_red[0]] = (canonical_red[1], canonical_red[2])
        canonical_identities[canonical_blue[0]] = (canonical_blue[1], canonical_blue[2])
        alias_observations.extend(
            (
                _alias_observation(
                    "ultimate", record_key, row["R_fighter"], red[0], canonical_red[0]
                ),
                _alias_observation(
                    "ultimate", record_key, row["B_fighter"], blue[0], canonical_blue[0]
                ),
            )
        )
        if key in seen:
            bout = primary_by_key[key]
            crosswalk.append(
                _crosswalk(
                    "ultimate",
                    record_key,
                    bout,
                    row["R_fighter"],
                    row["B_fighter"],
                    "normalized",
                )
            )
            continue
        bout = _bout(
            record_key,
            "ultimate",
            row["date"],
            red[0],
            blue[0],
            row["Winner"],
            row.get("finish", ""),
            _int(row.get("finish_round", "")),
            str(row["no_of_rounds"]),
            None,
            row.get("location"),
        )
        bouts.append(bout)
        crosswalk.append(
            _crosswalk(
                "ultimate",
                record_key,
                bout,
                row["R_fighter"],
                row["B_fighter"],
                "ultimate_only",
            )
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "semantic_groups": output_dir / "m3_semantic_bout_groups.parquet",
        "crosswalk": output_dir / "m3_source_bout_crosswalk.parquet",
        "m3_fighters": output_dir / "m3_canonical_fighters.parquet",
        "m3_aliases": output_dir / "m3_canonical_fighter_aliases.parquet",
        "m3_taxonomy": output_dir / "m3_taxonomy_authorities.parquet",
        "reconciliation": output_dir / "m3_bout_reconciliation.parquet",
        "reviewed_exclusions": output_dir / "m3_reviewed_exclusions.parquet",
        "duplicate_collapses": output_dir / "m3_duplicate_collapses.parquet",
        "historical_bouts": output_dir / "m3_canonical_historical_bouts.parquet",
        "prefight_fighter_history": output_dir / "m3_prefight_fighter_history.parquet",
        "fighter_bout_performance": output_dir / "m3_fighter_bout_performance.parquet",
        "prefight_performance_history": output_dir / "m3_prefight_performance_history.parquet",
        "pairwise_features": output_dir / "m3_prefight_pairwise_features.parquet",
        "model_ready_binary": output_dir / "m3_model_ready_binary.parquet",
    }
    crosswalk_frame = pl.DataFrame(crosswalk).sort(
        ["canonical_bout_id", "source_name", "source_row_id"]
    )
    crosswalk_frame.write_parquet(paths["crosswalk"])
    groups = (
        crosswalk_frame.group_by("canonical_bout_id")
        .agg(
            [
                pl.col("source_name").sort().alias("sources"),
                pl.col("source_row_id").sort().alias("source_rows"),
            ]
        )
        .sort("canonical_bout_id")
    )
    groups.write_parquet(paths["semantic_groups"])
    ultimate_by_row = {f"row-{number}": row for number, row in enumerate(ultimate, start=2)}
    datalab_by_row = {f"row-{number}": row for number, row in enumerate(datalab, start=2)}
    reconciliation = pl.DataFrame(
        _reconciliation_rows(
            crosswalk=crosswalk_frame,
            ultimate_by_row=ultimate_by_row,
            datalab_by_row=datalab_by_row,
            outcome_authorities=outcome_authorities,
        ),
        schema=_RECONCILIATION_SCHEMA,
    ).sort("canonical_bout_id")
    if reconciliation.height != 9068 or reconciliation["canonical_bout_id"].n_unique() != 9068:
        raise ValueError("reconciliation must contain one row for each of 9,068 semantic groups")
    reconciliation.write_parquet(paths["reconciliation"])
    historical_bouts = pl.DataFrame(
        _canonical_historical_bout_rows(
            reconciliation=reconciliation,
            ultimate_by_row=ultimate_by_row,
            datalab_by_row=datalab_by_row,
            canonical_fighter_ids=set(canonical_identities),
        ),
        schema=_HISTORICAL_SCHEMA,
    ).sort("global_chronological_key")
    if (
        historical_bouts.height != reconciliation.height
        or historical_bouts["canonical_bout_id"].n_unique() != reconciliation.height
    ):
        raise ValueError("historical bouts must contain one row for every reconciliation row")
    historical_bouts.write_parquet(paths["historical_bouts"])
    prefight_history = pl.DataFrame(
        _prefight_fighter_history_rows(historical_bouts), schema=_PREFIGHT_SCHEMA
    ).sort(["target_fight_date", "canonical_bout_id", "canonical_fighter_id"])
    if (
        prefight_history.height != historical_bouts.height * 2
        or prefight_history.select(["canonical_bout_id", "canonical_fighter_id"]).unique().height
        != prefight_history.height
    ):
        raise ValueError("pre-fight history must contain two unique fighter snapshots per bout")
    bout_fighters = historical_bouts.select(
        ["canonical_bout_id", "canonical_fighter_a_id", "canonical_fighter_b_id"]
    )
    snapshot_bouts = prefight_history.join(bout_fighters, on="canonical_bout_id", how="left")
    if snapshot_bouts.filter(
        ~pl.col("canonical_fighter_id").is_in(
            pl.concat_list("canonical_fighter_a_id", "canonical_fighter_b_id")
        )
        | ~pl.col("opponent_canonical_fighter_id").is_in(
            pl.concat_list("canonical_fighter_a_id", "canonical_fighter_b_id")
        )
        | (pl.col("canonical_fighter_id") == pl.col("opponent_canonical_fighter_id"))
    ).height:
        raise ValueError("pre-fight snapshot fighters do not match target bout")
    count_columns = [
        name
        for name in _PREFIGHT_SCHEMA
        if name.startswith("prior_")
        or name.startswith("recent_five_")
        or name.startswith("current_")
    ]
    count_columns = [name for name in count_columns if not name.endswith("rate")]
    if prefight_history.select(
        pl.any_horizontal([pl.col(name) < 0 for name in count_columns]).any()
    ).item():
        raise ValueError("pre-fight history contains a negative count")
    rate_columns = [name for name, dtype in _PREFIGHT_SCHEMA.items() if dtype == pl.Float64]
    if prefight_history.select(
        pl.any_horizontal(
            [pl.col(name).is_not_null() & ~pl.col(name).is_finite() for name in rate_columns]
        ).any()
    ).item():
        raise ValueError("pre-fight history contains a non-finite rate")
    if prefight_history.filter(
        (pl.col("prior_wins") + pl.col("prior_losses") > pl.col("prior_bouts"))
        | (pl.col("prior_decisive_bouts") > pl.col("prior_bouts"))
        | (pl.col("recent_five_observed_bouts") > pl.col("prior_bouts"))
    ).height:
        raise ValueError("pre-fight component counts exceed prior history")
    prefight_history.write_parquet(paths["prefight_fighter_history"])
    performance = pl.DataFrame(
        _performance_rows(
            historical=historical_bouts,
            reconciliation=reconciliation,
            datalab_by_row=datalab_by_row,
        ),
        schema=_PERFORMANCE_SCHEMA,
    ).sort(["fight_date", "canonical_bout_id", "canonical_fighter_id"])
    if performance.height != historical_bouts.height * 2:
        raise ValueError("performance observations must contain two rows per historical bout")
    performance.write_parquet(paths["fighter_bout_performance"])
    prefight_performance = pl.DataFrame(
        _prefight_performance_rows(performance, historical_bouts),
        schema=_PREFIGHT_PERFORMANCE_SCHEMA,
    ).sort(["target_fight_date", "canonical_bout_id", "canonical_fighter_id"])
    if prefight_performance.height != 18136:
        raise ValueError("pre-fight performance history cardinality changed")
    _validate_prefight_performance_history(
        prefight_performance=prefight_performance,
        performance=performance,
    )
    prefight_performance.write_parquet(paths["prefight_performance_history"])
    pairwise = pl.DataFrame(
        _pairwise_rows(historical_bouts, prefight_history, prefight_performance)
    ).sort("canonical_bout_id")
    if pairwise.height != 9068 or pairwise["canonical_bout_id"].n_unique() != 9068:
        raise ValueError("pairwise features must contain one row per historical bout")
    if pairwise.select(
        pl.any_horizontal(
            [
                pl.col(name).is_not_null() & ~pl.col(name).is_finite()
                for name, dtype in pairwise.schema.items()
                if dtype == pl.Float64
            ]
        ).any()
    ).item():
        raise ValueError("pairwise features contain a non-finite value")
    pairwise.write_parquet(paths["pairwise_features"])
    model_ready = _model_ready_binary(pairwise)
    model_ready.write_parquet(paths["model_ready_binary"])
    reviewed_exclusions = pl.DataFrame(
        _reviewed_exclusion_rows(authority_index, crosswalk_frame), schema=_EXCLUSION_SCHEMA
    ).sort("source_row_id")
    if reviewed_exclusions.height != 2:
        raise ValueError("expected exactly two reviewed exclusions")
    reviewed_exclusions.write_parquet(paths["reviewed_exclusions"])
    duplicate_collapses = pl.DataFrame(
        _duplicate_collapse_rows(collapsed_duplicates, crosswalk_frame), schema=_DUPLICATE_SCHEMA
    ).sort("duplicate_source_row_id")
    duplicate_collapses.write_parquet(paths["duplicate_collapses"])
    fighter_frame = pl.DataFrame(
        [
            _canonical_fighter_row(
                fighter_id=k,
                display_name=display_name,
                context_key=context_key,
                bruno_authority=bruno_authority,
                roldan_authority=roldan_authority,
            )
            for k, (display_name, context_key) in sorted(canonical_identities.items())
        ]
    ).sort("canonical_fighter_id")
    fighter_frame.write_parquet(paths["m3_fighters"])
    source_bout_lookup = crosswalk_frame.select(
        ["source_name", "source_row_id", "canonical_bout_id"]
    )
    aliases = (
        pl.DataFrame(alias_observations)
        .join(source_bout_lookup, on=["source_name", "source_row_id"], how="inner")
        .with_columns(
            pl.col("raw_fighter_name")
            .map_elements(
                lambda value: normalize_fighter_alias(value).normalized_value,
                return_dtype=pl.String,
            )
            .alias("normalized_lookup_key"),
        )
        .join(
            fighter_frame.select(
                [
                    "canonical_fighter_id",
                    "identity_context_key",
                    "authority_id",
                    "ledger_identifier",
                    "authority_kind",
                ]
            ),
            on="canonical_fighter_id",
            how="left",
        )
        .with_columns(
            pl.when(pl.col("authority_id").is_not_null())
            .then(pl.lit("reviewed_identity_mapping"))
            .otherwise(pl.lit("deterministic_self_mapping"))
            .alias("mapping_type")
        )
        .sort(["source_name", "source_row_id", "raw_fighter_name"])
    )
    aliases.write_parquet(paths["m3_aliases"])
    taxonomy = pl.DataFrame(
        [
            {
                "source_name": authority.source_name,
                "source_schema_version": authority.source_schema_version,
                "field_name": authority.field_name,
                "raw_value": authority.raw_value,
                "canonical_value": authority.canonical_value,
                "is_null_policy": authority.is_null_policy,
                "authority_id": authority.authority_id,
                "ledger_identifier": authority.ledger_identifier,
                "decision_reference": authority.decision_reference,
                "decision_action": authority.decision_action,
                "category": authority.category,
                "source_evidence_sha256": authority.source_evidence_sha256,
            }
            for authority in taxonomy_authorities
            if authority.classification == "active_and_applicable"
        ]
    ).sort(["source_name", "field_name", "raw_value", "authority_id"])
    taxonomy.write_parquet(paths["m3_taxonomy"])
    report = {
        "canonical_fighter_count": fighter_frame.height,
        "excluded_records": sorted(excluded),
        "unresolved_count": 0,
        "phase_1": {
            "crosswalk_rows": crosswalk_frame.height,
            "semantic_groups": groups.height,
            "collapsed_duplicate_rows": [
                row["duplicate_source_row_id"] for row in collapsed_duplicates
            ],
        },
        "phase_2a_authority": {
            "authority_records": authority_index.record_count,
            "v6_records": authority_index.count_for_ledger(V6_LEDGER_IDENTIFIER),
            "supplemental_records": authority_index.count_for_ledger(
                SUPPLEMENTAL_LEDGER_IDENTIFIER
            ),
            "reviewed_identity_contexts": fighter_frame.filter(
                pl.col("authority_id").is_not_null()
            ).height,
            "taxonomy_decisions_inspected": len(taxonomy_authorities),
            "taxonomy_rows_emitted": taxonomy.height,
        },
        "phase_2b": {
            "reconciliation_rows": reconciliation.height,
            "reviewed_outcomes_applied": reconciliation.filter(
                pl.col("outcome_authority_id").is_not_null()
            ).height,
            "reviewed_exclusions": reviewed_exclusions.height,
            "duplicate_collapses": duplicate_collapses.height,
            "unresolved_conflicts": 0,
        },
        "phase_3a": {
            "historical_bouts": historical_bouts.height,
            "ambiguous_same_date_ordering": historical_bouts.filter(
                pl.col("ordering_confidence") == "ambiguous_same_date"
            ).height,
        },
        "phase_3b1": {
            "prefight_fighter_history": prefight_history.height,
            "cold_starts": prefight_history.filter(pl.col("cold_start")).height,
        },
        "phase_3b2a": {"fighter_bout_performance": performance.height},
        "phase_3b2b": {"prefight_performance_history": prefight_performance.height},
        "phase_3c1": {"pairwise_features": pairwise.height},
        "phase_3c2": {
            "model_ready_binary": model_ready.height,
            "excluded_draw_bout_ids": sorted(
                pairwise.filter(pl.col("is_draw"))["canonical_bout_id"].to_list()
            ),
            "excluded_no_contest_bout_ids": sorted(
                pairwise.filter(pl.col("is_no_contest"))["canonical_bout_id"].to_list()
            ),
        },
        "outputs": {k: str(v) for k, v in paths.items()},
    }
    return report


def _fighter(name: str, context: str) -> tuple[str, str]:
    """Return the accepted Phase 1 source-normalized identity; never apply authorities."""
    key = normalize_fighter_alias(name).normalized_value
    if key == "bruno silva":
        key += "|" + ("flyweight" if "flyweight" in context.casefold() else "middleweight")
    if key == "roldan sangcha an":
        return str(uuid5(NAMESPACE_URL, "fighter:roldan-sangcha-an")), "Roldan Sangcha-an"
    return str(uuid5(NAMESPACE_URL, "fighter:" + key)), name.strip().title()


def _canonical_fighter(name: str, context: str) -> tuple[str, str, str]:
    """Return a Phase 2A authority-layer identity without changing Phase 1 groups."""
    key = identity_context_key(name, context)
    display_name = "Roldan Sangcha-an" if key == "roldan sangcha an" else name.strip().title()
    return str(uuid5(NAMESPACE_URL, "fighter:" + key)), display_name, key


def _alias_observation(
    source_name: str,
    source_row_id: str,
    raw_fighter_name: str,
    source_fighter_id: str,
    canonical_fighter_id: str,
) -> dict[str, str]:
    return {
        "source_name": source_name,
        "source_schema_version": (
            "completed-bouts-v1" if source_name == "ultimate" else "stats-raw-v1"
        ),
        "source_row_id": source_row_id,
        "raw_fighter_name": raw_fighter_name,
        "source_fighter_id": source_fighter_id,
        "canonical_fighter_id": canonical_fighter_id,
    }


def _canonical_fighter_row(
    *,
    fighter_id: str,
    display_name: str,
    context_key: str,
    bruno_authority: AuthorityRecord,
    roldan_authority: AuthorityRecord,
) -> dict[str, str | None]:
    """Return derived fighter metadata without changing any source alias values."""
    if context_key.startswith("bruno silva|"):
        authority = bruno_authority
        kind = "reviewed_homonym_preservation"
        discriminator = context_key.rsplit("|", maxsplit=1)[1]
    elif context_key == "roldan sangcha an":
        authority = roldan_authority
        kind = "reviewed_alias_consolidation"
        discriminator = None
    else:
        authority = None
        kind = "deterministic_normalization"
        discriminator = None
    return {
        "canonical_fighter_id": fighter_id,
        "canonical_display_name": display_name,
        "identity_context_key": context_key,
        "identity_discriminator": discriminator,
        "authority_kind": kind,
        "authority_id": authority.authority_id if authority else None,
        "ledger_identifier": authority.ledger_identifier if authority else None,
        "source_evidence_sha256": (
            authority.payload["source_evidence_sha256"] if authority else None
        ),
    }


def _bout(
    record_key: str,
    source: str,
    fight_date: str,
    a: str,
    b: str,
    outcome: str,
    method: str,
    finish_round: int | None,
    schedule: str,
    event: str | None,
    location: str | None,
) -> dict[str, object]:
    first, second = sorted((a, b))
    return {
        "canonical_bout_id": content_sha256(f"{fight_date}|{first}|{second}".encode()),
        "source": source,
        "source_record_key": record_key,
        "fight_date": date.fromisoformat(fight_date),
        "fighter_a_id": first,
        "fighter_b_id": second,
        "outcome": outcome,
        "method": method,
        "finish_round": finish_round,
        "scheduled_format": schedule,
        "event_name": event,
        "location": location,
    }


def _crosswalk(
    source: str,
    row_id: str,
    bout: dict[str, object],
    red: str,
    blue: str,
    classification: str,
) -> dict[str, object]:
    return {
        "source_name": source,
        "source_schema_version": "completed-bouts-v1" if source == "ultimate" else "stats-raw-v1",
        "source_row_id": row_id,
        "source_file_sha256": "recorded_in_materialization_manifest",
        "canonical_bout_id": bout["canonical_bout_id"],
        "canonical_fighter_a_id": bout["fighter_a_id"],
        "canonical_fighter_b_id": bout["fighter_b_id"],
        "source_fighter_a_name": red,
        "source_fighter_b_name": blue,
        "source_orientation_to_canonical": "resolved",
        "reconciliation_classification": classification,
        "reconciliation_record_id": str(bout["canonical_bout_id"]),
        "materialization_run_id": "m3-v6-phase1",
    }


def _features(frame: pl.DataFrame) -> pl.DataFrame:
    rows = []
    hist: defaultdict[str, list[str]] = defaultdict(list)
    for _d, same in frame.group_by("fight_date", maintain_order=True):
        for r in same.iter_rows(named=True):
            a, b = r["fighter_a_id"], r["fighter_b_id"]
            rows.append(
                {
                    "canonical_bout_id": r["canonical_bout_id"],
                    "fight_date": r["fight_date"],
                    "fighter_a_id": a,
                    "fighter_b_id": b,
                    "red_prior_bouts": len(hist[a]),
                    "blue_prior_bouts": len(hist[b]),
                    "difference_prior_bouts": len(hist[a]) - len(hist[b]),
                }
            )
        for r in same.iter_rows(named=True):
            hist[r["fighter_a_id"]].append(str(r["outcome"]))
            hist[r["fighter_b_id"]].append(str(r["outcome"]))
    return pl.DataFrame(rows)


def _jsonl(path: Path) -> list[dict[str, str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _iso(v: str) -> str:
    d, m, y = v.split("/")
    return f"{y}-{m}-{d}"


def _bout_key(d: str, a: str, b: str) -> tuple[str, tuple[str, str]]:
    values = sorted(
        (normalize_fighter_alias(a).normalized_value, normalize_fighter_alias(b).normalized_value)
    )
    return d, (values[0], values[1])


def _int(v: str) -> int | None:
    return int(float(v)) if v else None


def resolve_m3_current_generation(output_dir: Path) -> Path:
    """Resolve the atomically published M3 generation without exposing staging data."""
    pointer = output_dir / _CURRENT_GENERATION_POINTER
    if not pointer.exists():
        raise FileNotFoundError(f"M3 current-generation pointer is missing: {pointer}")
    pointer_payload = cast(dict[str, str], json.loads(pointer.read_text(encoding="utf-8")))
    generation_id = pointer_payload["generation_id"]
    generation = output_dir / _GENERATION_DIRECTORY / generation_id
    if not generation.is_dir():
        raise FileNotFoundError(f"M3 current generation is missing: {generation_id}")
    return generation


def materialize_m3_v6(
    *,
    ultimate_csv: Path,
    datalab_csv: Path,
    v6_dir: Path,
    output_dir: Path,
    failure_injection: str | None = None,
) -> dict[str, object]:
    """Stage, validate, and atomically publish one complete immutable M3 generation."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generation_root = output_dir / _GENERATION_DIRECTORY
    generation_root.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".m3-stage-", dir=output_dir))
    promoted_generation: Path | None = None
    try:
        report = _build_m3_artifact_set(
            ultimate_csv=ultimate_csv,
            datalab_csv=datalab_csv,
            v6_dir=v6_dir,
            output_dir=stage,
        )
        if failure_injection == "after_staging_before_validation":
            raise RuntimeError("injected failure after staging")
        provenance, manifest, generation_id = _write_phase2c_artifacts(
            stage=stage,
            output_root=output_dir,
            ultimate_csv=ultimate_csv,
            datalab_csv=datalab_csv,
            v6_dir=v6_dir,
            report=report,
        )
        _write_final_acceptance_report(
            stage=stage,
            manifest=manifest,
            generation_id=generation_id,
        )
        _validate_phase2c_generation(
            stage=stage,
            output_root=output_dir,
            v6_dir=v6_dir,
            provenance=provenance,
            manifest=manifest,
            generation_id=generation_id,
        )
        if failure_injection == "after_validation_before_commit":
            raise RuntimeError("injected failure after validation")
        final_generation = generation_root / generation_id
        created_generation = False
        if final_generation.exists():
            _validate_existing_generation(final_generation, stage)
            shutil.rmtree(stage)
        else:
            os.replace(stage, final_generation)
            promoted_generation = final_generation
            created_generation = True
        if failure_injection == "during_publication_before_pointer":
            if created_generation:
                shutil.rmtree(final_generation)
                promoted_generation = None
            raise RuntimeError("injected failure during publication")
        pointer_payload = (
            json.dumps(
                {"generation_id": generation_id, "schema_version": M3_PHASE2C_SCHEMA_VERSION},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        pointer_temp = output_dir / f".{_CURRENT_GENERATION_POINTER}.tmp"
        pointer_temp.write_text(pointer_payload, encoding="utf-8")
        os.replace(pointer_temp, output_dir / _CURRENT_GENERATION_POINTER)
        report["phase_2c"] = {
            "generation_id": generation_id,
            "provenance_rows": provenance.height,
            "provenance_covered_rows": 150162,
            "provenance_denominator": 150162,
            "validation_status": "passed",
        }
        outputs = cast(dict[str, str], report["outputs"])
        outputs.clear()
        outputs.update(
            {
                report_key: str(final_generation / artifact_name)
                for artifact_name, report_key in _PUBLISHED_ARTIFACTS
            }
        )
        outputs.update(
            {
                "provenance": str(final_generation / "m3_normalized_provenance.parquet"),
                "manifest": str(final_generation / "m3_phase2_manifest.json"),
                "final_acceptance_report": str(
                    final_generation / "m3_final_acceptance_report.json"
                ),
                "generation": str(final_generation),
            }
        )
        return report
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if (
            failure_injection
            and promoted_generation is not None
            and not (output_dir / _CURRENT_GENERATION_POINTER).exists()
        ):
            shutil.rmtree(promoted_generation)


def _write_phase2c_artifacts(
    *,
    stage: Path,
    output_root: Path,
    ultimate_csv: Path,
    datalab_csv: Path,
    v6_dir: Path,
    report: dict[str, object],
) -> tuple[pl.DataFrame, dict[str, object], str]:
    index = load_authority_index(v6_dir)
    provenance = _build_normalized_provenance(
        stage=stage,
        ultimate_csv=ultimate_csv,
        datalab_csv=datalab_csv,
        index=index,
    )
    provenance.write_parquet(stage / "m3_normalized_provenance.parquet")
    generation_id = _deterministic_generation_id(
        ultimate_csv=ultimate_csv, datalab_csv=datalab_csv, v6_dir=v6_dir
    )
    manifest = _phase2_manifest(
        stage=stage,
        provenance=provenance,
        generation_id=generation_id,
        ultimate_csv=ultimate_csv,
        datalab_csv=datalab_csv,
        v6_dir=v6_dir,
        report=report,
    )
    (stage / "m3_phase2_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return provenance, manifest, generation_id


def _write_final_acceptance_report(
    *, stage: Path, manifest: dict[str, object], generation_id: str
) -> None:
    """Write the generation-scoped, non-self-referential M3 acceptance evidence."""
    artifacts = cast(dict[str, dict[str, object]], manifest["artifacts"])
    pairwise = pl.read_parquet(stage / "m3_prefight_pairwise_features.parquet")
    model_ready = pl.read_parquet(stage / "m3_model_ready_binary.parquet")
    provenance = pl.read_parquet(stage / "m3_normalized_provenance.parquet")
    model_metadata = cast(dict[str, object], manifest["phase_3c2"])
    feature_columns = cast(list[str], model_metadata["prediction_safe_feature_columns"])
    float_columns = [
        name for name, dtype in model_ready.schema.items() if dtype in {pl.Float32, pl.Float64}
    ]
    invalid_float_count = sum(
        model_ready.filter(pl.col(name).is_not_null() & ~pl.col(name).is_finite()).height
        for name in float_columns
    )
    missingness_mismatch_count = sum(
        model_ready.filter(
            pl.col(f"{name.removesuffix('_missing')}_missing")
            != pl.col(name.removesuffix("_missing")).is_null()
        ).height
        for name in feature_columns
        if name.endswith("_missing")
    )
    artifact_rows = {name: cast(int, metadata["row_count"]) for name, metadata in artifacts.items()}
    model_rows = model_ready.height
    excluded_draws = pairwise.filter(pl.col("is_draw")).height
    excluded_no_contests = pairwise.filter(pl.col("is_no_contest")).height
    payload: dict[str, object] = {
        "acceptance_schema_version": "m3-final-acceptance-v1",
        "generation_id": generation_id,
        "artifact_inventory": artifacts,
        "raw_sources": manifest["raw_sources"],
        "authority_ledgers": manifest["authority_ledgers"],
        "authority_resolution": manifest["authority_resolution"],
        "cardinalities": {
            "artifact_rows": artifact_rows,
            "canonical_bouts": artifact_rows["m3_canonical_historical_bouts.parquet"],
            "canonical_fighters": artifact_rows["m3_canonical_fighters.parquet"],
            "provenance_denominator": sum(
                value
                for name, value in artifact_rows.items()
                if name != "m3_normalized_provenance.parquet"
            ),
        },
        "model_ready": {
            "row_count": model_rows,
            "column_count": model_ready.width,
            "feature_count": len(feature_columns),
            "feature_columns": feature_columns,
            "positive_target_count": model_ready.filter(pl.col("target_fighter_a_won") == 1).height,
            "negative_target_count": model_ready.filter(pl.col("target_fighter_a_won") == 0).height,
            "excluded_draw_count": excluded_draws,
            "excluded_no_contest_count": excluded_no_contests,
            "eligibility_equation": (
                f"{pairwise.height} - {excluded_draws} - {excluded_no_contests} = {model_rows}"
            ),
        },
        "provenance": manifest["provenance"],
        "audit": {
            "unresolved_conflict_count": manifest["unresolved_conflict_count"],
            "invalid_model_float_count": invalid_float_count,
            "missingness_mismatch_count": missingness_mismatch_count,
            "target_null_count": model_ready.filter(
                pl.col("target_fighter_a_won").is_null()
            ).height,
            "provenance_orphan_count": provenance.filter(
                pl.col("output_artifact").is_null() | pl.col("output_row_key").is_null()
            ).height,
        },
        "verification_contract": {
            "deterministic_json": "sorted_keys_compact_utf8_no_timestamp_or_absolute_path",
            "atomic_publication_failure_injections": [
                "after_staging_before_validation",
                "after_validation_before_commit",
                "during_publication_before_pointer",
            ],
            "test_module": "tests/data/test_m3_final_acceptance.py",
        },
        "validation_status": "passed",
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    (stage / "m3_final_acceptance_report.json").write_bytes((serialized + "\n").encode())


def _build_normalized_provenance(
    *, stage: Path, ultimate_csv: Path, datalab_csv: Path, index: AuthorityIndex
) -> pl.DataFrame:
    raw_sources = {
        "ultimate": _raw_source_descriptor(ultimate_csv, "completed-bouts-v1"),
        "ufc-datalab": _raw_source_descriptor(datalab_csv, "stats-raw-v1"),
    }
    rows: list[dict[str, str | None]] = []
    reconciliation_by_bout = {
        str(record["canonical_bout_id"]): record
        for record in pl.read_parquet(stage / "m3_bout_reconciliation.parquet").to_dicts()
    }
    for artifact_name, _ in _PUBLISHED_ARTIFACTS:
        frame = pl.read_parquet(stage / artifact_name)
        for record in frame.to_dicts():
            output_key = _artifact_row_key(artifact_name, record)
            rows.append(
                _provenance_row(
                    artifact_name=artifact_name,
                    output_row_key=output_key,
                    lineage_type="deterministic_materialization_lineage",
                    deterministic_rule_id="m3.phase2.materialization.v1",
                )
            )
            _append_special_provenance(
                rows=rows,
                artifact_name=artifact_name,
                output_row_key=output_key,
                record=record,
                raw_sources=raw_sources,
                index=index,
                reconciliation_by_bout=reconciliation_by_bout,
            )
    frame = pl.DataFrame(rows, schema=_PROVENANCE_SCHEMA).with_columns(
        pl.struct(pl.all())
        .map_elements(lambda value: _provenance_evidence_hash(value), return_dtype=pl.String)
        .alias("evidence_sha256")
    )
    return frame.sort(["output_artifact", "output_row_key", "lineage_type", "source_dataset"])


def _append_special_provenance(
    *,
    rows: list[dict[str, str | None]],
    artifact_name: str,
    output_row_key: str,
    record: dict[str, object],
    raw_sources: dict[str, dict[str, str]],
    index: AuthorityIndex,
    reconciliation_by_bout: dict[str, dict[str, object]],
) -> None:
    def raw(source: str, row_id: str) -> None:
        descriptor = raw_sources[source]
        rows.append(
            _provenance_row(
                artifact_name=artifact_name,
                output_row_key=output_row_key,
                lineage_type="raw_source_lineage",
                source_dataset=source,
                source_schema_version=descriptor["schema_version"],
                source_row_id=row_id,
                raw_artifact_path=descriptor["path"],
                raw_artifact_sha256=descriptor["sha256"],
                ingestion_reference=descriptor["ingestion_reference"],
            )
        )

    def authority(
        authority_id: object,
        ledger_identifier: object,
        lineage_type: str = "direct_reviewer_authority",
    ) -> None:
        if authority_id is None:
            return
        identifier = str(authority_id)
        ledger = str(ledger_identifier)
        resolved = index.resolve(identifier, ledger)
        rows.append(
            _provenance_row(
                artifact_name=artifact_name,
                output_row_key=output_row_key,
                lineage_type=lineage_type,
                authority_id=resolved.authority_id,
                authority_ledger_identifier=resolved.ledger_identifier,
                authority_decision_reference=resolved.authority_id,
            )
        )

    if artifact_name == "m3_source_bout_crosswalk.parquet":
        raw(str(record["source_name"]), str(record["source_row_id"]))
    elif artifact_name == "m3_canonical_fighter_aliases.parquet":
        raw(str(record["source_name"]), str(record["source_row_id"]))
        authority(
            record.get("authority_id"),
            record.get("ledger_identifier"),
            "authority_derived_identity_lineage",
        )
    elif artifact_name == "m3_canonical_fighters.parquet":
        authority(
            record.get("authority_id"),
            record.get("ledger_identifier"),
            "authority_derived_identity_lineage",
        )
    elif artifact_name == "m3_taxonomy_authorities.parquet":
        authority(
            record.get("authority_id"),
            record.get("ledger_identifier"),
            "authority_derived_taxonomy_lineage",
        )
    elif artifact_name == "m3_bout_reconciliation.parquet":
        if record.get("ultimate_source_row_id"):
            raw("ultimate", str(record["ultimate_source_row_id"]))
        if record.get("ufc_datalab_source_row_id"):
            raw("ufc-datalab", str(record["ufc_datalab_source_row_id"]))
        authority(record.get("outcome_authority_id"), record.get("authority_ledger_identifier"))
    elif artifact_name == "m3_canonical_historical_bouts.parquet":
        rows.append(
            _provenance_row(
                artifact_name=artifact_name,
                output_row_key=output_row_key,
                lineage_type="upstream_artifact_lineage",
                upstream_artifact="m3_bout_reconciliation.parquet",
                upstream_row_key=output_row_key,
                deterministic_rule_id="m3.phase3a.canonical_historical_projection.v1",
            )
        )
        # The reconciliation row provides the only outcome authority. Raw
        # lineage is duplicated here solely to make this artifact independently
        # auditable without using any post-fight source fields as features.
        reconciliation = reconciliation_by_bout[output_row_key]
        if reconciliation["ultimate_source_row_id"]:
            raw("ultimate", str(reconciliation["ultimate_source_row_id"]))
        if reconciliation["ufc_datalab_source_row_id"]:
            raw("ufc-datalab", str(reconciliation["ufc_datalab_source_row_id"]))
        authority(record.get("outcome_authority_id"), record.get("authority_ledger_identifier"))
    elif artifact_name == "m3_prefight_fighter_history.parquet":
        rows.extend(
            (
                _provenance_row(
                    artifact_name=artifact_name,
                    output_row_key=output_row_key,
                    lineage_type="upstream_artifact_lineage",
                    upstream_artifact="m3_canonical_historical_bouts.parquet",
                    upstream_row_key=str(record["canonical_bout_id"]),
                    deterministic_rule_id="m3.phase3b1.target_bout_lineage.v1",
                ),
                _provenance_row(
                    artifact_name=artifact_name,
                    output_row_key=output_row_key,
                    lineage_type="upstream_artifact_lineage",
                    upstream_artifact="m3_canonical_fighters.parquet",
                    upstream_row_key=str(record["canonical_fighter_id"]),
                    deterministic_rule_id="m3.phase3b1.canonical_fighter_lineage.v1",
                ),
                _provenance_row(
                    artifact_name=artifact_name,
                    output_row_key=output_row_key,
                    lineage_type="deterministic_aggregate_history_lineage",
                    upstream_artifact="m3_canonical_historical_bouts.parquet",
                    upstream_row_key=str(record["snapshot_evidence_sha256"]),
                    deterministic_rule_id=_PREFIGHT_CUTOFF_POLICY,
                ),
            )
        )
    elif artifact_name == "m3_fighter_bout_performance.parquet":
        rows.extend(
            (
                _provenance_row(
                    artifact_name=artifact_name,
                    output_row_key=output_row_key,
                    lineage_type="upstream_artifact_lineage",
                    upstream_artifact="m3_canonical_historical_bouts.parquet",
                    upstream_row_key=str(record["canonical_bout_id"]),
                    deterministic_rule_id=_PERFORMANCE_POLICY_ID,
                ),
                _provenance_row(
                    artifact_name=artifact_name,
                    output_row_key=output_row_key,
                    lineage_type="upstream_artifact_lineage",
                    upstream_artifact="m3_canonical_fighters.parquet",
                    upstream_row_key=str(record["canonical_fighter_id"]),
                    deterministic_rule_id=_PERFORMANCE_POLICY_ID,
                ),
            )
        )
        if record.get("ultimate_source_row_id"):
            raw("ultimate", str(record["ultimate_source_row_id"]))
        if record.get("ufc_datalab_source_row_id"):
            raw("ufc-datalab", str(record["ufc_datalab_source_row_id"]))
    elif artifact_name == "m3_prefight_performance_history.parquet":
        rows.extend(
            (
                _provenance_row(
                    artifact_name=artifact_name,
                    output_row_key=output_row_key,
                    lineage_type="upstream_artifact_lineage",
                    upstream_artifact="m3_fighter_bout_performance.parquet",
                    upstream_row_key=output_row_key,
                    deterministic_rule_id=_PREFIGHT_PERFORMANCE_POLICY_ID,
                ),
                _provenance_row(
                    artifact_name=artifact_name,
                    output_row_key=output_row_key,
                    lineage_type="upstream_artifact_lineage",
                    upstream_artifact="m3_canonical_fighters.parquet",
                    upstream_row_key=str(record["canonical_fighter_id"]),
                    deterministic_rule_id=_PREFIGHT_PERFORMANCE_POLICY_ID,
                ),
            )
        )
    elif artifact_name == "m3_prefight_pairwise_features.parquet":
        for upstream_artifact, fighter_id in (
            ("m3_canonical_historical_bouts.parquet", None),
            ("m3_prefight_fighter_history.parquet", record["canonical_fighter_a_id"]),
            ("m3_prefight_fighter_history.parquet", record["canonical_fighter_b_id"]),
            ("m3_prefight_performance_history.parquet", record["canonical_fighter_a_id"]),
            ("m3_prefight_performance_history.parquet", record["canonical_fighter_b_id"]),
        ):
            upstream_key = (
                output_row_key if fighter_id is None else f"{output_row_key}:{fighter_id}"
            )
            rows.append(
                _provenance_row(
                    artifact_name=artifact_name,
                    output_row_key=output_row_key,
                    lineage_type="upstream_artifact_lineage",
                    upstream_artifact=upstream_artifact,
                    upstream_row_key=upstream_key,
                    deterministic_rule_id=_PAIRWISE_FEATURE_SCHEMA_VERSION,
                )
            )
    elif artifact_name == "m3_model_ready_binary.parquet":
        for upstream_artifact, upstream_key in (
            ("m3_prefight_pairwise_features.parquet", output_row_key),
            ("m3_canonical_fighters.parquet", str(record["canonical_fighter_a_id"])),
            ("m3_canonical_fighters.parquet", str(record["canonical_fighter_b_id"])),
        ):
            rows.append(
                _provenance_row(
                    artifact_name=artifact_name,
                    output_row_key=output_row_key,
                    lineage_type="upstream_artifact_lineage",
                    upstream_artifact=upstream_artifact,
                    upstream_row_key=upstream_key,
                    deterministic_rule_id=_MODEL_READY_PROJECTION_POLICY_ID,
                )
            )
    elif artifact_name == "m3_reviewed_exclusions.parquet":
        raw("ultimate", str(record["source_row_id"]))
        authority(record.get("authority_id"), record.get("ledger_identifier"))
    elif artifact_name == "m3_duplicate_collapses.parquet":
        raw("ufc-datalab", str(record["duplicate_source_row_id"]))
        raw("ufc-datalab", str(record["retained_source_row_id"]))
        rows.append(
            _provenance_row(
                artifact_name=artifact_name,
                output_row_key=output_row_key,
                lineage_type="deterministic_duplicate_collapse_lineage",
                deterministic_rule_id=str(record["deterministic_rule_id"]),
            )
        )
    elif artifact_name == "m3_semantic_bout_groups.parquet":
        sources = cast(list[object], record["sources"])
        source_rows = cast(list[object], record["source_rows"])
        for source, row_id in zip(sources, source_rows, strict=True):
            raw(str(source), str(row_id))
            rows.append(
                _provenance_row(
                    artifact_name=artifact_name,
                    output_row_key=output_row_key,
                    lineage_type="upstream_artifact_lineage",
                    upstream_artifact="m3_source_bout_crosswalk.parquet",
                    upstream_row_key=f"{source}:{row_id}",
                )
            )


def _provenance_row(**values: str | None) -> dict[str, str | None]:
    if "artifact_name" in values:
        values["output_artifact"] = values.pop("artifact_name")
    row: dict[str, str | None] = {name: None for name in _PROVENANCE_SCHEMA}
    row.update(
        {
            "output_schema_version": M3_PHASE2C_SCHEMA_VERSION,
            "transformation_schema_version": M3_PHASE2C_SCHEMA_VERSION,
            "evidence_sha256": "",
        }
    )
    row.update(values)
    return row


def _provenance_evidence_hash(record: dict[str, object]) -> str:
    payload = {key: value for key, value in sorted(record.items()) if key != "evidence_sha256"}
    return content_sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def _artifact_row_key(artifact_name: str, record: dict[str, object]) -> str:
    if artifact_name == "m3_source_bout_crosswalk.parquet":
        return f"{record['source_name']}:{record['source_row_id']}"
    if artifact_name == "m3_canonical_fighter_aliases.parquet":
        return f"{record['source_name']}:{record['source_row_id']}:{record['raw_fighter_name']}"
    if artifact_name in {
        "m3_semantic_bout_groups.parquet",
        "m3_bout_reconciliation.parquet",
        "m3_canonical_historical_bouts.parquet",
        "m3_duplicate_collapses.parquet",
    }:
        return str(record["canonical_bout_id"])
    if artifact_name == "m3_prefight_fighter_history.parquet":
        return f"{record['canonical_bout_id']}:{record['canonical_fighter_id']}"
    if artifact_name == "m3_fighter_bout_performance.parquet":
        return f"{record['canonical_bout_id']}:{record['canonical_fighter_id']}"
    if artifact_name == "m3_prefight_performance_history.parquet":
        return f"{record['canonical_bout_id']}:{record['canonical_fighter_id']}"
    if artifact_name == "m3_prefight_pairwise_features.parquet":
        return str(record["canonical_bout_id"])
    if artifact_name == "m3_model_ready_binary.parquet":
        return str(record["canonical_bout_id"])
    if artifact_name == "m3_canonical_fighters.parquet":
        return str(record["canonical_fighter_id"])
    if artifact_name == "m3_taxonomy_authorities.parquet":
        return str(record["authority_id"])
    if artifact_name == "m3_reviewed_exclusions.parquet":
        return f"{record['source_name']}:{record['source_row_id']}"
    return content_sha256(json.dumps(record, sort_keys=True, default=str).encode())


def _raw_source_descriptor(path: Path, schema_version: str) -> dict[str, str]:
    return {
        "path": _repository_relative(path),
        "schema_version": schema_version,
        "sha256": content_sha256(path.read_bytes()),
        "ingestion_reference": f"immutable-local-source:{_repository_relative(path)}",
    }


def _repository_relative(path: Path) -> str:
    root = Path(__file__).resolve().parents[4]
    return path.resolve().relative_to(root).as_posix()


def _deterministic_generation_id(*, ultimate_csv: Path, datalab_csv: Path, v6_dir: Path) -> str:
    """Return a stable content address for the complete Phase 2 publication."""
    inputs = {
        "schema_version": M3_PHASE2C_SCHEMA_VERSION,
        "materializer_code_sha256": content_sha256(Path(__file__).read_bytes()),
        "raw_sources": [
            _raw_source_descriptor(ultimate_csv, "completed-bouts-v1"),
            _raw_source_descriptor(datalab_csv, "stats-raw-v1"),
        ],
        "authority_ledgers": _ledger_descriptors(v6_dir),
    }
    digest = content_sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode())
    return f"m3-{digest[:24]}"


def _ledger_descriptors(v6_dir: Path) -> list[dict[str, object]]:
    ledgers = (
        (V6_LEDGER_IDENTIFIER, v6_dir / "m3_imported_decisions.jsonl"),
        (
            SUPPLEMENTAL_LEDGER_IDENTIFIER,
            v6_dir / "authority-migration-v1/m3_supplemental_legacy_authorities.jsonl",
        ),
    )
    return [
        {
            "identifier": identifier,
            "path": _repository_relative(path),
            "record_count": len(_jsonl(path)),
            "sha256": content_sha256(path.read_bytes()),
        }
        for identifier, path in ledgers
    ]


def _artifact_metadata(path: Path) -> dict[str, object]:
    frame = pl.read_parquet(path)
    return {
        "path": path.name,
        "row_count": frame.height,
        "column_count": frame.width,
        "schema": [{"name": name, "type": str(dtype)} for name, dtype in frame.schema.items()],
        "sha256": content_sha256(path.read_bytes()),
    }


def _provenance_coverage(
    *, stage: Path, provenance: pl.DataFrame
) -> tuple[dict[str, int], int, int]:
    expected = {
        artifact_name: pl.read_parquet(stage / artifact_name).height
        for artifact_name, _ in _PUBLISHED_ARTIFACTS
    }
    covered = {
        artifact_name: provenance.filter(pl.col("output_artifact") == artifact_name)
        .select("output_row_key")
        .n_unique()
        for artifact_name, _ in _PUBLISHED_ARTIFACTS
    }
    return covered, sum(covered.values()), sum(expected.values())


def _phase2_manifest(
    *,
    stage: Path,
    provenance: pl.DataFrame,
    generation_id: str,
    ultimate_csv: Path,
    datalab_csv: Path,
    v6_dir: Path,
    report: dict[str, object],
) -> dict[str, object]:
    coverage_by_artifact, covered_rows, denominator = _provenance_coverage(
        stage=stage, provenance=provenance
    )
    authority_rows = provenance.filter(pl.col("authority_id").is_not_null()).select(
        ["authority_id", "authority_ledger_identifier"]
    )
    authority_pairs = sorted({tuple(row) for row in authority_rows.iter_rows()})
    artifacts = {
        artifact_name: _artifact_metadata(stage / artifact_name)
        for artifact_name, _ in _PUBLISHED_ARTIFACTS
    }
    artifacts["m3_normalized_provenance.parquet"] = _artifact_metadata(
        stage / "m3_normalized_provenance.parquet"
    )
    phase_1 = cast(dict[str, object], report["phase_1"])
    phase_2a = cast(dict[str, object], report["phase_2a_authority"])
    phase_2b = cast(dict[str, object], report["phase_2b"])
    return {
        "artifact_set": [artifact_name for artifact_name, _ in _PUBLISHED_ARTIFACTS],
        "artifacts": artifacts,
        "authority_ledgers": _ledger_descriptors(v6_dir),
        "authority_resolution": {
            "denominator": len(authority_pairs),
            "numerator": len(authority_pairs),
        },
        "generation_id": generation_id,
        "manifest_schema_version": M3_PHASE2C_SCHEMA_VERSION,
        "materializer": {
            "code_sha256": content_sha256(Path(__file__).read_bytes()),
            "schema_version": M3_PHASE2C_SCHEMA_VERSION,
        },
        "phase_1": {
            "crosswalk_rows": phase_1["crosswalk_rows"],
            "semantic_groups": phase_1["semantic_groups"],
            "source_presence": {
                "dual_source": 6843,
                "ufc_datalab_only": 1893,
                "ultimate_only": 332,
            },
        },
        "phase_2a": {
            "canonical_fighters": report["canonical_fighter_count"],
            "canonical_aliases": pl.read_parquet(
                stage / "m3_canonical_fighter_aliases.parquet"
            ).height,
            "taxonomy_authorities": phase_2a["taxonomy_rows_emitted"],
        },
        "phase_2b": {
            "duplicate_collapses": phase_2b["duplicate_collapses"],
            "reconciliation_rows": phase_2b["reconciliation_rows"],
            "reviewed_exclusions": phase_2b["reviewed_exclusions"],
            "reviewed_outcomes": phase_2b["reviewed_outcomes_applied"],
            "unresolved_conflicts": phase_2b["unresolved_conflicts"],
        },
        "phase_3a": {
            "historical_bouts": cast(dict[str, object], report["phase_3a"])["historical_bouts"],
            "ambiguous_same_date_ordering": cast(dict[str, object], report["phase_3a"])[
                "ambiguous_same_date_ordering"
            ],
        },
        "phase_3b1": {
            "prefight_fighter_history": cast(dict[str, object], report["phase_3b1"])[
                "prefight_fighter_history"
            ],
            "cold_starts": cast(dict[str, object], report["phase_3b1"])["cold_starts"],
            "feature_policies": _PREFIGHT_FEATURE_POLICIES,
        },
        "phase_3b2a": {
            "fighter_bout_performance": cast(dict[str, object], report["phase_3b2a"])[
                "fighter_bout_performance"
            ],
            "supported_metrics": list(_PERFORMANCE_METRICS),
            "null_semantics": "null_unavailable_or_conflicted_zero_observed",
            "reconciliation_policy_id": _PERFORMANCE_POLICY_ID,
        },
        "phase_3b2b": {
            "prefight_performance_history": cast(dict[str, object], report["phase_3b2b"])[
                "prefight_performance_history"
            ],
            "cutoff_policy": _PREFIGHT_CUTOFF_POLICY,
            "feature_policy_id": _PREFIGHT_PERFORMANCE_POLICY_ID,
            "aggregation_windows": ["career", "recent_3", "recent_5", "days_365", "days_730"],
            "accuracy_denominator_policy": "summed_prior_attempts_strictly_gt_zero_else_null",
            "defense_denominator_policy": (
                "summed_prior_opponent_attempts_strictly_gt_zero_else_null"
            ),
            "pace_formulas": {
                "significant_strikes_landed_per_minute": (
                    "sum_eligible_landed * 60 / sum_eligible_completed_duration_seconds"
                ),
                "total_strikes_landed_per_minute": (
                    "sum_eligible_landed * 60 / sum_eligible_completed_duration_seconds"
                ),
                "takedown_attempts_per_15_minutes": (
                    "sum_eligible_attempts * 900 / sum_eligible_completed_duration_seconds"
                ),
                "submission_attempts_per_15_minutes": (
                    "sum_eligible_attempts * 900 / sum_eligible_completed_duration_seconds"
                ),
                "control_seconds_per_fight_minute": (
                    "sum_eligible_control_seconds / sum_eligible_completed_duration_seconds"
                ),
            },
            "missingness_policy": (
                "null_performance_does_not_supply_numerator_or_duration_denominator"
            ),
            "duration_exclusion_policy": (
                "only_positive_completed_duration_from_historical_finish_round_and_time; "
                "null_zero_negative_or_malformed_excluded; "
                "scheduled_duration_never_substituted"
            ),
        },
        "phase_3c1": {
            "pairwise_features": cast(dict[str, object], report["phase_3c1"])["pairwise_features"],
            "orientation_policy_id": _PAIRWISE_ORIENTATION_POLICY_ID,
            "feature_schema_version": _PAIRWISE_FEATURE_SCHEMA_VERSION,
            "feature_registry": list(_PAIRWISE_FEATURE_REGISTRY),
            "label_schema": ["canonical_outcome", "fighter_a_won", "is_draw", "is_no_contest"],
            "swap_behavior": "a_b_exchange_signed_differences_negate_labels_complement",
            "null_policy": "preserve_null_with_fighter_specific_indicator",
        },
        "phase_3c2": {
            "model_ready_schema_version": _MODEL_READY_SCHEMA_VERSION,
            "projection_policy_id": _MODEL_READY_PROJECTION_POLICY_ID,
            "metadata_columns": [
                "canonical_bout_id",
                "fight_date",
                "canonical_fighter_a_id",
                "canonical_fighter_b_id",
                "orientation_policy_id",
                "feature_schema_version",
                "pairwise_evidence_sha256",
            ],
            "prediction_safe_feature_columns": _model_ready_feature_columns(),
            "target_columns": ["target_fighter_a_won"],
            "feature_count": 130,
            "target_definition": "1_when_canonical_fighter_a_won_else_0_for_decisive_bouts",
            "eligibility_definition": "exclude_draws_and_no_contests_only",
            "excluded_draw_bout_ids": cast(dict[str, object], report["phase_3c2"])[
                "excluded_draw_bout_ids"
            ],
            "excluded_no_contest_bout_ids": cast(dict[str, object], report["phase_3c2"])[
                "excluded_no_contest_bout_ids"
            ],
            "null_policy": "preserve_source_nulls_without_imputation",
            "corner_swap_policy": "accepted_phase3c1_swap_with_binary_target_complement",
        },
        "provenance": {
            "coverage_by_artifact": coverage_by_artifact,
            "coverage_denominator": denominator,
            "coverage_percentage": 100 * covered_rows / denominator,
            "physical_rows": provenance.height,
            "unique_covered_rows": covered_rows,
        },
        "raw_sources": [
            _raw_source_descriptor(ultimate_csv, "completed-bouts-v1"),
            _raw_source_descriptor(datalab_csv, "stats-raw-v1"),
        ],
        "unresolved_conflict_count": report["unresolved_count"],
        "validation_status": "passed",
    }


def _validate_phase2c_generation(
    *,
    stage: Path,
    output_root: Path,
    v6_dir: Path,
    provenance: pl.DataFrame,
    manifest: dict[str, object],
    generation_id: str,
) -> None:
    """Fail closed before a staged generation can become consumer visible."""
    expected_rows = {
        artifact_name: pl.read_parquet(stage / artifact_name).height
        for artifact_name, _ in _PUBLISHED_ARTIFACTS
    }
    if expected_rows != {
        "m3_semantic_bout_groups.parquet": 9068,
        "m3_source_bout_crosswalk.parquet": 15911,
        "m3_canonical_fighters.parquet": 2790,
        "m3_canonical_fighter_aliases.parquet": 31822,
        "m3_taxonomy_authorities.parquet": 44,
        "m3_bout_reconciliation.parquet": 9068,
        "m3_reviewed_exclusions.parquet": 2,
        "m3_duplicate_collapses.parquet": 1,
        "m3_canonical_historical_bouts.parquet": 9068,
        "m3_prefight_fighter_history.parquet": 18136,
        "m3_fighter_bout_performance.parquet": 18136,
        "m3_prefight_performance_history.parquet": 18136,
        "m3_prefight_pairwise_features.parquet": 9068,
        "m3_model_ready_binary.parquet": 8912,
    }:
        raise ValueError("M3 accepted artifact cardinalities changed")
    if sum(expected_rows.values()) != 150162:
        raise ValueError("M3 provenance denominator changed")
    covered_by_artifact, covered_rows, denominator = _provenance_coverage(
        stage=stage, provenance=provenance
    )
    if covered_by_artifact != expected_rows or covered_rows != denominator:
        raise ValueError("normalized provenance does not cover every accepted output row")
    artifact_keys = {
        artifact_name: {
            _artifact_row_key(artifact_name, record)
            for record in pl.read_parquet(stage / artifact_name).to_dicts()
        }
        for artifact_name, _ in _PUBLISHED_ARTIFACTS
    }
    for row in (
        provenance.group_by("output_artifact")
        .agg(pl.col("output_row_key").unique().alias("keys"))
        .iter_rows(named=True)
    ):
        artifact_name = row["output_artifact"]
        keys = row["keys"]
        if artifact_name not in artifact_keys or not set(keys).issubset(
            artifact_keys[artifact_name]
        ):
            raise ValueError(
                f"normalized provenance contains an orphan output key: {artifact_name}"
            )
    raw_sources = cast(list[dict[str, object]], manifest["raw_sources"])
    for source in raw_sources:
        raw_path = Path(__file__).resolve().parents[4] / cast(str, source["path"])
        if content_sha256(raw_path.read_bytes()) != cast(str, source["sha256"]):
            raise ValueError("raw source checksum differs from manifest")
    index = load_authority_index(v6_dir)
    for authority_id, ledger_identifier in (
        provenance.filter(pl.col("authority_id").is_not_null())
        .select(["authority_id", "authority_ledger_identifier"])
        .unique()
        .iter_rows()
    ):
        index.resolve(authority_id, ledger_identifier)
    if manifest["generation_id"] != generation_id:
        raise ValueError("manifest generation ID mismatch")
    manifest_provenance = cast(dict[str, object], manifest["provenance"])
    if manifest_provenance["unique_covered_rows"] != 150162:
        raise ValueError("manifest provenance coverage mismatch")
    manifest_artifacts = cast(dict[str, dict[str, object]], manifest["artifacts"])
    for artifact_name, metadata in manifest_artifacts.items():
        artifact_path = stage / artifact_name
        if not artifact_path.is_file() or content_sha256(artifact_path.read_bytes()) != cast(
            str, metadata["sha256"]
        ):
            raise ValueError(f"manifest checksum mismatch: {artifact_name}")
    acceptance_path = stage / "m3_final_acceptance_report.json"
    acceptance_bytes = acceptance_path.read_bytes()
    accepted_payload = cast(dict[str, object], json.loads(acceptance_bytes))
    if acceptance_bytes != (
        json.dumps(accepted_payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    ):
        raise ValueError("final acceptance report is not canonical deterministic JSON")
    if accepted_payload["generation_id"] != generation_id:
        raise ValueError("final acceptance report generation ID mismatch")
    acceptance_inventory = cast(
        dict[str, dict[str, object]], accepted_payload["artifact_inventory"]
    )
    if acceptance_inventory != manifest_artifacts:
        raise ValueError("final acceptance report artifact inventory mismatch")
    if accepted_payload["provenance"] != manifest["provenance"]:
        raise ValueError("final acceptance report provenance mismatch")
    # The accepted direct artifacts remain untouched; a staged copy must be byte-identical.
    for artifact_name, _ in _PUBLISHED_ARTIFACTS:
        accepted = output_root / artifact_name
        if accepted.exists() and content_sha256(accepted.read_bytes()) != content_sha256(
            (stage / artifact_name).read_bytes()
        ):
            raise ValueError(f"accepted artifact bytes changed: {artifact_name}")


def _validate_existing_generation(existing: Path, staged: Path) -> None:
    expected = {path.name for path in staged.iterdir() if path.is_file()}
    actual = {path.name for path in existing.iterdir() if path.is_file()}
    if actual != expected:
        raise ValueError("existing generation has a different artifact set")
    for name in sorted(expected):
        if content_sha256((existing / name).read_bytes()) != content_sha256(
            (staged / name).read_bytes()
        ):
            raise ValueError(f"existing generation differs from deterministic replay: {name}")
