import asyncio
import json

from sqlalchemy import update
from test_chat import _chat, _poll

from portail.db import Document
from portail.llm import ErreurLLM


def _bloc(prefixe, cites=()):
    """Texte suivi d'un bloc de modèle valide : un élément `<prefixe>a` et une vue."""
    ident = f"{prefixe}a"
    modele = {
        "elements": [{"id": ident, "type": "BusinessActor", "nom": "A"}],
        "vues": [{"nom": "V", "elements": [ident, *cites]}],
    }
    return f"Texte {prefixe}\n\n```json\n{json.dumps(modele)}\n```"


VISION, VOLET, SYNTHESE = _bloc("mot-"), _bloc("aff-", ["mot-a"]), _bloc("ent-", ["aff-a"])


async def _attendre_tout(client):
    """Attend les tâches de fond, y compris celles qu'elles lancent en finissant."""
    chat = _chat(client)
    while chat.taches:
        await asyncio.wait_for(asyncio.gather(*list(chat.taches.values())), 5)


async def _projet(client):
    return (await client.post("/api/projets", json={"nom": "P"})).json()["id"]


async def _architecture(client, projet_id=None):
    projet_id = projet_id or await _projet(client)
    r = await client.post("/api/pipelines", json={"projet_id": projet_id, "type": "architecture"})
    assert r.status_code == 201, r.text
    return r.json()


async def _pipeline(client, pid):
    return (await client.get(f"/api/pipelines/{pid}")).json()


async def _etats(client, pid):
    return [e["etat"] for e in (await _pipeline(client, pid))["etapes"]]


async def _vision_redigee(client, faux_llm, *suite):
    """Pipeline dont la vision a un brouillon valide ; `suite` : réponses des appels suivants."""
    p = await _architecture(client)
    faux_llm.file = [[VISION], *suite]
    eid = p["etapes"][0]["id"]
    assert (await client.post(f"/api/etapes/{eid}/rediger")).status_code == 202
    await _attendre_tout(client)
    return p["id"], [e["id"] for e in p["etapes"]]


async def test_chaine_complete(client, faux_llm):
    pid, (vision, *_) = await _vision_redigee(client, faux_llm, [VOLET], [SYNTHESE])
    assert (await client.post(f"/api/etapes/{vision}/valider")).status_code == 200
    await _attendre_tout(client)
    etapes = (await _pipeline(client, pid))["etapes"]
    assert [e["etat"] for e in etapes] == ["terminee", "terminee", "en_attente"]
    assert etapes[1]["document"]["etat"] == "validee"
    assert etapes[1]["document"]["contenu"] == VOLET
    assert etapes[2]["document"]["etat"] == "brouillon"
    assert etapes[2]["document"]["contenu"] == SYNTHESE
    systeme = [m["content"] for m in faux_llm.appels[2]["messages"] if m["role"] == "system"]
    assert "Vision validée :\n\n" + VISION in systeme
    assert "Volet affaires (volet) :\n\n" + VOLET in systeme


async def test_volet_recoit_la_vision_en_annexe(client, faux_llm):
    _, (vision, *_) = await _vision_redigee(client, faux_llm, [VOLET], [SYNTHESE])
    await client.post(f"/api/etapes/{vision}/valider")
    await _attendre_tout(client)
    systeme = [m["content"] for m in faux_llm.appels[1]["messages"] if m["role"] == "system"]
    [annexe] = [c for c in systeme if c.startswith("Vision validée :")]
    assert annexe.endswith(VISION) and "```json" in annexe


async def test_bloc_absent_fait_echouer_le_volet(client, faux_llm):
    pid, (vision, *_) = await _vision_redigee(client, faux_llm, ["Pas de bloc."])
    await client.post(f"/api/etapes/{vision}/valider")
    await _attendre_tout(client)
    etapes = (await _pipeline(client, pid))["etapes"]
    assert [e["etat"] for e in etapes] == ["terminee", "echouee", "a_faire"]
    assert "bloc de modèle absent" in etapes[1]["erreur"]
    assert etapes[1]["document"] is None


async def test_reessayer_un_volet_echoue_reprend_la_chaine(client, faux_llm):
    pid, (vision, volet, _) = await _vision_redigee(client, faux_llm, ["Pas de bloc."])
    await client.post(f"/api/etapes/{vision}/valider")
    await _attendre_tout(client)
    faux_llm.file = [[VOLET], [SYNTHESE]]
    assert (await client.post(f"/api/etapes/{volet}/reessayer")).status_code == 202
    await _attendre_tout(client)
    etapes = (await _pipeline(client, pid))["etapes"]
    assert [e["etat"] for e in etapes] == ["terminee", "terminee", "en_attente"]
    assert etapes[1]["action"] == "rediger"
    assert etapes[1]["document"]["etat"] == "validee"


