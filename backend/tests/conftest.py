import os

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text

from portail.db import Base, creer_moteur, fabrique_sessions

URL = os.environ.get(
    "PORTAIL_TEST_DATABASE_URL", "postgresql+psycopg://portail:portail@localhost:5433/portail_test"
)


@pytest.fixture(scope="session")
def schema():
    # moteur synchrone : un moteur async de session serait lié à une autre boucle d'événements
    m = create_engine(URL)
    Base.metadata.create_all(m)
    m.dispose()


@pytest_asyncio.fixture
async def moteur(schema):
    m = creer_moteur(URL)
    yield m
    async with m.begin() as c:
        tables = ", ".join(Base.metadata.tables)
        await c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await m.dispose()


@pytest.fixture
def sessions(moteur):
    return fabrique_sessions(moteur)
