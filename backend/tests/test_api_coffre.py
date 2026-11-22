"""Routes /api/coffre : 503 sans secret S3, lecture, chemins refusés, erreur S3 masquée."""

import pytest_asyncio
from asgi_lifespan import LifespanManager
from botocore.exceptions import ClientError
from httpx import ASGITransport, AsyncClient

from portail.api import create_app
from portail.obsidian import Coffre
from tests.conftest import CATALOGUE_TEST
from tests.test_obsidian import FauxS3


@pytest_asyncio.fixture
async def avec_coffre(moteur, reglages, faux_llm):
    s3 = FauxS3()
    s3.objets.update({"Maison/D/a.md": b"# A", "Maison/b.md": b"b"})
    app = create_app(
        reglages=reglages, llm=faux_llm, catalogue=CATALOGUE_TEST, coffre=Coffre(s3, "o", "Maison")
    )
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        yield c, s3


async def test_sans_secret_503(client):
    assert (await client.get("/api/coffre/arbre")).status_code == 503
    assert (await client.get("/api/coffre/note", params={"chemin": "a.md"})).status_code == 503


async def test_arbre_et_note(avec_coffre):
    c, _ = avec_coffre
    r = await c.get("/api/coffre/arbre")
    assert r.status_code == 200
    assert r.json()["dossiers"] == ["D"] and r.json()["notes"][0]["chemin"] == "b.md"
    r = await c.get("/api/coffre/note", params={"chemin": "D/a.md"})
    assert r.json() == {"chemin": "D/a.md", "contenu": "# A"}


async def test_chemins_refuses(avec_coffre):
    c, _ = avec_coffre
    for chemin in ["../x.md", "/x.md", ".obsidian/x.md", "D/a.txt"]:
        assert (await c.get("/api/coffre/note", params={"chemin": chemin})).status_code == 422
    assert (await c.get("/api/coffre/note", params={"chemin": "x.md"})).status_code == 404


async def test_erreur_s3_masquee(avec_coffre):
    c, s3 = avec_coffre

    def panne(**_):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "secret-xyz"}}, "List")

    s3.list_objects_v2 = panne
    r = await c.get("/api/coffre/arbre")
    assert r.status_code == 502 and "secret-xyz" not in r.text
