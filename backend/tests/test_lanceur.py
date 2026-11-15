import json

import httpx
import pytest

from portail.execution import Service
from portail.lanceur import ClientLanceur, ErreurLanceur, Resultat


def _client(gestionnaire):
    return ClientLanceur(
        "http://lanceur:8080", "s" * 32, transport=httpx.MockTransport(gestionnaire)
    )


async def test_client_lanceur_auth_et_erreurs():
    vus = []

    def gestionnaire(req: httpx.Request):
        vus.append(req)
        if req.url.path == "/lancer":
            return httpx.Response(200, json={"code": 0, "sortie": "ok", "delai_depasse": False})
        return httpx.Response(422, json={"erreur": "image non permise"})

    c = _client(gestionnaire)
    r = await c.lancer("tache-1-1", "img", "pytest", 600, ["tests"])
    assert r == Resultat(code=0, sortie="ok", delai_depasse=False)
    assert vus[0].headers["authorization"] == "Bearer " + "s" * 32
    assert json.loads(vus[0].content) == {
        "espace": "tache-1-1", "image": "img", "commande": "pytest",
        "delai_s": 600, "lecture_seule": ["tests"],
    }  # fmt: skip
    with pytest.raises(ErreurLanceur) as exc:
        await c.services("tache-1-1", [Service(nom="db", image="postgres:16", env={"A": "b"})])
    assert exc.value.statut == 422 and exc.value.message == "image non permise"
    assert json.loads(vus[1].content) == {
        "espace": "tache-1-1", "services": [{"nom": "db", "image": "postgres:16", "env": {"A": "b"}}],
    }  # fmt: skip


async def test_client_lanceur_tout_lecture_seule():
    vus = []

    def gestionnaire(req: httpx.Request):
        vus.append(json.loads(req.content))
        return httpx.Response(200, json={"code": 0, "sortie": "", "delai_depasse": False})

    c = _client(gestionnaire)
    await c.lancer("tache-1-1", "img", "ruff check", 600, [], True)
    await c.lancer("tache-1-1", "img", "ruff check", 600, [])
    assert vus[0]["tout_lecture_seule"] is True
    assert "tout_lecture_seule" not in vus[1]


async def test_client_lanceur_routes_simples():
    vus = []

    def gestionnaire(req: httpx.Request):
        vus.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={})

    c = _client(gestionnaire)
    await c.arreter("e")
    await c.nettoyer("e")
    assert vus == [("/arreter", {"espace": "e"}), ("/nettoyer", {"espace": "e"})]


async def test_client_lanceur_erreur_non_json():
    c = _client(lambda req: httpx.Response(500, text="boum"))
    with pytest.raises(ErreurLanceur) as exc:
        await c.arreter("e")
    assert exc.value.statut == 500 and "boum" in exc.value.message


async def test_faux_lanceur(tmp_path):
    from conftest import FauxLanceur

    f = FauxLanceur(tmp_path)
    (tmp_path / "e").mkdir()
    f.codes["pytest"] = [1, 2]
    f.effets["pytest"] = lambda d: (d / "x").write_text("x")
    assert (await f.lancer("e", "img", "pytest", 600, [])).code == 1
    assert (await f.lancer("e", "img", "pytest", 600, [])).code == 2
    assert (await f.lancer("e", "img", "pytest", 600, [])).code == 0
    assert (tmp_path / "e/x").exists() and len(f.appels) == 3


async def test_client_lanceur_erreur_reseau():
    def gestionnaire(req):
        raise httpx.ConnectError("refusé")

    with pytest.raises(ErreurLanceur) as exc:
        await _client(gestionnaire).arreter("e")
    assert exc.value.statut == 0


async def test_client_lanceur_reponse_invalide():
    c = _client(lambda req: httpx.Response(200, text="pas du json"))
    with pytest.raises(ErreurLanceur) as exc:
        await c.lancer("e", "img", "pytest", 600, [])
    assert exc.value.statut == 0
    c = _client(lambda req: httpx.Response(200, json={"code": "x"}))
    with pytest.raises(ErreurLanceur):
        await c.lancer("e", "img", "pytest", 600, [])
