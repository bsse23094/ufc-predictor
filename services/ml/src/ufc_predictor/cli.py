"""Safe command-line entry point introduced in the foundation milestone."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from ufc_predictor import __version__
from ufc_predictor.config import MlSettings

app = typer.Typer(
    add_completion=False,
    help="UFC Predictor data and ML operations. Source commands unlock after their audit gate.",
)


@app.callback()
def main() -> None:
    """Provide a command group so `info` remains an explicit safe operation."""


@app.command()
def info() -> None:
    """Print safe foundation status without reading or writing data."""

    settings = MlSettings()
    typer.echo(f"ufc-predictor {__version__}")
    typer.echo(f"enabled_sources={','.join(settings.enabled_sources) or 'none'}")
    typer.echo("network ingestion is disabled; audited local-file commands remain explicit")


@app.command("ingest-kaggle-ultimate")
def ingest_kaggle_ultimate(
    incoming_directory: Annotated[
        Path,
        typer.Option(help="Ignored directory containing the manually downloaded ufc-master.csv."),
    ] = Path("data/incoming/ultimate-ufc-dataset"),
    raw_root: Annotated[Path, typer.Option()] = Path("data/raw"),
    interim_root: Annotated[Path, typer.Option()] = Path("data/interim"),
) -> None:
    """Ingest one explicitly downloaded CC BY 4.0 Kaggle CSV without network access."""

    from ufc_predictor.ingestion.kaggle_ultimate import ingest_local_kaggle_ultimate_dataset

    result = asyncio.run(
        ingest_local_kaggle_ultimate_dataset(
            incoming_directory=incoming_directory,
            raw_root=raw_root,
            interim_root=interim_root,
        )
    )
    summary = {
        "ingestion_run_id": result.execution.run.run_id,
        "state": result.execution.run.state.value,
        "replayed": result.replayed,
        "parquet_path": str(result.parquet_path) if result.parquet_path is not None else None,
        "manifest_path": str(result.manifest_path) if result.manifest_path is not None else None,
    }
    typer.echo(json.dumps(summary, sort_keys=True))
    if result.execution.run.state.value != "published":
        raise typer.Exit(code=2)


@app.command("ingest-ufc-datalab")
def ingest_ufc_datalab(
    input_file: Annotated[
        Path,
        typer.Option(help="Pinned local data/incoming/ufc-datalab/<commit>/stats_raw.csv file."),
    ],
    raw_root: Annotated[Path, typer.Option()] = Path("data/raw"),
    interim_root: Annotated[Path, typer.Option()] = Path("data/interim"),
) -> None:
    """Ingest one local UFC-DataLab raw stats CSV; no network is used."""

    from ufc_predictor.ingestion.ufc_datalab import ingest_local_ufc_datalab_stats

    result = ingest_local_ufc_datalab_stats(
        input_file=input_file, raw_root=raw_root, interim_root=interim_root
    )
    typer.echo(
        json.dumps(
            {
                "ingestion_run_id": result.ingestion_run_id,
                "state": result.state,
                "replayed": result.replayed,
                "parquet_path": str(result.parquet_path) if result.parquet_path else None,
                "manifest_path": str(result.manifest_path) if result.manifest_path else None,
                "issues": list(result.issues),
            },
            sort_keys=True,
        )
    )
    if result.state != "published":
        raise typer.Exit(code=2)


@app.command("build-m3-reviewer-packet")
def build_m3_reviewer_packet(
    review_root: Annotated[Path, typer.Option()] = Path("data/quarantine/reviews"),
    reconciliation_root: Annotated[Path, typer.Option()] = Path(
        "data/quarantine/reconciliation/ultimate_ufc_datalab/m3-reconciliation-v5"
    ),
    output_dir: Annotated[Path, typer.Option()] = Path("data/quarantine/reviews/m3"),
) -> None:
    """Create the deduplicated, non-mutating M3 reviewer packet."""

    from ufc_predictor.m3_reviewer_packet import generate_m3_reviewer_packet

    result = generate_m3_reviewer_packet(
        ultimate_identity_queue=review_root / "ultimate_identity_review.md",
        datalab_identity_queue=review_root / "ufc_datalab_identity_review.md",
        ultimate_taxonomy_queue=review_root / "ultimate_taxonomy_review.md",
        datalab_taxonomy_queue=review_root / "ufc_datalab_taxonomy_review.md",
        residual_outcome_conflicts=reconciliation_root / "residual_material_conflicts.jsonl",
        output_dir=output_dir,
    )
    typer.echo(
        json.dumps(
            {
                "identity_count": result.identity_count,
                "taxonomy_count": result.taxonomy_count,
                "outcome_count": result.outcome_count,
                "packet_path": str(result.packet_path),
            },
            sort_keys=True,
        )
    )


@app.command("import-m3-reviewer-decisions")
def import_m3_reviewer_decisions(
    decision_files: Annotated[
        list[Path], typer.Argument(help="Completed M3 decision CSV files from the reviewer packet.")
    ],
    packet_dir: Annotated[Path, typer.Option()] = Path("data/quarantine/reviews/m3"),
    ledger_path: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Validate and append human M3 decisions; never alter raw source data."""

    from ufc_predictor.m3_reviewer_packet import import_m3_reviewer_decisions as import_decisions

    result = import_decisions(
        packet_dir=packet_dir, decision_files=tuple(decision_files), ledger_path=ledger_path
    )
    typer.echo(
        json.dumps(
            {
                "applied": result.applied,
                "replayed": result.replayed,
                "ledger_path": str(result.ledger_path),
                "canonical_application": "not_performed",
            },
            sort_keys=True,
        )
    )


