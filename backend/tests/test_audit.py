import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from portail.audit import auteur_de, inscrire
from portail.db import ActionConversation, Audit, Conversation

MOI = {"X-Auth-Request-Email": "n@exemple.net"}


async def _lignes(sessions) -> list[Audit]:
    async with sessions() as s:
        return list((await s.scalars(select(Audit).order_by(Audit.id))).all())


async def _action(sessions) -> int:
    async with sessions() as s:
        c = Conversation()
        s.add(c)
        await s.flush()
        a = ActionConversation(conversation_id=c.id, nom="creer_projet", parametres={"nom": "X"})
        s.add(a)
        await s.commit()
        return a.id


async def _tache(client) -> int:
    pid = (await client.post("/api/projets", json={"nom": "P"})).json()["id"]
    r = await client.post(f"/api/projets/{pid}/taches", json={"titre": "T"})
    return r.json()["id"]


async def test_confirmer_inscrit(client, sessions, reglages):
    reglages.exiger_utilisateur = True
    aid = await _action(sessions)
    assert (await client.post(f"/api/actions/{aid}/confirmer", headers=MOI)).status_code == 202
    [ligne] = [x for x in await _lignes(sessions) if x.action == "action.confirmer"]
    assert (ligne.objet, ligne.objet_id, ligne.auteur) == (
        "action_conversation",
        aid,
        "n@exemple.net",
    )


async def test_sans_entete_local(client, sessions):
    aid = await _action(sessions)
    assert (await client.post(f"/api/actions/{aid}/confirmer")).status_code == 202
    [ligne] = [x for x in await _lignes(sessions) if x.action == "action.confirmer"]
    assert ligne.auteur == "local"


async def test_refuser_deplacer_annuler(client, sessions):
    aid = await _action(sessions)
    await client.post(f"/api/actions/{aid}/refuser")
    tid = await _tache(client)
    await client.post(f"/api/taches/{tid}/deplacer", json={"colonne": "prete"})
    assert (await client.post(f"/api/taches/{tid}/annuler")).status_code == 409  # rien à annuler
    actions = [(x.action, x.objet, x.objet_id) for x in await _lignes(sessions)]
    assert ("action.refuser", "action_conversation", aid) in actions
    assert ("tache.creer", "tache", tid) in actions
    assert ("tache.deplacer", "tache", tid) in actions
    assert not any(a[0] == "tache.annuler" for a in actions)  # le 409 n'inscrit rien


async def test_modifier_supprimer_projet(client, sessions):
    tid = await _tache(client)
    await client.patch(f"/api/taches/{tid}", json={"titre": "U"})
    await client.delete(f"/api/taches/{tid}")
    actions = [x.action for x in await _lignes(sessions)]
    assert actions == ["projet.creer", "tache.creer", "tache.modifier", "tache.supprimer"]


async def test_echec_non_inscrit(client, sessions):
    r = await client.post("/api/taches/999/deplacer", json={"colonne": "prete"})
    assert r.status_code == 404
    r = await client.post("/api/actions/999/confirmer")
    assert r.status_code == 404
    assert await _lignes(sessions) == []


async def test_lecture(client, sessions):
    async with sessions() as s:
        for i in range(3):
            inscrire(s, "n@exemple.net", "tache.creer", "tache", i + 1)
        await s.commit()
    r = await client.get("/api/audit", params={"limite": 2})
    ids = [x["id"] for x in r.json()]
    assert len(ids) == 2 and ids[0] > ids[1]
    suite = await client.get("/api/audit", params={"limite": 2, "avant": ids[1]})
    assert [x["id"] for x in suite.json()] == [ids[1] - 1]
    assert set(r.json()[0]) == {"id", "quand", "auteur", "action", "objet", "objet_id"}


@pytest.mark.parametrize("chemin", ["/api/audit", "/api/audit/1"])
@pytest.mark.parametrize("methode", ["post", "put", "patch", "delete"])
async def test_pas_d_ecriture(client, chemin, methode):
    assert (await getattr(client, methode)(chemin)).status_code in (404, 405)


async def test_survit_a_la_suppression(client, sessions):
    tid = await _tache(client)
    await client.delete(f"/api/taches/{tid}")
    lignes = [x for x in await _lignes(sessions) if x.objet == "tache"]
    assert [x.action for x in lignes] == ["tache.creer", "tache.supprimer"]


def _requete(exiger: bool, entete: str | None):
    reglages = SimpleNamespace(exiger_utilisateur=exiger)
    app = SimpleNamespace(state=SimpleNamespace(reglages=reglages))
    headers = {} if entete is None else {"X-Auth-Request-Email": entete}
    return SimpleNamespace(app=app, headers=headers)


def test_auteur_entete_ignore_sans_exiger():
    # sans oauth2-proxy devant, l'en-tête vient du client : forgeable
    assert auteur_de(_requete(False, "intrus@exemple.net")) == "local"


def test_auteur_entete_tronque_si_exige():
    assert auteur_de(_requete(True, "n@exemple.net")) == "n@exemple.net"
    assert auteur_de(_requete(True, "a" * 400)) == "a" * 320


async def test_creer_conversation_inscrit(client, sessions):
    cid = (await client.post("/api/conversations")).json()["id"]
    [ligne] = await _lignes(sessions)
    assert (ligne.action, ligne.objet, ligne.objet_id) == (
        "conversation.creer",
        "conversation",
        cid,
    )


async def test_audit_en_echec_ne_casse_pas_la_route(client, monkeypatch, caplog):
    secret = "contenu-secret"

    def casse(*_):
        raise SQLAlchemyError(secret)

    monkeypatch.setattr("portail.api.inscrire", casse)
    with caplog.at_level(logging.ERROR):
        r = await client.post("/api/conversations")
    assert r.status_code == 201  # l'action a eu lieu : pas de 500, pas de rejeu
    assert "SQLAlchemyError" in caplog.text and secret not in caplog.text
