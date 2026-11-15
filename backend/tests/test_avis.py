import asyncio

import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from portail.agents import Catalogue
from portail.api import create_app
from portail.db import Avis, Document, Etape
from tests.conftest import OUTILS, FauxLLM, _agent

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
    modeles_permis=["m", "m2"],
)  # fmt: skip


class LLMAvis(FauxLLM):
    """Sans réponse préparée, l'avis dit quel modèle l'a donné."""

    async def completer(self, modele, messages, *args, **kw):
        if not self.reponses:
            self.reponses.append({"content": f"avis {modele}"})
        return await super().completer(modele, messages, *args, **kw)


@pytest_asyncio.fixture
def faux_llm():
    return LLMAvis()


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
    faux_llm.reponses = reponses if reponses is not None else []
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
    assert {a["agent"]: a["contenu"] for a in doc["avis"]} == {
        "architecte": "avis m",
        "challenger": "avis m2",
    }
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
    assert (await client.post(f"/api/etapes/{eid}/rediger")).status_code == 202
    await _attendre(client, eid)
    redaction = next(a for a in reversed(faux_llm.appels) if "outils" not in a)
    annexe = next(m["content"] for m in redaction["messages"] if "Avis ouverts" in m["content"])
    assert (
        annexe
        == "Avis ouverts à prendre en compte :\n\n- architecte : avis m\n- challenger : avis m2"
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


async def test_annuler_abandonne_les_avis_en_cours(client, faux_llm, sessions):
    bloque = asyncio.Event()
    pid, _eid = await _plan(
        client, faux_llm, [bloque, bloque, _reponse("a"), _reponse("b")], avis=False
    )
    assert (await client.post(f"/api/pipelines/{pid}/annuler")).status_code == 200
    bloque.set()
    await _attendre(client)
    async with sessions() as s:
        assert set((await s.scalars(select(Avis.etat))).all()) == {"abandonne"}


async def test_challenger_change_de_modele_si_meme_que_le_redacteur(client, faux_llm):
    await _plan(client, faux_llm)
    assert sorted(a["modele"] for a in _avis_appels(faux_llm)) == ["m", "m2"]


async def test_auteur_effectif(client, faux_llm, sessions):
    pid, eid = await _plan(client, faux_llm)
    did = (await _document(client, pid))["id"]
    async with sessions() as s:  # l'auteur tourne sur m2 : le challenger (m) n'a plus à changer
        (await s.get(Etape, eid)).modele = "m2"
        await s.commit()
    faux_llm.appels.clear()
    faux_llm.reponses = [_reponse("avis A2"), _reponse("avis C2")]
    assert (await client.post(f"/api/documents/{did}/avis")).status_code == 202
    await _attendre(client)
    assert sorted(a["modele"] for a in _avis_appels(faux_llm)) == ["m", "m"]


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


async def test_tri_d_un_avis(client, faux_llm, sessions):
    pid, _ = await _plan(client, faux_llm)
    avis = (await _document(client, pid))["avis"][0]
    r = await client.patch(f"/api/avis/{avis['id']}", json={"etat": "ecarte"})
    assert r.status_code == 200 and r.json()["etat"] == "ecarte"
    assert (
        await client.patch(f"/api/avis/{avis['id']}", json={"etat": "en_cours"})
    ).status_code == 422
    # un avis non ouvert (en cours, abandonné) ne se trie pas
    async with sessions() as s:
        await s.execute(update(Avis).where(Avis.id == avis["id"]).values(etat="en_cours"))
        await s.commit()
    r = await client.patch(f"/api/avis/{avis['id']}", json={"etat": "ouvert"})
    assert r.status_code == 409
    async with sessions() as s:
        await s.execute(update(Avis).where(Avis.id == avis["id"]).values(etat="abandonne"))
        await s.commit()
    assert (
        await client.patch(f"/api/avis/{avis['id']}", json={"etat": "ouvert"})
    ).status_code == 409
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


async def test_lancer_sur_un_document_valide_ne_fait_rien(client, faux_llm, sessions):
    pid, eid = await _plan(client, faux_llm)
    did = (await _document(client, pid))["id"]
    await client.post(f"/api/etapes/{eid}/valider")
    avant = len(_avis_appels(faux_llm))
    async with sessions() as s:
        n = len((await s.scalars(select(Avis.id))).all())
    await _app(client).state.avis.lancer(did)
    assert not _app(client).state.avis.taches and len(_avis_appels(faux_llm)) == avant
    async with sessions() as s:
        assert len((await s.scalars(select(Avis.id))).all()) == n


async def test_lancer_sur_un_pipeline_annule_ne_fait_rien(client, faux_llm, sessions):
    pid, _eid = await _plan(client, faux_llm)
    did = (await _document(client, pid))["id"]
    assert (await client.post(f"/api/pipelines/{pid}/annuler")).status_code == 200
    avant = len(_avis_appels(faux_llm))
    async with sessions() as s:
        n = len((await s.scalars(select(Avis.id))).all())
    await _app(client).state.avis.lancer(did)
    assert not _app(client).state.avis.taches and len(_avis_appels(faux_llm)) == avant
    async with sessions() as s:
        assert len((await s.scalars(select(Avis.id))).all()) == n


async def test_avis_qui_finit_apres_la_validation_n_est_pas_enregistre(client, faux_llm, sessions):
    bloque = asyncio.Event()
    pid, _ = await _plan(client, faux_llm, [bloque, bloque, _reponse("a"), _reponse("b")], False)
    did = (await _document(client, pid))["id"]
    async with sessions() as s:  # validation sans passer par `abandonner`
        await s.execute(update(Document).where(Document.id == did).values(etat="validee"))
        await s.commit()
    bloque.set()
    await _attendre(client)
    async with sessions() as s:
        assert set((await s.scalars(select(Avis.etat))).all()) == {"abandonne"}


async def test_put_renvoie_les_avis(client, faux_llm):
    _, eid = await _plan(client, faux_llm)
    r = await client.put(f"/api/etapes/{eid}/document", json={"contenu": "# Plan corrigé"})
    assert r.json()["version"] == 2
    assert sorted((a["agent"], a["ancienne"]) for a in r.json()["avis"]) == [
        ("architecte", True),
        ("challenger", True),
    ]


async def test_avis_n_herite_pas_du_contexte_du_redacteur(client, faux_llm):
    from portail import journal

    pid, _ = await _plan(client, faux_llm)
    did = (await _document(client, pid))["id"]
    service = _app(client).state.avis
    vus = []
    rediger = service._rediger

    async def espion(*args):  # le contexte à l'entrée, avant toute lecture en base
        vus.append(dict(journal.contexte.get()))
        return await rediger(*args)

    service._rediger = espion
    # lancé depuis le contexte d'une étape de chat : la tâche en reçoit une copie
    journal.commencer(etape=99, agent="plan", mission="mission-du-redacteur", tache=5)
    try:
        await service.lancer(did)
    finally:
        journal.commencer()
    await _attendre(client)
    assert vus == [{}, {}]