@app.command("build-m3-correction-packet")
def build_m3_correction_packet(
    ultimate_csv: Annotated[Path, typer.Option()] = Path(
        "data/incoming/ultimate-ufc-dataset/ufc-master.csv"
    ),
    datalab_csv: Annotated[Path, typer.Option()] = Path(
        "data/incoming/ufc-datalab/3268146c05211de9deab8b9b4c0bb4a954815f0b/stats_raw.csv"
    ),
    output_dir: Annotated[Path, typer.Option()] = Path("data/quarantine/reviews/m3-corrections-v6"),
    retire_manifest_path: Annotated[Path, typer.Option()] = Path(
        "data/quarantine/reviews/m3-corrections-v6/m3_retired_review_ids.json"
    ),
) -> None:
    """Generate replacement-only M3 review proposals for explicitly deferred items."""

    from ufc_predictor.m3_reviewer_packet import generate_m3_correction_packet

    result = generate_m3_correction_packet(
        ultimate_csv=ultimate_csv,
        datalab_csv=datalab_csv,
        output_dir=output_dir,
        retire_manifest_path=retire_manifest_path,
    )
    typer.echo(
        json.dumps(
            {
                "identity_replacement_id": result.identity_replacement_id,
                "taxonomy_replacement_count": result.taxonomy_replacement_count,
                "bout_review_count": result.bout_review_count,
                "proposed_exclusion_count": result.proposed_exclusion_count,
                "output_dir": str(result.output_dir),
            },
            sort_keys=True,
        )
    )


@app.command("prepare-m3-v6-reviewer-package")
def prepare_m3_v6_reviewer_package(
    outcome_source_csv: Annotated[Path, typer.Option()] = Path(
        "data/quarantine/reviews/m3/m3_outcome_conflict_decisions.csv"
    ),
    output_dir: Annotated[Path, typer.Option()] = Path("data/quarantine/reviews/m3-corrections-v6"),
) -> None:
    """Authorize the completed outcome decisions inside the closed v6 packet."""

    from ufc_predictor.m3_reviewer_packet import prepare_m3_v6_reviewer_package as prepare

    outcome_path = prepare(outcome_source_csv=outcome_source_csv, output_dir=output_dir)
    typer.echo(json.dumps({"outcome_template_path": str(outcome_path)}, sort_keys=True))


