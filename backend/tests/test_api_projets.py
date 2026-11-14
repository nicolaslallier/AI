from datetime import UTC, datetime

from asgi_lifespan import LifespanManager
from conftest import CATALOGUE_TEST, URL, FauxLLM
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from portail.api import create_app
from portail.config import Reglages
from portail.db import Document, Etape
from portail.moteur import terminer_etape


async def _projet(client, nom="P"):
    return (await client.post("/api/projets", json={"nom": nom})).json()


async def test_creer_et_lister_projets(client):
    for nom in ("Zeta", "Alpha"):
        r = await client.post("/api/projets", json={"nom": nom})
        assert r.status_code == 201
    assert [p["nom"] for p in (await client.get("/api/projets")).json()] == ["Alpha", "Zeta"]


async def test_nom_vide_refuse(client):
    assert (await client.post("/api/projets", json={"nom": "   "})).status_code == 422


async def test_creer_pipeline_spec(client):
    p = await _projet(client)
    r = await client.post("/api/pipelines", json={"projet_id": p["id"], "type": "spec"})
    assert r.status_code == 201
    d = r.json()
    assert d["projet"] == {"id": p["id"], "nom": "P"}
    assert len(d["etapes"]) == 1
    e = d["etapes"][0]
    assert (e["agent"], e["etat"], e["document"]) == ("spec", "en_attente", None)
    assert e["jauge"]["niveau"] == "ok"
    assert (await client.get(f"/api/pipelines/{d['id']}")).json() == d


async def test_pipeline_projet_inconnu(client):
    r = await client.post("/api/pipelines", json={"projet_id": 999, "type": "spec"})
    assert r.status_code == 404


async def test_pipeline_type_inconnu(client):
    p = await _projet(client)
    r = await client.post("/api/pipelines", json={"projet_id": p["id"], "type": "nope"})
    assert r.status_code == 404


async def test_filtre_par_etat(client, sessions):
    p = await _projet(client)
    ids = []
    for _ in range(2):
        r = await client.post("/api/pipelines", json={"projet_id": p["id"], "type": "spec"})
        ids.append(r.json()["id"])
    async with sessions() as s:
        etape = await s.scalar(select(Etape).where(Etape.pipeline_id == ids[0]))
        await terminer_etape(s, etape)
        await s.commit()
    r = await client.get("/api/pipelines", params={"etat": "terminee"})
    assert [x["id"] for x in r.json()] == [ids[0]]
    assert len((await client.get("/api/pipelines")).json()) == 2


async def test_spec_courante_est_la_derniere_validee(client, sessions):
    p = await _projet(client)
    det = (
        await client.post("/api/pipelines", json={"projet_id": p["id"], "type": "double"})
    ).json()
    async with sessions() as s:
        e = await s.scalar(select(Etape).where(Etape.pipeline_id == det["id"], Etape.ordre == 0))
        e2 = await s.scalar(select(Etape).where(Etape.pipeline_id == det["id"], Etape.ordre == 1))
        e3 = Etape(pipeline_id=det["id"], ordre=2, agent="a")
        s.add(e3)
        await s.flush()
        for etape, contenu, etat, jour in [
            (e, "ancienne", "validee", 1),
            (e2, "recente", "validee", 2),
            (e3, "brouillon", "brouillon", 3),
        ]:
            s.add(Document(
                projet_id=p["id"], pipeline_id=det["id"], etape_id=etape.id, type="spec",
                contenu=contenu, etat=etat, maj_le=datetime(2026, 1, jour, tzinfo=UTC),
            ))  # fmt: skip
        await s.commit()
    r = (await client.get(f"/api/projets/{p['id']}")).json()
    assert r["spec_courante"]["contenu"] == "recente"
    assert [x["id"] for x in r["pipelines"]] == [det["id"]]


async def test_utilisateur_exige(moteur, schema):
    reglages = Reglages(database_url=URL, exiger_utilisateur=True)
    app = create_app(reglages=reglages, llm=FauxLLM(), catalogue=CATALOGUE_TEST)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        assert (await c.get("/api/projets")).status_code == 401
        h = {"X-Auth-Request-Email": "n@x.fr"}
        assert (await c.get("/api/projets", headers=h)).status_code == 200
        assert (await c.get("/api/sante")).status_code == 200
        assert (
            await c.get("/api/projets", headers={"X-Auth-Request-Email": ""})
        ).status_code == 401
        assert (await c.get("/api/santeX")).status_code == 401


async def test_redemarrage_marque_les_etapes_interrompues(client, sessions, reglages):
    p = await _projet(client)
    det = (await client.post("/api/pipelines", json={"projet_id": p["id"], "type": "spec"})).json()
    async with sessions() as s:
        etape = await s.scalar(select(Etape).where(Etape.pipeline_id == det["id"]))
        etape.etat = "en_cours"
        await s.commit()
    app = create_app(reglages=reglages, llm=FauxLLM(), catalogue=CATALOGUE_TEST)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        d = (await c.get(f"/api/pipelines/{det['id']}")).json()
    assert d["etapes"][0]["etat"] == "echouee"


async def test_agent_absent_du_catalogue(client, sessions):
    p = await _projet(client)
    det = (await client.post("/api/pipelines", json={"projet_id": p["id"], "type": "spec"})).json()
    async with sessions() as s:
        etape = await s.scalar(select(Etape).where(Etape.pipeline_id == det["id"]))
        etape.agent = "disparu"
        await s.commit()
        eid = etape.id
    r = await client.get(f"/api/pipelines/{det['id']}")
    assert r.status_code == 200
    assert r.json()["etapes"][0]["jauge"] is None
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "x"})
    assert r.status_code == 409
    assert "disparu" in r.json()["detail"]
