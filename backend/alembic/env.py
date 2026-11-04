from alembic import context

from app.core.db import Base, engine
from app.core.registry import load_all_models

load_all_models()

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
