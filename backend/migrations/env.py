import os

from alembic import context
from sqlalchemy import create_engine

from portail.db import Base

url = os.environ["PORTAIL_DATABASE_URL"]

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url).connect() as connexion:
        context.configure(connection=connexion, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
