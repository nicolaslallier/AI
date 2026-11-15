import re
from pathlib import Path

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from portail.api import create_app
from portail.config import Reglages
from tests.conftest import CATALOGUE_TEST, URL, FauxLLM

VHOST = Path(__file__).parents[2] / "deploy" / "nginx" / "portail.conf"


async def _client(tmp_path, **kw):
    r = Reglages(
        database_url=URL, donnees_dir=tmp_path / "d", resume_heure="",
        version="sha-test", deploye_le=1_700_000_000, **kw,
    )  # fmt: skip
    app = create_app(reglages=r, llm=FauxLLM(), catalogue=CATALOGUE_TEST)
    return app


async def test_metrics_format_prometheus(moteur, tmp_path):
    app = await _client(tmp_path)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        r = await c.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert 'portail_info{version="sha-test"} 1.0' in r.text
    assert "portail_deploiement_horodatage_secondes 1.7e+09" in r.text
    assert "portail_duree_max_tache_secondes 7200.0" in r.text


async def test_metrics_hors_authentification(moteur, tmp_path):
    app = await _client(tmp_path, exiger_utilisateur=True)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        assert (await c.get("/metrics")).status_code == 200
        assert (await c.get("/api/projets")).status_code == 401


async def test_metrics_avant_le_repli_spa(moteur, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>portail</html>")
    app = await _client(tmp_path, static_dir=tmp_path)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        r = await c.get("/metrics")
    assert "portail_info" in r.text
    assert "<html>" not in r.text


def test_vhost_refuse_metrics():
    assert re.search(r"location\s+\^~\s+/metrics\s*\{\s*return\s+404;\s*\}", VHOST.read_text())