@app.command("validate-m3-v6-reviewer-package")
def validate_m3_v6_reviewer_package(
    packet_dir: Annotated[Path, typer.Option()] = Path("data/quarantine/reviews/m3-corrections-v6"),
) -> None:
    """Report v6 review completion without importing decisions or writing a ledger."""

    from ufc_predictor.m3_reviewer_packet import validate_m3_v6_reviewer_package as validate

    report = validate(packet_dir)
    typer.echo(
        json.dumps(
            {
                "identity": report.identity_count,
                "taxonomy_mappings": report.taxonomy_mapping_count,
                "null_policy": report.null_policy_count,
                "grouped_special_formats": report.special_format_count,
                "ultimate_four_round_confirmation": report.ultimate_four_round_count,
                "unresolved_bout_actions": report.unresolved_bout_count,
                "outcome_decisions": report.outcome_count,
                "total_required": report.total_required_count,
                "completed": report.completed_count,
                "valid_completed": report.valid_completed_count,
                "blank": report.blank_count,
                "complete": report.is_complete,
            },
            sort_keys=True,
        )
    )


@app.command("import-m3-v6-reviewer-decisions")
def import_m3_v6_reviewer_decisions(
    packet_dir: Annotated[Path, typer.Option()] = Path("data/quarantine/reviews/m3-corrections-v6"),
    ledger_path: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Atomically import the complete closed v6 packet; blank rows block import."""

    from ufc_predictor.m3_reviewer_packet import import_m3_reviewer_decisions as import_decisions

    decision_files = tuple(sorted(packet_dir.glob("*decisions.csv")))
    result = import_decisions(
        packet_dir=packet_dir,
        decision_files=decision_files,
        ledger_path=ledger_path,
        require_complete=True,
    )
    typer.echo(
        json.dumps(
            {
                "applied": result.applied,
                "replayed": result.replayed,
                "ledger_path": str(result.ledger_path),
                "canonical_application": "not_performed",
            },
            sort_keys=True,
        )
    )


@app.command("migrate-m3-legacy-authorities")
def migrate_m3_legacy_authorities(
    legacy_packet_dir: Annotated[Path, typer.Option()] = Path("data/quarantine/reviews/m3"),
    v6_packet_dir: Annotated[Path, typer.Option()] = Path(
        "data/quarantine/reviews/m3-corrections-v6"
    ),
    output_dir: Annotated[Path, typer.Option()] = Path(
        "data/quarantine/reviews/m3-corrections-v6/authority-migration-v1"
    ),
) -> None:
    """Create the immutable supplemental authority ledger from approved legacy rows."""

    from ufc_predictor.m3_reviewer_packet import migrate_m3_legacy_authorities as migrate

    report = migrate(
        legacy_identity_csv=legacy_packet_dir / "m3_identity_decisions.csv",
        legacy_taxonomy_csv=legacy_packet_dir / "m3_taxonomy_decisions.csv",
        legacy_packet_dir=legacy_packet_dir,
        v6_packet_dir=v6_packet_dir,
        output_dir=output_dir,
    )
    typer.echo(
        json.dumps(
            {
                "accepted_identity": report.accepted_identity_count,
                "accepted_taxonomy": report.accepted_taxonomy_count,
                "retired_or_superseded": report.retired_or_superseded_count,
                "rejected": report.rejected_count,
                "ledger_path": str(report.ledger_path),
                "report_path": str(report.report_path),
            },
            sort_keys=True,
        )
    )


@app.command("materialize-m3-v6")
def materialize_m3_v6(
    output_dir: Annotated[Path, typer.Option()] = Path("data/processed/m3-v6"),
) -> None:
    """Materialize derived canonical and leakage-safe M3 v6 outputs."""
    from ufc_predictor.m3_materialization import materialize_m3_v6 as materialize

    typer.echo(
        json.dumps(
            materialize(
                ultimate_csv=Path("data/incoming/ultimate-ufc-dataset/ufc-master.csv"),
                datalab_csv=Path(
                    "data/incoming/ufc-datalab/3268146c05211de9deab8b9b4c0bb4a954815f0b/stats_raw.csv"
                ),
                v6_dir=Path("data/quarantine/reviews/m3-corrections-v6"),
                output_dir=output_dir,
            ),
            sort_keys=True,
        )
    )


@app.command("materialize-m3")
def materialize_m3(
    ultimate_csv: Annotated[Path, typer.Option()] = Path(
        "data/incoming/ultimate-ufc-dataset/ufc-master.csv"
    ),
    datalab_csv: Annotated[Path, typer.Option()] = Path(
        "data/incoming/ufc-datalab/3268146c05211de9deab8b9b4c0bb4a954815f0b/stats_raw.csv"
    ),
    review_dir: Annotated[Path, typer.Option()] = Path("data/quarantine/reviews"),
    output_dir: Annotated[Path, typer.Option()] = Path("data/processed/m3-authority-v1"),
) -> None:
    """Materialize the closed M3 authority snapshot and pre-fight-only features."""

    from ufc_predictor.m3_materialization import materialize_m3_v6 as materialize

    result = materialize(
        ultimate_csv=ultimate_csv,
        datalab_csv=datalab_csv,
        v6_dir=review_dir / "m3-corrections-v6",
        output_dir=output_dir,
    )
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("train-m4-baselines")
def train_m4_baselines(
    m3_root: Annotated[Path, typer.Option()] = Path("data/processed/m3-v6"),
    output_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-baselines"),
) -> None:
    """Train fixed M4 Phase 1 baselines from the accepted M3 generation only."""

    from ufc_predictor.training.m4_baselines import run_m4_baseline_training

    result = run_m4_baseline_training(m3_root=m3_root, output_root=output_root)
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("train-m4-symmetry")
def train_m4_symmetry(
    m3_root: Annotated[Path, typer.Option()] = Path("data/processed/m3-v6"),
    phase1_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-baselines"),
    output_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase2-symmetry"),
) -> None:
    """Train deterministic M4 Phase 2 symmetry-aware candidates."""

    from ufc_predictor.training.m4_symmetry import run_m4_symmetry_training

    result = run_m4_symmetry_training(
        m3_root=m3_root, phase1_root=phase1_root, output_root=output_root
    )
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("train-m4-xgboost")
def train_m4_xgboost(
    m3_root: Annotated[Path, typer.Option()] = Path("data/processed/m3-v6"),
    phase1_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-baselines"),
    phase2_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase2-symmetry"),
    output_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase3a-xgboost"),
) -> None:
    """Train M4 Phase 3A regularized XGBoost candidates on rolling temporal folds."""

    from ufc_predictor.training.m4_xgboost import run_m4_xgboost_training

    result = run_m4_xgboost_training(
        m3_root=m3_root,
        phase1_root=phase1_root,
        phase2_root=phase2_root,
        output_root=output_root,
    )
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("train-m4-opponent-strength")
def train_m4_opponent_strength(
    m3_root: Annotated[Path, typer.Option()] = Path("data/processed/m3-v6"),
    phase1_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-baselines"),
    phase2_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase3a-xgboost"),
    output_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase3b1-opponent-strength"
    ),
) -> None:
    """Train M4 Phase 3B1 opponent-strength feature ablations."""

    from ufc_predictor.training.m4_opponent_strength import run_m4_opponent_strength_training

    result = run_m4_opponent_strength_training(
        m3_root=m3_root,
        phase1_root=phase1_root,
        phase2_root=phase2_root,
        phase3a_root=phase3a_root,
        output_root=output_root,
    )
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("train-m4-opponent-ablation")
def train_m4_opponent_ablation(
    m3_root: Annotated[Path, typer.Option()] = Path("data/processed/m3-v6"),
    phase1_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-baselines"),
    phase2_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase3a-xgboost"),
    phase3b1_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase3b1-opponent-strength"
    ),
    output_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase3b2-opponent-ablation"
    ),
) -> None:
    """Train M4 Phase 3B2 opponent-strength group ablations."""

    from ufc_predictor.training.m4_opponent_ablation import run_m4_opponent_ablation_training

    result = run_m4_opponent_ablation_training(
        m3_root=m3_root,
        phase1_root=phase1_root,
        phase2_root=phase2_root,
        phase3a_root=phase3a_root,
        phase3b1_root=phase3b1_root,
        output_root=output_root,
    )
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("train-m4-opponent-adjusted-performance")
def train_m4_opponent_adjusted_performance(
    m3_root: Annotated[Path, typer.Option()] = Path("data/processed/m3-v6"),
    phase1_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-baselines"),
    phase2_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase3a-xgboost"),
    phase3b1_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase3b1-opponent-strength"
    ),
    output_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase3c-opponent-adjusted-performance"
    ),
) -> None:
    """Train M4 Phase 3C opponent-adjusted performance packs."""

    from ufc_predictor.training.m4_opponent_adjusted_performance import (
        run_m4_opponent_adjusted_performance_training,
    )

    result = run_m4_opponent_adjusted_performance_training(
        m3_root=m3_root,
        phase1_root=phase1_root,
        phase2_root=phase2_root,
        phase3a_root=phase3a_root,
        phase3b1_root=phase3b1_root,
        output_root=output_root,
    )
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("train-m4-optuna")
def train_m4_optuna(
    m3_root: Annotated[Path, typer.Option()] = Path("data/processed/m3-v6"),
    phase1_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-baselines"),
    phase2_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase3a-xgboost"),
    phase3b1_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase3b1-opponent-strength"
    ),
    phase3c_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase3c-opponent-adjusted-performance"
    ),
    output_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase3d-optuna"),
) -> None:
    """Tune the frozen M4 Phase 3C champion pack with bounded Optuna trials."""

    from ufc_predictor.training.m4_optuna_tuning import run_m4_optuna_tuning

    result = run_m4_optuna_tuning(
        m3_root=m3_root,
        phase1_root=phase1_root,
        phase2_root=phase2_root,
        phase3a_root=phase3a_root,
        phase3b1_root=phase3b1_root,
        phase3c_root=phase3c_root,
        output_root=output_root,
    )
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("train-m4-calibration-blending")
def train_m4_calibration_blending(
    m3_root: Annotated[Path, typer.Option()] = Path("data/processed/m3-v6"),
    phase1_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-baselines"),
    phase2_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase3a-xgboost"),
    phase3b1_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase3b1-opponent-strength"
    ),
    phase3c_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase3c-opponent-adjusted-performance"
    ),
    phase3d_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase3d-optuna"),
    output_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase4a-calibration-blending"
    ),
) -> None:
    """Evaluate development-only calibration and fixed logistic/XGBoost blends."""

    from ufc_predictor.training.m4_calibration_blending import run_m4_calibration_blending

    result = run_m4_calibration_blending(
        m3_root=m3_root,
        phase1_root=phase1_root,
        phase2_root=phase2_root,
        phase3a_root=phase3a_root,
        phase3b1_root=phase3b1_root,
        phase3c_root=phase3c_root,
        phase3d_root=phase3d_root,
        output_root=output_root,
    )
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("evaluate-m4-confidence-coverage")
def evaluate_m4_confidence_coverage(
    m3_root: Annotated[Path, typer.Option()] = Path("data/processed/m3-v6"),
    phase1_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-baselines"),
    phase2_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase3a-xgboost"),
    phase3b1_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase3b1-opponent-strength"
    ),
    phase3c_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase3c-opponent-adjusted-performance"
    ),
    phase3d_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-phase3d-optuna"),
    phase4a_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase4a-calibration-blending"
    ),
    output_root: Annotated[Path, typer.Option()] = Path(
        "data/processed/m4-phase4b-confidence-coverage"
    ),
) -> None:
    """Evaluate fixed confidence coverage for the accepted Phase 3C champion."""

    from ufc_predictor.training.m4_confidence_coverage import run_m4_confidence_coverage

    result = run_m4_confidence_coverage(
        m3_root=m3_root,
        phase1_root=phase1_root,
        phase2_root=phase2_root,
        phase3a_root=phase3a_root,
        phase3b1_root=phase3b1_root,
        phase3c_root=phase3c_root,
        phase3d_root=phase3d_root,
        phase4a_root=phase4a_root,
        output_root=output_root,
    )
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("finalize-m4-champion")
def finalize_m4_champion(
    output_root: Annotated[Path, typer.Option()] = Path("data/processed/m4-final-champion"),
) -> None:
    """Publish the immutable M4 champion deployment bundle."""

    from ufc_predictor.training.m4_final_champion import run_m4_final_champion_bundle

    typer.echo(json.dumps(run_m4_final_champion_bundle(output_root=output_root), sort_keys=True))


@app.command("verify-m5-phase2-exhaustive-parity")
def verify_m5_phase2_exhaustive_parity() -> None:
    """Verify every accepted Phase 3C row against the M5 historical-exact route."""
    from ufc_predictor.inference.m5_champion import run_m5_phase2_exhaustive_parity

    typer.echo(json.dumps(run_m5_phase2_exhaustive_parity(), sort_keys=True))
