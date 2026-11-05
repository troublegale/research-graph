"""Database connections; schemas are managed exclusively by Alembic."""

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str) -> Engine:
    """Create a PostgreSQL or local SQLite connection pool."""
    engine = create_engine(
        url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection: object, _: object) -> None:
            # SQLite's DB-API types are intentionally kept out of PostgreSQL code.
            from sqlite3 import Connection

            if isinstance(connection, Connection):
                connection.execute("PRAGMA foreign_keys=ON")

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Sessions keep loaded attributes available after commit."""
    return sessionmaker(engine, expire_on_commit=False)
