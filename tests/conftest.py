import asyncio
import contextlib

import httpx
import pytest
from httpx import ASGITransport

from server.app import create_app


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "00 - Inbox").mkdir()
    return tmp_path


@contextlib.asynccontextmanager
async def running(app):
    # ASGITransport ne lance pas le lifespan Starlette : on le tient dans une tâche dédiée
    # (anyio exige d'entrer et sortir du cancel scope dans la même tâche).
    ready, stop = asyncio.Event(), asyncio.Event()

    async def run():
        async with app.router.lifespan_context(app):
            ready.set()
            await stop.wait()

    task = asyncio.create_task(run())
    await ready.wait()
    try:
        yield app
    finally:
        stop.set()
        await task


def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app), base_url="http://127.0.0.1:8765")


@pytest.fixture
async def app(vault):
    async with running(create_app(vault)) as a:
        yield a


@pytest.fixture
async def http(app):
    async with client(app) as c:
        yield c


def make_pdf(n_bytes: int) -> bytes:
    """PDF minimal valide, rembourré (commentaire) jusqu'à `n_bytes`."""
    head, tail = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n", b"\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    pad = max(0, n_bytes - len(head) - len(tail) - 1)
    return head + b"%" + b"x" * pad + tail
