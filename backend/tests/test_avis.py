import asyncio

import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from portail.agents import Catalogue
from portail.api import create_app
from portail.db import Avis
from tests.conftest import OUTILS, _agent

CATALOGUE_AVIS = Catalogue(
    agents={
        "spec": _agent("spec", consigne_redaction="Rédige la spec.", outils=OUTILS),
        "plan": _agent(
            "plan", consigne_redaction="Rédige le plan.", produit="plan", auto=True, outils=OUTILS
        ),
        "architecte": _agent("architecte", outils=OUTILS, consigne_avis="Relis l'architecture."),
        "challenger": _agent(
            "challenger", outils=OUTILS, produit="verdict", role="revue",
            modele_si_meme="m2", consigne_avis="Conteste le plan.",
        ),
    },
    pipelines={"spec": ["spec"], "planification": ["plan"]},
    avis={"plan": ["architecte", "challenger"]},
)  # fmt: skip


@pytest_asyncio.fixture
async def client(moteur, reglages, faux_llm):
    app = create_app(reglages=reglages, llm=faux_llm, catalogue=CATALOGUE_AVIS)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        yield c


def _app(client):
    return client._transport.app


def _reponse(texte):
    return {"content": texte}


async def _attendre(client, eid=None, avis=True):
    app = _app(client)
    if eid and (t := app.state.chat.taches.get(eid)):
        await asyncio.wait_for(t, 5)
    if avis and (taches := list(app.state.avis.taches.values())):
        await asyncio.wait_for(asyncio.gather(*taches), 5)


async def _plan(client, faux_llm, reponses=None, avis=True):
    """Spec validée, puis planification : renvoie (pipeline_id, étape du plan)."""
    projet = (await client.post("/api/projets", json={"nom": "P"})).json()
    p = (
        await client.post("/api/pipelines", json={"projet_id": projet["id"], "type": "spec"})
    ).json()
    sid = p["etapes"][0]["id"]
    faux_llm.morceaux = ["# Spec"]
    await client.post(f"/api/etapes/{sid}/rediger")
    await _attendre(client, sid)
    assert (await client.post(f"/api/etapes/{sid}/valider")).status_code == 200
    faux_llm.morceaux = ["# Plan"]
    faux_llm.reponses = reponses if reponses is not None else [_reponse("avis"), _reponse("avis")]
    p = (
        await client.post(
            "/api/pipelines", json={"projet_id": projet["id"], "type": "planification"}
        )
    ).json()
    eid = p["etapes"][0]["id"]
    await _attendre(client, eid, avis)
    return p["id"], eid


async def _document(client, pid):
    return (await client.get(f"/api/pipelines/{pid}")).json()["etapes"][0]["document"]


def _avis_appels(faux_llm):
    return [a for a in faux_llm.appels if "outils" in a]


async def test_redaction_declenche_les_avis_du_plan(client, faux_llm):
    pid, _ = await _plan(client, faux_llm)
    doc = await _document(client, pid)
    assert sorted((a["agent"], a["etat"], a["version"]) for a in doc["avis"]) == [
        ("architecte", "ouvert", 1),
        ("challenger", "ouvert", 1),
    ]
    assert {a["contenu"] for a in doc["avis"]} == {"avis"}
    # le brouillon et la spec courante sont lus par l'agent d'avis
    lu = "\n".join(m["content"] for m in _avis_appels(faux_llm)[0]["messages"])
    assert "# Plan" in lu and "# Spec" in lu


async def test_put_de_nicolas_ne_declenche_rien(client, faux_llm):
    pid, eid = await _plan(client, faux_llm)
    avant = len(_avis_appels(faux_llm))
    r = await client.put(f"/api/etapes/{eid}/document", json={"contenu": "# Plan corrigé"})
    assert r.status_code == 200
    await _attendre(client)
    assert len(_avis_appels(faux_llm)) == avant and not _app(client).state.avis.taches
    assert len((await _document(client, pid))["avis"]) == 2


