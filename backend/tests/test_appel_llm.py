import json

import httpx
import pytest
from conftest import valeur
from sqlalchemy import select

from portail import journal
from portail.arbitre import Arbitre, LLMArbitre
from portail.db import AppelLLM
from portail.llm import ClientLLM, ErreurLLM

MSG = [{"role": "user", "content": "secret"}]
USAGE = {"prompt_tokens": 10, "completion_tokens": 5}


def _client(handler, sessions):
    return ClientLLM(
        "http://l", "k", httpx.MockTransport(handler), sessions=sessions, version="sha-test"
    )


def _ok(requete: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": "r"}}], "usage": USAGE})


async def _lignes(sessions) -> list[AppelLLM]:
    async with sessions() as s:
        return list((await s.scalars(select(AppelLLM))).all())


@pytest.fixture(autouse=True)
def _contexte_propre():
    journal.commencer()
    yield
    journal.commencer()


async def test_completer_inscrit_l_appel(sessions):
    journal.commencer(pipeline=1, etape=2, tache=3)
    mission = journal.nouvelle_mission("code", 1000)
    await _client(_ok, sessions).completer("m", MSG, None)
    (ligne,) = await _lignes(sessions)
    assert (ligne.agent, ligne.modele, ligne.lieu, ligne.version_image) == (
        "code",
        "m",
        "portail",
        "sha-test",
    )
    assert ligne.mission == mission
    assert (ligne.pipeline_id, ligne.etape_id, ligne.tache_id) == (1, 2, 3)
    assert ligne.conversation_id is None
    assert (ligne.jetons_entree, ligne.jetons_sortie, ligne.issue) == (10, 5, "ok")
    assert ligne.duree_ms >= 0


async def test_metriques_d_un_appel(sessions):
    et = {"agent": "code", "modele": "m", "lieu": "portail"}
    noms = [
        ("portail_llm_appels_total", {**et, "issue": "ok"}),
        ("portail_llm_jetons_total", {**et, "sens": "entree"}),
        ("portail_llm_jetons_total", {**et, "sens": "sortie"}),
        ("portail_llm_duree_secondes_count", et),
        ("portail_contexte_remplissage_count", {"agent": "code"}),
        ("portail_contexte_remplissage_sum", {"agent": "code"}),
    ]
    avant = [valeur(n, **e) for n, e in noms]
    journal.nouvelle_mission("code", 1000)
    await _client(_ok, sessions).completer("m", MSG, None)
    apres = [valeur(n, **e) for n, e in noms]
    assert [round(a - b, 6) for a, b in zip(apres, avant, strict=True)] == [1, 10, 5, 1, 1, 0.01]


async def test_flux_demande_l_usage(sessions):
    corps = []

    def handler(requete: httpx.Request) -> httpx.Response:
        corps.append(json.loads(requete.content))
        morceaux = [
            {"choices": [{"delta": {"content": "Bon"}}]},
            {"choices": [{"delta": {"content": "jour"}}]},
            {"choices": [], "usage": USAGE},
        ]
        texte = "".join(f"data: {json.dumps(m)}\n\n" for m in morceaux) + "data: [DONE]\n\n"
        return httpx.Response(200, text=texte)

    client = _client(handler, sessions)
    texte = "".join([m async for m in client.flux("m", MSG, None)])
    assert texte == "Bonjour"
    assert corps[0]["stream_options"]["include_usage"] is True
    (ligne,) = await _lignes(sessions)
    assert (ligne.jetons_entree, ligne.jetons_sortie, ligne.issue) == (10, 5, "ok")


@pytest.mark.parametrize(
    ("handler", "issue"),
    [
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("t")), "delai"),
        (lambda r: httpx.Response(500, text="contenu secret"), "erreur"),
    ],
)
async def test_issue_delai_et_erreur(sessions, handler, issue):
    client = _client(handler, sessions)
    with pytest.raises(ErreurLLM):
        await client.completer("m", MSG, None)
    with pytest.raises(ErreurLLM):
        [m async for m in client.flux("m", MSG, None)]
    lignes = await _lignes(sessions)
    assert [x.issue for x in lignes] == [issue, issue]
    assert all(x.jetons_entree is None for x in lignes)


async def test_inscription_impossible_n_arrete_pas_l_appel():
    def casse():
        raise RuntimeError("base saturée")

    client = ClientLLM("http://l", "k", httpx.MockTransport(_ok), sessions=casse)
    assert (await client.completer("m", MSG, None))["content"] == "r"


async def test_sous_l_arbitre(sessions):
    arbitre = LLMArbitre(_client(_ok, sessions), Arbitre(), "fond")
    await arbitre.completer("m", MSG, None)
    assert len(await _lignes(sessions)) == 1


def test_colonnes_sans_contenu():
    assert set(AppelLLM.__table__.columns.keys()) == {
        "id",
        "quand",
        "agent",
        "modele",
        "lieu",
        "version_image",
        "mission",
        "pipeline_id",
        "etape_id",
        "tache_id",
        "conversation_id",
        "jetons_entree",
        "jetons_sortie",
        "duree_ms",
        "issue",
    }


def _flux_de(morceaux):
    def handler(requete: httpx.Request) -> httpx.Response:
        texte = "".join(f"data: {json.dumps(m)}\n\n" for m in morceaux) + "data: [DONE]\n\n"
        return httpx.Response(200, text=texte)

    return handler


async def test_flux_usage_sans_choices(sessions):
    handler = _flux_de(
        [{"choices": [{"delta": {"content": "Bon"}}]}, {"usage": USAGE}]  # pas de `choices`
    )
    texte = "".join([m async for m in _client(handler, sessions).flux("m", MSG, None)])
    assert texte == "Bon"
    (ligne,) = await _lignes(sessions)
    assert (ligne.jetons_entree, ligne.jetons_sortie, ligne.issue) == (10, 5, "ok")


async def test_flux_sans_usage(sessions):
    handler = _flux_de([{"choices": [{"delta": {"content": "Bon"}}]}])
    assert "".join([m async for m in _client(handler, sessions).flux("m", MSG, None)]) == "Bon"
    (ligne,) = await _lignes(sessions)
    assert (ligne.jetons_entree, ligne.jetons_sortie, ligne.issue) == (None, None, "ok")


async def test_version_non_definie_inscrite_null(sessions):
    client = ClientLLM("http://l", "k", httpx.MockTransport(_ok), sessions=sessions)
    await client.completer("m", MSG, None)
    (ligne,) = await _lignes(sessions)
    assert ligne.version_image is None
