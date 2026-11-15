import asyncio
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from portail.api import _flux, create_app
from portail.config import Reglages
from portail.db import ExecutionDev, Pipeline, Projet, Tache
from portail.metriques import rafraichir
from tests.conftest import CATALOGUE_TEST, URL, FauxLLM, valeur

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


_REQ = "portail_http_requetes_total"


async def test_requete_par_modele_de_route(moteur, tmp_path):
    from prometheus_client import generate_latest

    app = await _client(tmp_path)
    etiq = {"methode": "DELETE", "route": "/api/taches/{tache_id}", "code": "404"}
    avant = valeur(_REQ, **etiq)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        assert (await c.delete("/api/taches/987654")).status_code == 404
    assert valeur(_REQ, **etiq) == avant + 1
    assert "987654" not in generate_latest().decode()
    assert valeur(
        "portail_http_duree_secondes_count", methode="DELETE", route="/api/taches/{tache_id}"
    )


async def test_chemin_sans_route(moteur, tmp_path):
    app = await _client(tmp_path)
    etiq = {"methode": "GET", "route": "aucune", "code": "404"}
    avant = valeur(_REQ, **etiq)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        assert (await c.get("/api/inconnu/123")).status_code == 404
    assert valeur(_REQ, **etiq) == avant + 1


async def test_401_sans_route(moteur, tmp_path):
    app = await _client(tmp_path, exiger_utilisateur=True)
    etiq = {"methode": "GET", "route": "aucune", "code": "401"}
    avant = valeur(_REQ, **etiq)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        assert (await c.get("/api/projets")).status_code == 401
    assert valeur(_REQ, **etiq) == avant + 1


async def test_erreur_interne_comptee_500(moteur, tmp_path):
    app = await _client(tmp_path)

    @app.get("/api/explose/{x}")
    async def explose(x: str):
        raise RuntimeError("secret")

    etiq = {"methode": "GET", "route": "/api/explose/{x}", "code": "500"}
    avant = valeur(_REQ, **etiq)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        assert (await c.get("/api/explose/1")).status_code == 500
    assert valeur(_REQ, **etiq) == avant + 1


async def test_flux_ouverts():
    async def gen():
        yield "a"
        yield "b"

    avant = valeur("portail_flux_ouverts", flux="conversations")
    r = _flux(gen(), "conversations")
    assert valeur("portail_flux_ouverts", flux="conversations") == avant
    await r.body_iterator.__anext__()
    assert valeur("portail_flux_ouverts", flux="conversations") == avant + 1
    await r.body_iterator.aclose()
    assert valeur("portail_flux_ouverts", flux="conversations") == avant


async def test_flux_ouverts_annule():
    async def gen():
        yield "a"
        await asyncio.sleep(60)
        yield "b"

    avant = valeur("portail_flux_ouverts", flux="evenements")
    r = _flux(gen(), "evenements")
    await r.body_iterator.__anext__()
    tache = asyncio.create_task(r.body_iterator.__anext__())
    await asyncio.sleep(0)
    tache.cancel()
    await asyncio.gather(tache, return_exceptions=True)
    await r.body_iterator.aclose()
    assert valeur("portail_flux_ouverts", flux="evenements") == avant


async def _metrics(app):
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        return (await c.get("/metrics")).text


async def _tache(s, pid, colonne):
    t = Tache(projet_id=pid, titre="t", colonne=colonne, rang=1000, origine="manuel")
    s.add(t)
    await s.flush()
    return t


async def test_collecte_taches_par_colonne(moteur, sessions, tmp_path):
    async with sessions() as s, s.begin():
        p = Projet(nom="p")
        s.add(p)
        await s.flush()
        await _tache(s, p.id, "a_faire")
        await _tache(s, p.id, "a_faire")
        b = await _tache(s, p.id, "bloquee")
    texte = await _metrics(await _client(tmp_path))
    assert 'portail_taches{colonne="a_faire"} 2.0' in texte
    assert 'portail_taches{colonne="bloquee"} 1.0' in texte
    async with sessions() as s, s.begin():
        (await s.get(Tache, b.id)).colonne = "terminee"
    texte = await _metrics(await _client(tmp_path))
    # une colonne vidée sort à 0, elle ne disparaît pas (les alertes ne voient pas de série absente)
    assert 'portail_taches{colonne="bloquee"} 0.0' in texte
    assert 'portail_taches{colonne="prete"} 0.0' in texte


async def test_collecte_age_et_echecs_consecutifs(moteur, sessions, tmp_path):
    maintenant = datetime.now(UTC)
    async with sessions() as s, s.begin():
        p = Projet(nom="p")
        s.add(p)
        await s.flush()
        t = await _tache(s, p.id, "en_cours")
        etats = ["terminee", "echouee", "echouee", "echouee", "en_cours"]
        for i, etat in enumerate(etats):
            pl = Pipeline(
                projet_id=p.id, type="dev", etat=etat, maj_le=maintenant - timedelta(hours=9 - i)
            )
            s.add(pl)
            await s.flush()
            s.add(ExecutionDev(
                pipeline_id=pl.id, tache_id=t.id, n=i, branche="b", espace="e", base="main",
                base_sha="x", phase="code",
                debut=maintenant - timedelta(hours=3 if etat == "en_cours" else 20),
            ))  # fmt: skip
    texte = await _metrics(await _client(tmp_path))
    assert "portail_echecs_dev_consecutifs 3.0" in texte
    age = float(
        re.search(r"^portail_tache_en_cours_age_max_secondes (\S+)$", texte, re.MULTILINE)[1]
    )
    assert 10_800 <= age < 11_400
    assert "portail_base_joignable 1.0" in texte


async def test_collecte_base_injoignable():
    def casse():
        raise ConnectionError("base saturée")

    await rafraichir(casse)
    assert valeur("portail_base_joignable") == 0.0
