import pytest

from portail.config import Reglages
from tests.conftest import URL


@pytest.fixture
def reglages(schema, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "a.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<html>portail</html>")
    (tmp_path / "favicon.ico").write_text("ico")
    (tmp_path.parent / "secret.txt").write_text("secret")
    return Reglages(database_url=URL, static_dir=tmp_path)


async def test_repli_spa(client):
    r = await client.get("/pipelines/3")
    assert r.status_code == 200
    assert "portail" in r.text


async def test_asset(client):
    assert (await client.get("/assets/a.js")).status_code == 200


async def test_fichier_racine(client):
    assert (await client.get("/favicon.ico")).text == "ico"


async def test_pas_de_traversee(client):
    r = await client.get("/..%2Fsecret.txt")
    assert "secret" not in r.text


async def test_api_inconnue_reste_404_json(client):
    r = await client.get("/api/inexistant")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


async def test_api_sante_intacte(client):
    assert (await client.get("/api/sante")).json() == {"ok": True}
