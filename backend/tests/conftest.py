import asyncio
import os

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from portail.agents import Agent, Catalogue
from portail.api import create_app
from portail.config import Reglages
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


# --- API ---------------------------------------------------------------


class FauxLLM:
    """Même signature que ClientLLM.flux. `morceaux` est renvoyé, puis `exception` est levée."""

    def __init__(self):
        self.morceaux: list[str | asyncio.Event] = []  # un Event met le flux en pause
        self.exception: Exception | None = None
        self.appels: list[dict] = []  # {"modele", "messages", "temperature"}

    async def flux(self, modele, messages, temperature):
        self.appels.append({"modele": modele, "messages": messages, "temperature": temperature})
        for m in self.morceaux:
            if isinstance(m, asyncio.Event):
                await m.wait()
            else:
                yield m
        if self.exception:
            raise self.exception


def _agent(nom, contexte_max=32768, **kw):
    return Agent(
        nom=nom, description=nom, modele="m", prompt_systeme=f"Tu es {nom}.",
        contexte_max=contexte_max, **kw,
    )  # fmt: skip


CATALOGUE_TEST = Catalogue(
    agents={
        "spec": _agent("spec", consigne_redaction="Rédige la spec."),
        "a": _agent("a"),
        "b": _agent("b"),
        "petit": _agent("petit", contexte_max=50),
    },
    pipelines={"spec": ["spec"], "double": ["a", "b"], "petit": ["petit"]},
)


@pytest.fixture
def reglages(schema):
    return Reglages(database_url=URL)


@pytest.fixture
def faux_llm():
    return FauxLLM()


@pytest_asyncio.fixture
async def client(moteur, reglages, faux_llm):
    app = create_app(reglages=reglages, llm=faux_llm, catalogue=CATALOGUE_TEST)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        yield c
