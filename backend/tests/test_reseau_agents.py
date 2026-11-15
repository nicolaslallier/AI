"""Le réseau des agents ne mène qu'à /interne/, et /interne/ ne vient que de lui."""

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from portail.api import create_app
from portail.config import Reglages
from tests.conftest import CATALOGUE_TEST, URL

RESEAU = "172.31.250.0/24"
AGENT = ("172.31.250.7", 5000)
FRONTAL = ("172.20.0.4", 5000)
FORGE = {"X-Auth-Request-Email": "nicolas@example.test"}


def _client(moteur, tmp_path, faux_llm, pair, reseau=RESEAU, **kw):
    r = Reglages(
        database_url=URL, donnees_dir=tmp_path / "d", resume_heure="", reseau_agents=reseau
    )
    app = create_app(reglages=r, llm=faux_llm, catalogue=CATALOGUE_TEST, **kw)
    return app, ASGITransport(app, client=pair)


async def _code(moteur, tmp_path, faux_llm, pair, chemin, reseau=RESEAU, methode="GET", **kw):
    app, transport = _client(moteur, tmp_path, faux_llm, pair, reseau)
    async with (
        LifespanManager(app),
        AsyncClient(transport=transport, base_url="http://t") as c,
    ):
        r = await c.request(methode, chemin, headers=kw.get("entetes", {}))
        return r.status_code, r.text


@pytest.mark.parametrize("chemin", ["/api/taches", "/api/bureau", "/metrics", "/", "/api/sante"])
async def test_pair_agent_n_atteint_que_interne(moteur, tmp_path, faux_llm, chemin):
    code, corps = await _code(moteur, tmp_path, faux_llm, AGENT, chemin, entetes=FORGE)
    assert code == 404 and "detail" not in corps.lower()


async def test_pair_agent_atteint_interne(moteur, tmp_path, faux_llm):
    # sans jeton : 401 de la route, donc le filtre a laissé passer
    code, _ = await _code(moteur, tmp_path, faux_llm, AGENT, "/interne/modele", methode="POST")
    assert code == 401


async def test_interne_refuse_hors_du_reseau(moteur, tmp_path, faux_llm):
    code, _ = await _code(moteur, tmp_path, faux_llm, FRONTAL, "/interne/modele", methode="POST")
    assert code == 404


async def test_frontal_atteint_l_api(moteur, tmp_path, faux_llm):
    code, _ = await _code(moteur, tmp_path, faux_llm, FRONTAL, "/api/sante")
    assert code == 200


async def test_sans_reseau_rien_ne_change(moteur, tmp_path, faux_llm):
    assert (await _code(moteur, tmp_path, faux_llm, AGENT, "/api/sante", reseau=""))[0] == 200
    code, _ = await _code(
        moteur, tmp_path, faux_llm, FRONTAL, "/interne/modele", reseau="", methode="POST"
    )
    assert code == 401


async def test_en_tete_forwarded_ne_change_pas_le_pair(moteur, tmp_path, faux_llm):
    code, _ = await _code(
        moteur, tmp_path, faux_llm, AGENT, "/api/sante", entetes={"X-Forwarded-For": "172.20.0.4"}
    )
    assert code == 404


def test_cidr_invalide_refuse():
    with pytest.raises(ValidationError):
        Reglages(database_url=URL, reseau_agents="pas-un-reseau")


async def test_pair_ipv4_mappe_en_ipv6_reste_du_reseau(moteur, tmp_path, faux_llm):
    pair = ("::ffff:172.31.250.5", 5000)
    code, _ = await _code(moteur, tmp_path, faux_llm, pair, "/interne/modele", methode="POST")
    assert code == 401  # le filtre l'a laissé passer jusqu'à la route
    code, _ = await _code(moteur, tmp_path, faux_llm, pair, "/api/sante")
    assert code == 404


@pytest.mark.parametrize(
    "chemin", ["/interne/../assets/x.js", "/interne/%2e%2e/api/taches", "/interne/%2E%2E/"]
)
async def test_pair_agent_ne_remonte_pas_hors_de_interne(moteur, tmp_path, faux_llm, chemin):
    code, corps = await _code(moteur, tmp_path, faux_llm, AGENT, chemin, entetes=FORGE)
    assert code == 404 and "detail" not in corps.lower()
