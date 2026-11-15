import asyncio

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from portail.api import create_app
from portail.config import Reglages
from portail.db import Pipeline
from portail.evenements import Bus, bus, flux
from tests.conftest import CATALOGUE_TEST, URL, FauxLLM


def _vider(file):
    sortie = []
    while not file.empty():
        sortie.append(file.get_nowait())
    return sortie


async def test_signal_kanban_au_deplacement(client):
    pid = (await client.post("/api/projets", json={"nom": "P"})).json()["id"]
    tid = (await client.post(f"/api/projets/{pid}/taches", json={"titre": "T"})).json()["id"]
    file = bus.abonner()
    try:
        r = await client.post(f"/api/taches/{tid}/deplacer", json={"colonne": "prete"})
        assert r.status_code == 200
        assert ("kanban", pid) in _vider(file)
    finally:
        bus.desabonner(file)


async def test_rollback_ne_signale_rien(sessions):
    file = bus.abonner()
    try:
        async with sessions() as s:
            await s.execute(update(Pipeline).values(etat="annule"))
            await s.rollback()
        assert _vider(file) == []
    finally:
        bus.desabonner(file)


async def test_update_en_masse_pipeline_signale(sessions):
    file = bus.abonner()
    try:
        async with sessions() as s:
            await s.execute(update(Pipeline).values(etat="annule"))
            await s.commit()
        assert _vider(file) == [("pipelines", None)]
    finally:
        bus.desabonner(file)


async def test_flux_format():
    b = Bus()
    it = flux(b)
    tache = asyncio.ensure_future(anext(it))
    await asyncio.sleep(0)
    b.publier(("kanban", 1))
    assert await tache == 'event: kanban\ndata: {"projet_id": 1}\n\n'
    tache = asyncio.ensure_future(anext(it))
    await asyncio.sleep(0)
    b.publier(("pipelines", None))
    assert await tache == "event: pipelines\ndata: {}\n\n"
    await it.aclose()
    assert not b.abonnes


async def test_flux_ping():
    b = Bus()
    it = flux(b, ping_s=0.01)
    assert await anext(it) == ": ping\n\n"
    await it.aclose()
    assert not b.abonnes


async def test_evenements_exige_l_utilisateur(moteur, schema):
    app = create_app(
        reglages=Reglages(database_url=URL, exiger_utilisateur=True),
        llm=FauxLLM(),
        catalogue=CATALOGUE_TEST,
    )
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        assert (await c.get("/api/evenements")).status_code == 401


async def test_flux_sans_tampon(client, monkeypatch):
    async def fini(_bus):
        yield "data: x\n\n"

    monkeypatch.setattr("portail.api.flux_evenements", fini)
    projet = (await client.post("/api/projets", json={"nom": "P"})).json()
    pid = (
        await client.post("/api/pipelines", json={"projet_id": projet["id"], "type": "spec"})
    ).json()
    eid = pid["etapes"][0]["id"]
    cid = (await client.post("/api/conversations")).json()["id"]
    for url in (f"/api/etapes/{eid}/flux", f"/api/conversations/{cid}/flux", "/api/evenements"):
        r = await asyncio.wait_for(client.get(url), 5)
        assert r.headers["content-type"].startswith("text/event-stream"), url
        assert r.headers["x-accel-buffering"] == "no", url
        assert r.headers["cache-control"] == "no-cache", url
