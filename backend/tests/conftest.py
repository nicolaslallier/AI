import os

import pytest
import pytest_asyncio
from sqlalchemy import text

from portail.db import Base, creer_moteur, fabrique_sessions

URL = os.environ.get(
    "PORTAIL_TEST_DATABASE_URL", "postgresql+psycopg://portail:portail@localhost:5433/portail_test"
)


@pytest_asyncio.fixture
async def moteur():
    m = creer_moteur(URL)
    async with m.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    yield m
    async with m.begin() as c:
        tables = ", ".join(Base.metadata.tables)
        await c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await m.dispose()


@pytest.fixture
def sessions(moteur):
    return fabrique_sessions(moteur)