async def test_rediger_un_bloc_invalide_garde_le_brouillon(client, faux_llm):
    pid, (vision, *_) = await _vision_redigee(client, faux_llm, [_bloc("aff-")])
    avant = (await _pipeline(client, pid))["etapes"][0]["document"]
    assert (await client.post(f"/api/etapes/{vision}/rediger")).status_code == 202
    await _attendre_tout(client)
    e = (await _pipeline(client, pid))["etapes"][0]
    assert e["etat"] == "echouee" and "préfixe « mot- » attendu" in e["erreur"]
    assert e["document"] == avant


async def test_corriger_un_brouillon_au_bloc_casse_422(client, faux_llm):
    pid, (vision, *_) = await _vision_redigee(client, faux_llm)
    r = await client.put(
        f"/api/etapes/{vision}/document", json={"contenu": "Texte\n\n```json\n{oups\n```"}
    )
    assert r.status_code == 422 and "JSON illisible" in r.json()["detail"]
    doc = (await _pipeline(client, pid))["etapes"][0]["document"]
    assert (doc["contenu"], doc["version"], doc["etat"]) == (VISION, 1, "brouillon")
    r = await client.put(f"/api/etapes/{vision}/document", json={"contenu": _bloc("mot-", [])})
    assert r.status_code == 200 and r.json()["version"] == 2


async def test_valider_la_vision_au_bloc_invalide_422(client, faux_llm, sessions):
    pid, (vision, *_) = await _vision_redigee(client, faux_llm)
    async with sessions() as s:  # brouillon abîmé hors du portail
        await s.execute(
            update(Document).where(Document.etape_id == vision).values(contenu="sans bloc")
        )
        await s.commit()
    r = await client.post(f"/api/etapes/{vision}/valider")
    assert r.status_code == 422 and r.json()["detail"] == "bloc de modèle absent"
    e = (await _pipeline(client, pid))["etapes"][0]
    assert e["etat"] == "en_attente" and e["document"]["etat"] == "brouillon"
    assert await _etats(client, pid) == ["en_attente", "a_faire", "a_faire"]


async def test_deuxieme_architecture_active_409(client, faux_llm):
    projet = await _projet(client)
    premier = await _architecture(client, projet)
    r = await client.post("/api/pipelines", json={"projet_id": projet, "type": "architecture"})
    assert r.status_code == 409
    assert r.json()["detail"] == "une architecture est déjà en cours pour ce projet"
    # la première échoue : une autre peut démarrer, et la première ne se relance plus
    faux_llm.exception = ErreurLLM("injoignable")
    vision = premier["etapes"][0]["id"]
    await client.post(f"/api/etapes/{vision}/rediger")
    await _attendre_tout(client)
    assert (await _etats(client, premier["id"]))[0] == "echouee"
    await _architecture(client, projet)
    r = await client.post(f"/api/etapes/{vision}/reessayer")
    assert r.status_code == 409
    assert r.json()["detail"] == "une autre architecture est active pour ce projet"


async def test_architecture_sans_spec_201(client):
    p = await _architecture(client)
    assert [e["etat"] for e in p["etapes"]] == ["en_attente", "a_faire", "a_faire"]


async def test_annuler_pendant_un_volet_n_enchaine_pas(client, faux_llm):
    pause = asyncio.Event()
    pid, (vision, *_) = await _vision_redigee(client, faux_llm, [pause, VOLET], [SYNTHESE])
    await client.post(f"/api/etapes/{vision}/valider")
    await _poll(lambda: len(faux_llm.appels) == 2)  # le volet attend le modèle
    assert (await client.post(f"/api/pipelines/{pid}/annuler")).status_code == 200
    pause.set()
    await _attendre_tout(client)
    etapes = (await _pipeline(client, pid))["etapes"]
    assert [e["etat"] for e in etapes] == ["terminee", "echouee", "a_faire"]
    assert etapes[1]["erreur"] == "annulé" and etapes[1]["document"] is None
    assert len(faux_llm.appels) == 2


def test_apercu_borne():
    from portail.chat import budget_apercu

    assert budget_apercu(200_000) == 8192
    assert budget_apercu(32_768) == 8192
    assert budget_apercu(16_000) == 4000
