"""Route de service /service/taches-doc : agent-doc crée une tâche de doc seule, « Prête »."""

import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from portail.api import create_app
from portail.config import Reglages
from portail.db import Tache
from tests.conftest import CATALOGUE_TEST, URL

JETON = {"Authorization": "Bearer s3cret"}
CORPS = {"depot": "Infra", "demande": "Documente la pile mcp.\nDétails…", "appelant": "agent-doc"}
CHEMIN = "/service/taches-doc"


def _app(tmp_path, faux_llm, **kw):
    r = Reglages(
        database_url=URL,
        donnees_dir=tmp_path / "d",
        resume_heure="",
        jeton_service="s3cret",
        github_proprietaire="nicolaslallier",
        url_publique="https://portail.test",
        **kw,
    )
    return create_app(reglages=r, llm=faux_llm, catalogue=CATALOGUE_TEST)


@pytest_asyncio.fixture
async def client_service(moteur, tmp_path, faux_llm):
    app = _app(tmp_path, faux_llm)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        yield c


async def _projet(client, depot_url):
    r = await client.post("/api/projets", json={"nom": "P", "depot_url": depot_url})
    assert r.status_code == 201, r.text
    return r.json()


async def test_cree_une_tache_doc_prete(client_service, sessions):
    p = await _projet(client_service, "https://github.com/nicolaslallier/Infra.git")
    r = await client_service.post(CHEMIN, json=CORPS, headers=JETON)
    assert r.status_code == 201, r.text
    assert r.json()["existante"] is False and r.json()["projet_id"] == p["id"]
    assert r.json()["lien"] == f"https://portail.test/projets/{p['id']}/kanban"
    async with sessions() as s:
        t = await s.get(Tache, r.json()["tache_id"])
        assert (t.doc, t.colonne, t.origine, t.protegee) == (True, "prete", "agent", False)
        assert t.titre == "Documentation : Documente la pile mcp."
        assert t.description == CORPS["demande"]


async def test_meme_demande_une_seule_tache(client_service):
    await _projet(client_service, "https://github.com/NicolasLallier/infra.git")
    a = await client_service.post(CHEMIN, json=CORPS, headers=JETON)
    b = await client_service.post(CHEMIN, json=CORPS | {"depot": "infra"}, headers=JETON)
    assert a.status_code == 201
    assert (b.status_code, b.json()["existante"], b.json()["tache_id"]) == (
        200,
        True,
        a.json()["tache_id"],
    )


async def test_jeton(client_service, client):  # `client` : jeton_service vide
    assert (await client_service.post(CHEMIN, json=CORPS)).status_code == 401
    faux = {"Authorization": "Bearer faux"}
    assert (await client_service.post(CHEMIN, json=CORPS, headers=faux)).status_code == 401
    basic = {"Authorization": "Basic s3cret"}
    assert (await client_service.post(CHEMIN, json=CORPS, headers=basic)).status_code == 401
    for h in ({}, {"Authorization": "Bearer "}, JETON):
        r = await client.post(CHEMIN, json=CORPS, headers=h)
        assert r.status_code == 503 and r.json() == {"detail": "service désactivé"}


async def test_depot_inconnu_ambigu_invalide(client_service):
    assert (await client_service.post(CHEMIN, json=CORPS, headers=JETON)).status_code == 404
    for _ in range(2):
        await _projet(client_service, "https://github.com/nicolaslallier/Infra")
    assert (await client_service.post(CHEMIN, json=CORPS, headers=JETON)).status_code == 409
    for depot in ("a/b", "..", ".", "", "x" * 101):
        r = await client_service.post(CHEMIN, json=CORPS | {"depot": depot}, headers=JETON)
        assert r.status_code == 422, depot
    for mauvais in ({"demande": "  "}, {"appelant": "Agent Doc"}, {"autre": 1}):
        r = await client_service.post(CHEMIN, json=CORPS | mauvais, headers=JETON)
        assert r.status_code == 422, mauvais


async def test_autre_proprietaire_ignore(client_service):
    await _projet(client_service, "https://github.com/quelquun/Infra")
    assert (await client_service.post(CHEMIN, json=CORPS, headers=JETON)).status_code == 404


async def test_plafond_de_taches_ouvertes(client_service):
    await _projet(client_service, "https://github.com/nicolaslallier/Infra")
    codes = [
        (
            await client_service.post(CHEMIN, json=CORPS | {"demande": f"d{i}"}, headers=JETON)
        ).status_code
        for i in range(6)
    ]
    assert codes == [201] * 5 + [429]


async def test_le_jeton_de_service_n_ouvre_pas_api(moteur, tmp_path, faux_llm):
    app = _app(tmp_path, faux_llm, exiger_utilisateur=True)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        assert (await c.get("/api/projets", headers=JETON)).status_code == 401


async def test_reseau_agents_ne_voit_pas_service(moteur, tmp_path, faux_llm):
    app = _app(tmp_path, faux_llm, reseau_agents="172.31.250.0/24")
    transport = ASGITransport(app, client=("172.31.250.7", 5000))
    async with LifespanManager(app), AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.post(CHEMIN, json=CORPS, headers=JETON)).status_code == 404


async def test_jeton_avant_le_corps(client_service, client):
    assert (await client_service.post(CHEMIN, content=b"{")).status_code == 401
    assert (await client.post(CHEMIN, content=b"{")).status_code == 503
    r = await client_service.post(CHEMIN, content=b"{", headers=JETON)
    assert r.status_code == 422


async def test_corps_trop_gros(client_service):
    gros = CORPS | {"demande": "x" * 20000}
    assert (await client_service.post(CHEMIN, json=gros, headers=JETON)).status_code == 413


async def test_caractere_nul_refuse(client_service):
    await _projet(client_service, "https://github.com/nicolaslallier/Infra")
    r = await client_service.post(CHEMIN, json=CORPS | {"demande": "a\u0000b"}, headers=JETON)
    assert r.status_code == 422


async def test_plafond_compte_en_revue_et_bloquee(client_service, sessions):
    await _projet(client_service, "https://github.com/nicolaslallier/Infra")
    for i in range(5):
        r = await client_service.post(CHEMIN, json=CORPS | {"demande": f"d{i}"}, headers=JETON)
        assert r.status_code == 201
    async with sessions() as s:
        await s.execute(update(Tache).values(colonne="en_revue"))
        await s.execute(update(Tache).where(Tache.id == 1).values(colonne="bloquee"))
        await s.commit()
    r = await client_service.post(CHEMIN, json=CORPS | {"demande": "d5"}, headers=JETON)
    assert r.status_code == 429
    async with sessions() as s:
        await s.execute(update(Tache).values(colonne="terminee"))
        await s.commit()
    r = await client_service.post(CHEMIN, json=CORPS | {"demande": "d5"}, headers=JETON)
    assert r.status_code == 201
