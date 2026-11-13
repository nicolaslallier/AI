import asyncio

import httpx
import pytest
from httpx import ASGITransport

from server.app import create_app


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "00 - Inbox").mkdir()
    return tmp_path


@pytest.fixture
async def app(vault):
    app = create_app(vault)
    # ASGITransport ne lance pas le lifespan Starlette : on le tient dans une tâche dédiée
    # (anyio exige d'entrer et sortir du cancel scope dans la même tâche).
    ready, stop = asyncio.Event(), asyncio.Event()

    async def run():
        async with app.router.lifespan_context(app):
            ready.set()
            await stop.wait()

    task = asyncio.create_task(run())
    await ready.wait()
    yield app
    stop.set()
    await task


@pytest.fixture
async def http(app):
    async with httpx.AsyncClient(transport=ASGITransport(app), base_url="http://127.0.0.1:8765") as c:
        yield c
