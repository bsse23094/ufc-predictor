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
