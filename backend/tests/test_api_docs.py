import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from test_usine_doc import CATALOGUE_DOC

from portail.api import create_app
from portail.db import Audit, CarteDoc
from portail.obsidian import Conflit


class FauxCoffre:
    def __init__(self):
        self.notes: dict[str, tuple[str, str]] = {}  # chemin -> (texte, etag)
        self.ecritures = 0

    async def ecrire_doc(self, chemin, texte, etag_connu, forcer=False):
        actuelle = self.notes.get(chemin)
        if actuelle and not forcer and actuelle[1] != etag_connu:
            raise Conflit(chemin)
        self.ecritures += 1
        etag = f"e{self.ecritures}"
        self.notes[chemin] = (texte, etag)
        return etag


@pytest_asyncio.fixture
async def app(moteur, reglages, faux_llm):
    app = create_app(reglages=reglages, llm=faux_llm, catalogue=CATALOGUE_DOC)
    async with LifespanManager(app):
        app.state.usine.coffre = FauxCoffre()
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        yield c


async def _carte(client, titre="Guide : démarrer") -> dict:
    pid = (await client.post("/api/projets", json={"nom": "Mon/Projet"})).json()["id"]
    r = await client.post(
        "/api/docs/cartes", json={"projet_id": pid, "genre": "guide", "titre": titre}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _a_valider(sessions, cid, contenu="# Guide"):
    async with sessions() as s:
        await s.execute(
            update(CarteDoc)
            .where(CarteDoc.id == cid)
            .values(colonne="a_valider", contenu=contenu, sha="a" * 40)
        )
        await s.commit()


async def test_crud(client):
    c = await _carte(client)
    assert c["chemin"] == "01 - Projets/Mon-Projet/Docs/Mon-Projet - Guide - démarrer.md"
    assert (c["colonne"], c["projet_nom"]) == ("a_rediger", "Mon/Projet")
    r = await client.post(
        "/api/docs/cartes",
        json={"projet_id": c["projet_id"], "genre": "guide", "titre": "Guide : démarrer"},
    )
    assert r.status_code == 409
    r = await client.patch(f"/api/docs/cartes/{c['id']}", json={"consigne": "court"})
    assert r.json()["consigne"] == "court"
    assert [x["id"] for x in (await client.get("/api/docs/cartes")).json()] == [c["id"]]
    assert (await client.get("/api/docs/cartes?projet_id=999")).json() == []
    assert (await client.delete(f"/api/docs/cartes/{c['id']}")).status_code == 204
    assert (await client.get("/api/docs/cartes")).json() == []


async def test_genre_inconnu_refuse(client):
    pid = (await client.post("/api/projets", json={"nom": "p"})).json()["id"]
    r = await client.post("/api/docs/cartes", json={"projet_id": pid, "genre": "x", "titre": "t"})
    assert r.status_code == 422


async def test_carte_en_cours_intouchable(client, sessions):
    c = await _carte(client)
    async with sessions() as s:
        await s.execute(update(CarteDoc).values(colonne="redaction"))
        await s.commit()
    assert (
        await client.patch(f"/api/docs/cartes/{c['id']}", json={"titre": "x"})
    ).status_code == 409
    assert (await client.delete(f"/api/docs/cartes/{c['id']}")).status_code == 409
    r = await client.post(f"/api/docs/cartes/{c['id']}/renvoyer", json={"remarques": ["x"]})
    assert r.status_code == 409


async def test_valider_ecrit_dans_le_coffre(client, app, sessions):
    c = await _carte(client)
    await _a_valider(sessions, c["id"])
    r = await client.post(f"/api/docs/cartes/{c['id']}/valider", json={})
    assert r.status_code == 200, r.text
    assert r.json()["colonne"] == "publie" and r.json()["publie_le"]
    texte, _ = app.state.usine.coffre.notes[c["chemin"]]
    assert texte.startswith('---\ntype: "doc"\nprojet: "Mon/Projet"\ngenre: "guide"\n')
    assert f'depot_sha: "{"a" * 40}"' in texte and texte.endswith("---\n\n# Guide")
    async with sessions() as s:
        assert (await s.get(CarteDoc, c["id"])).etag == "e1"
        assert "carte_doc.valider" in (await s.scalars(select(Audit.action))).all()
    # publiée : plus validable tant qu'elle n'est pas repassée par l'usine
    assert (await client.post(f"/api/docs/cartes/{c['id']}/valider", json={})).status_code == 409


async def test_republication_conflit_etag_puis_forcer(client, app, sessions):
    c = await _carte(client)
    coffre = app.state.usine.coffre
    coffre.notes[c["chemin"]] = ("à la main", "x")  # note déjà là : 1re publication refusée
    await _a_valider(sessions, c["id"])
    r = await client.post(f"/api/docs/cartes/{c['id']}/valider", json={})
    assert r.status_code == 409
    assert coffre.notes[c["chemin"]][0] == "à la main"
    r = await client.post(f"/api/docs/cartes/{c['id']}/valider", json={"forcer": True})
    assert r.json()["colonne"] == "publie"


async def test_valider_sans_coffre_503(client, app, sessions):
    app.state.usine.coffre = None
    c = await _carte(client)
    await _a_valider(sessions, c["id"])
    assert (await client.post(f"/api/docs/cartes/{c['id']}/valider", json={})).status_code == 503
    assert (await client.get("/api/docs/cartes")).json()[0]["colonne"] == "a_valider"


async def test_renvoyer_et_relancer(client, sessions):
    c = await _carte(client)
    await _a_valider(sessions, c["id"])
    async with sessions() as s:
        await s.execute(update(CarteDoc).values(renvois=2))
        await s.commit()
    r = await client.post(
        f"/api/docs/cartes/{c['id']}/renvoyer", json={"remarques": ["plus court"]}
    )
    assert (r.json()["colonne"], r.json()["remarques"], r.json()["renvois"]) == (
        "a_rediger",
        ["plus court"],
        0,
    )
    async with sessions() as s:
        await s.execute(update(CarteDoc).values(erreur="boum"))
        await s.commit()
    r = await client.post(f"/api/docs/cartes/{c['id']}/relancer")
    assert r.json()["erreur"] is None


async def test_pipeline_doc_refuse_par_la_route(client):
    pid = (await client.post("/api/projets", json={"nom": "p"})).json()["id"]
    r = await client.post("/api/pipelines", json={"projet_id": pid, "type": "doc"})
    assert r.status_code == 422
