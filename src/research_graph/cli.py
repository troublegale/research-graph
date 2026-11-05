"""Интерфейс командной строки ``rg``."""

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from research_graph import __version__
from research_graph.config import Settings, get_settings
from research_graph.logging_setup import setup_logging

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="rg",
    help="research-graph: project toolkit CLI.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def version() -> None:
    """Show the package version."""
    typer.echo(__version__)


def _format_summary(settings: Settings) -> list[str]:
    token = settings.masked_github_token
    rows = [
        ("github_token", f"set ({token})" if token else "not set"),
        ("data_dir", str(settings.data_dir)),
        ("data_dir exists", "yes" if settings.data_dir.is_dir() else "no"),
        ("log_level", settings.log_level),
        ("log_format", settings.log_format),
        ("request_timeout", f"{settings.request_timeout:g} s"),
        ("max_concurrency", str(settings.max_concurrency)),
    ]
    width = max(len(key) for key, _ in rows)
    return [f"{key:<{width}} : {value}" for key, value in rows]


@app.command("check-config")
def check_config(
    create_data_dir: Annotated[
        bool,
        typer.Option("--create-data-dir", help="Create data_dir if it does not exist."),
    ] = False,
) -> None:
    """Load settings, initialise logging and print a summary (secrets are masked)."""
    try:
        settings = get_settings()
    except ValidationError as exc:
        setup_logging("ERROR")
        logger.error("Invalid configuration: %d error(s)", exc.error_count())
        for error in exc.errors(include_input=False):
            field = ".".join(str(part) for part in error["loc"]) or "<root>"
            typer.echo(f"RG_{field.upper()}: {error['msg']}", err=True)
        raise typer.Exit(code=2) from None

    setup_logging(settings.log_level, settings.log_format)
    logger.info("Configuration loaded")

    if create_data_dir:
        path = settings.ensure_data_dir()
        logger.info("Data directory is ready: %s", path)

    typer.echo("Configuration summary:")
    for line in _format_summary(settings):
        typer.echo(f"  {line}")


@app.command()
def migrate() -> None:
    """Create/update the database using Alembic migrations."""
    from alembic import command
    from alembic.config import Config

    settings = get_settings()
    settings.ensure_data_dir()
    command.upgrade(Config("alembic.ini"), "head")


@app.command("import-data")
def import_data(source: Path, limit: Annotated[int | None, typer.Option(min=1)] = None) -> None:
    """Import raw Kaggle CSV with validation, deduplication and a run report."""
    from research_graph.pipelines.importer import import_csv
    from research_graph.storage.database import make_engine, session_factory

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)
    engine = make_engine(settings.database_url)
    try:
        with session_factory(engine)() as session:
            typer.echo(asdict(import_csv(session, source, limit)))
    finally:
        engine.dispose()


@app.command()
def seed() -> None:
    """Load synthetic demonstration listings (not real market observations)."""
    from research_graph.pipelines.seed import write_demo_csv

    path = get_settings().ensure_data_dir() / "demo.csv"
    write_demo_csv(path)
    import_data(path)


@app.command("prepare-data")
def prepare_data(
    source: Path,
    output: Path = Path("data/training.parquet"),
    size: Annotated[int, typer.Option(min=100)] = 50_000,
    seed: int = 42,
) -> None:
    """Stream the full CSV and sample latest unique listings to Parquet."""
    from research_graph.ml.dataset import prepare_dataset

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)
    typer.echo(prepare_dataset(source, output, size, seed))


@app.command()
def train(
    dataset: Path = Path("data/training.parquet"),
    output: Path | None = None,
    threads: Annotated[int | None, typer.Option(min=1, max=16)] = None,
    iterations: Annotated[int, typer.Option(min=1, max=5000)] = 800,
    seed: int = 42,
) -> None:
    """Compare Ridge/CatBoost locally; save the validation winner and test metrics."""
    from research_graph.ml.train import train_model

    settings = get_settings()
    typer.echo(
        train_model(
            dataset, output or settings.model_path, threads or settings.ml_threads, iterations, seed
        )
    )


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the API and web interface."""
    import uvicorn

    uvicorn.run("research_graph.api.app:create_app", factory=True, host=host, port=port)


@app.command("download-data")
def download_data(output: Path = Path("data/raw/all_regions.csv")) -> None:
    """Download the public Kaggle dataset; about 400 MB compressed / 2 GB CSV."""
    import shutil
    import urllib.request
    import zipfile

    output.parent.mkdir(parents=True, exist_ok=True)
    compressed = output.with_suffix(".zip.part")
    url = "https://www.kaggle.com/api/v1/datasets/download/ekibee/car-sales-information"
    with urllib.request.urlopen(url, timeout=120) as response, compressed.open("wb") as stream:
        shutil.copyfileobj(response, stream, length=1024 * 1024)
    pending = output.with_suffix(".csv.part")
    try:
        with (
            zipfile.ZipFile(compressed) as archive,
            archive.open("all_regions.csv") as source,
            pending.open("wb") as target,
        ):
            shutil.copyfileobj(source, target, length=1024 * 1024)
        pending.replace(output)
    finally:
        compressed.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)
    typer.echo(str(output))
