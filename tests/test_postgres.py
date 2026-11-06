"""Real PostgreSQL smoke test; enabled by TEST_POSTGRES_URL in CI."""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from research_graph.api.app import create_app
from research_graph.config import Settings
from research_graph.pipelines.importer import import_csv
from research_graph.pipelines.seed import write_demo_csv
from research_graph.storage.database import make_engine, session_factory
from tests.db_fixtures import migration_config
from tests.test_predictions import assert_concurrent_first_predictions


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="PostgreSQL URL not configured")
def test_postgresql_migrations_and_workflow(tmp_path: Path) -> None:
    url = os.environ["TEST_POSTGRES_URL"]
    schema = "test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated_url = (
        make_url(url)
        .update_query_dict({"options": f"-csearch_path={schema}"})
        .render_as_string(hide_password=False)
    )
    engine = make_engine(isolated_url)
    try:
        config = migration_config(isolated_url)
        command.upgrade(config, "head")
        command.check(config)
        assert_concurrent_first_predictions(engine)
        path = tmp_path / "demo.csv"
        write_demo_csv(path, 12)
        with session_factory(engine)() as session:
            assert import_csv(session, path).loaded == 12
            assert import_csv(session, path).duplicates == 12
        with TestClient(
            create_app(
                Settings(
                    _env_file=None, database_url=isolated_url, model_path=tmp_path / "missing.zip"
                )
            )
        ) as client:
            assert client.get("/api/health").status_code == 200
            response = client.post(
                "/api/requests", json={"title": "PostgreSQL", "budget": 2_000_000}
            )
            assert response.status_code == 201
            identity = response.json()["id"]
            assert (
                client.post(
                    f"/api/requests/{identity}/candidates", json={"listing_id": 1}
                ).status_code
                == 201
            )
            assert client.post(f"/api/requests/{identity}/close").status_code == 200
            assert client.delete(f"/api/requests/{identity}").status_code == 409
            assert client.get("/api/analytics/prices").json()
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()