async def test_avis_marque_ancien_apres_correction(client, faux_llm):
    pid, eid = await _plan(client, faux_llm)
    await client.put(f"/api/etapes/{eid}/document", json={"contenu": "# Plan corrigé"})
    doc = await _document(client, pid)
    assert doc["version"] == 2
    assert [a["ancienne"] for a in doc["avis"]] == [True, True]


async def test_avis_ouverts_donnes_a_la_redaction_suivante(client, faux_llm):
    pid, eid = await _plan(client, faux_llm)
    faux_llm.morceaux = ["# Plan 2"]
    faux_llm.reponses = [_reponse("n1"), _reponse("n2")]
    assert (await client.post(f"/api/etapes/{eid}/rediger")).status_code == 202
    await _attendre(client, eid)
    redaction = next(a for a in reversed(faux_llm.appels) if "outils" not in a)
    annexe = next(m["content"] for m in redaction["messages"] if "Avis ouverts" in m["content"])
    assert (
        annexe == "Avis ouverts à prendre en compte :\n\n- architecte : avis\n- challenger : avis"
    )
    doc = await _document(client, pid)
    assert doc["version"] == 2
    assert sorted((a["version"], a["ancienne"]) for a in doc["avis"]) == [
        (1, True), (1, True), (2, False), (2, False),
    ]  # fmt: skip


async def test_valider_abandonne_les_avis_en_cours(client, faux_llm, sessions):
    bloque = asyncio.Event()
    pid, eid = await _plan(
        client, faux_llm, [bloque, bloque, _reponse("a"), _reponse("b")], avis=False
    )
    assert (await client.post(f"/api/etapes/{eid}/valider")).status_code == 200
    bloque.set()
    await _attendre(client)
    assert (await _document(client, pid))["avis"] == []
    async with sessions() as s:
        assert set((await s.scalars(select(Avis.etat))).all()) == {"abandonne"}


async def test_challenger_change_de_modele_si_meme_que_le_redacteur(client, faux_llm):
    await _plan(client, faux_llm)
    assert sorted(a["modele"] for a in _avis_appels(faux_llm)) == ["m", "m2"]


async def test_demande_manuelle(client, faux_llm):
    pid, eid = await _plan(client, faux_llm)
    did = (await _document(client, pid))["id"]
    faux_llm.reponses = [_reponse("avis A2"), _reponse("avis C2")]
    assert (await client.post(f"/api/documents/{did}/avis")).status_code == 202
    await _attendre(client)
    assert len((await _document(client, pid))["avis"]) == 4
    assert (await client.post("/api/documents/999999/avis")).status_code == 404
    await client.post(f"/api/etapes/{eid}/valider")
    assert (await client.post(f"/api/documents/{did}/avis")).status_code == 409


async def test_tri_d_un_avis(client, faux_llm):
    pid, _ = await _plan(client, faux_llm)
    avis = (await _document(client, pid))["avis"][0]
    r = await client.patch(f"/api/avis/{avis['id']}", json={"etat": "ecarte"})
    assert r.status_code == 200 and r.json()["etat"] == "ecarte"
    assert (
        await client.patch(f"/api/avis/{avis['id']}", json={"etat": "en_cours"})
    ).status_code == 422
    assert (await client.patch("/api/avis/999999", json={"etat": "ecarte"})).status_code == 404


async def test_avis_ne_bloque_pas_la_validation(client, faux_llm):
    bloque = asyncio.Event()
    _, eid = await _plan(
        client, faux_llm, [bloque, bloque, _reponse("a"), _reponse("b")], avis=False
    )
    r = await asyncio.wait_for(client.post(f"/api/etapes/{eid}/valider"), 2)
    assert r.status_code == 200 and r.json()["etat"] == "terminee"
    bloque.set()


async def test_redemarrage_abandonne_les_avis_en_cours(client, faux_llm, sessions):
    bloque = asyncio.Event()
    pid, _ = await _plan(
        client, faux_llm, [bloque, bloque, _reponse("a"), _reponse("b")], avis=False
    )
    async with sessions() as s:
        await _app(client).state.avis.recuperer_interrompues(s)
        await s.commit()
    bloque.set()
    await _attendre(client)  # le modèle répond ensuite : la ligne reste abandonnée
    assert (await _document(client, pid))["avis"] == []
