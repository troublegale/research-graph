"""Shared migrated relational fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from research_graph.pipelines.importer import import_csv
from research_graph.pipelines.seed import write_demo_csv
from research_graph.storage.database import make_engine, session_factory

ROOT = Path(__file__).resolve().parents[1]


def migration_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["database_url"] = url
    return config


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    url = "sqlite:///" + (tmp_path / "test.db").as_posix()
    command.upgrade(migration_config(url), "head")
    engine = make_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine, tmp_path: Path) -> Iterator[Session]:
    path = tmp_path / "demo.csv"
    write_demo_csv(path, 150)
    with session_factory(engine)() as session:
        import_csv(session, path)
        yield session
