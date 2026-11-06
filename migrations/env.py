"""Migration configuration shares the application database URL."""

from alembic import context
from sqlalchemy import create_engine, pool

from research_graph.config import get_settings
from research_graph.models.entities import Base

config = context.config
url = config.attributes.get("database_url", get_settings().database_url)
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
