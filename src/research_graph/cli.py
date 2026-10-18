"""Интерфейс командной строки ``rg``."""

import logging
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
