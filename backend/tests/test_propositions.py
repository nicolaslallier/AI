import json

import pytest
from sqlalchemy import select
from test_etapes_depot import _attendre, _planifier, _projet

from portail.db import Etape, Message, Pipeline, Proposition, Tache, TacheEvenement
from portail.propositions import lire_propositions
from portail.schemas import DonneesTache
from portail.taches import creer_tache


def _n(cle, titre=None, depend_de=()):
    return {"sorte": "nouvelle", "cle": cle, "titre": titre or cle, "description": "",
            "criteres": [], "fichiers": [], "depend_de": list(depend_de)}  # fmt: skip


def _m(tache_id, titre):
    return {"sorte": "modification", "tache_id": tache_id, "titre": titre, "description": "",
            "criteres": [], "fichiers": [], "depend_de": []}  # fmt: skip


def _json(*props) -> str:
    return json.dumps({"propositions": list(props)})


@pytest.mark.parametrize(
    "texte, attendu",
    [
        ("{pas du json", "JSON"),
        (_json(_n("n1"), _n("n1")), "clé en double"),
        (_json(_n("n1", depend_de=["n1"])), "elle-même"),
        (_json(_n("n1", depend_de=["n9"])), "inconnue"),
        (_json(_n("n1", depend_de=["T999"])), "T999"),
        (_json({**_m(1, "x"), "depend_de": ["T1"]}), "elle-même"),
    ],
)
def test_lire_propositions(texte, attendu):
    with pytest.raises(ValueError, match=attendu):
        lire_propositions(texte, {1, 2})


def test_lire_propositions_valide():
    lues = lire_propositions(_json(_n("n1", depend_de=["T1"]), _n("n2", depend_de=["n1"])), {1})
    assert [p.cle for p in lues] == ["n1", "n2"]


async def _tache_agent(sessions, pid, titre="Existante") -> int:
    async with sessions() as s:
        t = await creer_tache(
            s, pid, DonneesTache(titre=titre), "agent:taches", origine="agent", protegee=False
        )
        await s.commit()
        return t.id


async def _lancer(client, sessions, faux_llm, *reponses, pid=None):
    """Plan streamé puis validé : l'étape de tâches démarre seule avec `reponses`."""
    pid = pid or await _projet(sessions)
    faux_llm.morceaux = ["# Plan"]
    faux_llm.reponses = [{"content": r} for r in reponses]
    pipeline_id, eid = await _planifier(client, pid)
    r = await client.post(f"/api/etapes/{eid}/valider")
    assert r.status_code == 200, r.text
    etape_taches = r.json()["etapes"][1]["id"]
    await _attendre(client, etape_taches)
    return pid, pipeline_id, etape_taches


async def _etat(sessions, modele, id_):
    async with sessions() as s:
        return (await s.get(modele, id_)).etat


async def _propositions(sessions, eid) -> list[Proposition]:
    async with sessions() as s:
        q = select(Proposition).where(Proposition.etape_id == eid).order_by(Proposition.id)
        return list((await s.scalars(q)).all())


async def _deps(client, pid):
    """(dépendances par titre, id par titre)"""
    taches = (await client.get(f"/api/projets/{pid}/kanban")).json()["taches"]
    return {t["titre"]: t["depend_de"] for t in taches}, {t["titre"]: t["id"] for t in taches}


async def test_etape_taches_cree_des_propositions(client, sessions, faux_llm):
    pid, _, eid = await _lancer(client, sessions, faux_llm, _json(_n("n1"), _n("n2")))
    appel = faux_llm.appels[-1]
    assert appel["response_format"]["json_schema"]["name"] == "propositions"
    systemes = [m["content"] for m in appel["messages"] if m["role"] == "system"]
    assert "Plan validé :\n\n# Plan" in systemes
    assert any(t.startswith("Tâches existantes (JSON) :\n\n") for t in systemes)
    assert appel["messages"][-1] == {"role": "user", "content": "Propose les tâches."}

    assert await _etat(sessions, Etape, eid) == "en_attente"
    props = await _propositions(sessions, eid)
    assert [(p.sorte, p.cle, p.etat) for p in props] == [
        ("nouvelle", "n1", "ouverte"),
        ("nouvelle", "n2", "ouverte"),
    ]
    kanban = (await client.get(f"/api/projets/{pid}/kanban")).json()
    assert len(kanban["propositions"]) == 2


async def test_reponse_invalide_relance_une_fois(client, sessions, faux_llm):
    _, _, eid = await _lancer(
        client, sessions, faux_llm, _json(_n("n1", depend_de=["n1"])), _json(_n("n1"))
    )
    assert await _etat(sessions, Etape, eid) == "en_attente"
    assert len(await _propositions(sessions, eid)) == 1
    dernier = faux_llm.appels[-1]["messages"][-1]
    assert dernier["role"] == "user" and dernier["content"].startswith("Réponse invalide : ")
    assert dernier["content"].endswith("Renvoie uniquement le JSON corrigé.")


async def test_reponse_invalide_deux_fois_echoue(client, sessions, faux_llm):
    _, _, eid = await _lancer(client, sessions, faux_llm, "{oups", _json(_n("n1", depend_de=["x"])))
    async with sessions() as s:
        etape = await s.get(Etape, eid)
    assert etape.etat == "echouee"
    assert etape.erreur.startswith("propositions invalides : ")
    assert "inconnue" in etape.erreur
    assert await _propositions(sessions, eid) == []


async def test_tout_accepter_resout_les_dependances(client, sessions, faux_llm):
    _pid, pipeline_id, eid = await _lancer(
        client, sessions, faux_llm, _json(_n("n1"), _n("n2", depend_de=["n1"]))
    )
    r = await client.post(f"/api/etapes/{eid}/propositions/tout-accepter")
    assert r.status_code == 200, r.text
    assert r.json()["perimees"] == 0
    assert r.json()["propositions"] == []
    taches = {t["titre"]: t for t in r.json()["taches"]}
    assert [t["colonne"] for t in taches.values()] == ["a_faire", "a_faire"]
    assert taches["n2"]["depend_de"] == [taches["n1"]["id"]]
    assert taches["n1"]["origine"] == "agent" and not taches["n1"]["protegee"]
    assert taches["n1"]["document_id"] is not None  # le plan validé du pipeline
    assert await _etat(sessions, Etape, eid) == "terminee"
    assert await _etat(sessions, Pipeline, pipeline_id) == "terminee"


async def test_accepter_dans_le_desordre_relie_quand_meme(client, sessions, faux_llm):
    pid, _, eid = await _lancer(
        client, sessions, faux_llm, _json(_n("n1"), _n("n2", depend_de=["n1"]))
    )
    p1, p2 = await _propositions(sessions, eid)
    assert (await client.post(f"/api/propositions/{p2.id}/accepter")).status_code == 200
    assert await _etat(sessions, Etape, eid) == "en_attente"
    r = await client.post(f"/api/propositions/{p1.id}/accepter")
    assert r.status_code == 200, r.text
    deps, ids = await _deps(client, pid)
    assert deps["n2"] == [ids["n1"]]
    assert await _etat(sessions, Etape, eid) == "terminee"
    # déjà acceptée : 409
    assert (await client.post(f"/api/propositions/{p1.id}/accepter")).status_code == 409
    assert (await client.post(f"/api/propositions/{p1.id}/rejeter")).status_code == 409


async def test_rejeter_puis_terminer(client, sessions, faux_llm):
    _pid, _, eid = await _lancer(
        client, sessions, faux_llm, _json(_n("n1"), _n("n2", depend_de=["n1"]))
    )
    p1, p2 = await _propositions(sessions, eid)
    assert (await client.post(f"/api/propositions/{p1.id}/rejeter")).status_code == 200
    r = await client.post(f"/api/propositions/{p2.id}/accepter")
    assert r.status_code == 200, r.text
    assert r.json()["taches"][0]["depend_de"] == []  # n1 rejetée : dépendance ignorée
    assert await _etat(sessions, Etape, eid) == "terminee"


async def test_modifier_puis_accepter_protege(client, sessions, faux_llm):
    _pid, _, eid = await _lancer(client, sessions, faux_llm, _json(_n("n1"), _n("n2")))
    p1, _ = await _propositions(sessions, eid)
    corps = {"donnees": {"titre": "Titre de Nicolas", "criteres": ["ok"]}}
    r = await client.post(f"/api/propositions/{p1.id}/accepter", json=corps)
    assert r.status_code == 200, r.text
    (t,) = r.json()["taches"]
    assert (t["titre"], t["criteres"], t["protegee"]) == ("Titre de Nicolas", ["ok"], True)
    async with sessions() as s:
        ev = await s.scalar(select(TacheEvenement).where(TacheEvenement.tache_id == t["id"]))
    assert (ev.type, ev.auteur) == ("creation", "nicolas")


async def test_proposition_sur_tache_protegee_ecartee(client, sessions, faux_llm):
    pid = await _projet(sessions)
    r = await client.post(f"/api/projets/{pid}/taches", json={"titre": "Manuelle"})
    tid = r.json()["id"]
    _, _, eid = await _lancer(
        client, sessions, faux_llm, _json(_m(tid, "Réécrite"), _n("n1")), pid=pid
    )
    props = await _propositions(sessions, eid)
    assert [p.sorte for p in props] == ["nouvelle"]
    async with sessions() as s:
        msgs = (
            await s.scalars(
                select(Message).where(Message.etape_id == eid, Message.role == "system")
            )
        ).all()
    assert [m.contenu for m in msgs] == [f"propositions écartées : T{tid} : tâche protégée"]


async def test_proposition_perimee(client, sessions, faux_llm):
    pid = await _projet(sessions)
    tid = await _tache_agent(sessions, pid)
    _, _, eid = await _lancer(client, sessions, faux_llm, _json(_m(tid, "Par l'agent")), pid=pid)
    (p,) = await _propositions(sessions, eid)
    assert p.version_tache == 1
    r = await client.patch(f"/api/taches/{tid}", json={"titre": "Par Nicolas"})
    assert r.status_code == 200
    r = await client.post(f"/api/propositions/{p.id}/accepter")
    assert r.status_code == 409
    assert "périmée" in r.json()["detail"]
    assert await _etat(sessions, Proposition, p.id) == "perimee"
    async with sessions() as s:
        assert (await s.get(Tache, tid)).titre == "Par Nicolas"
    assert await _etat(sessions, Etape, eid) == "terminee"  # plus rien d'ouvert


async def test_modification_acceptee(client, sessions, faux_llm):
    pid = await _projet(sessions)
    tid = await _tache_agent(sessions, pid)
    _, _, eid = await _lancer(client, sessions, faux_llm, _json(_m(tid, "Par l'agent")), pid=pid)
    r = await client.post(f"/api/etapes/{eid}/propositions/tout-accepter")
    assert r.status_code == 200, r.text
    (t,) = r.json()["taches"]
    assert (t["titre"], t["version"], t["protegee"]) == ("Par l'agent", 2, False)


async def test_tout_accepter_saute_les_perimees(client, sessions, faux_llm):
    pid = await _projet(sessions)
    tid = await _tache_agent(sessions, pid)
    _, _, eid = await _lancer(
        client, sessions, faux_llm, _json(_m(tid, "Par l'agent"), _n("n1")), pid=pid
    )
    await client.patch(f"/api/taches/{tid}", json={"titre": "Par Nicolas"})
    r = await client.post(f"/api/etapes/{eid}/propositions/tout-accepter")
    assert r.status_code == 200, r.text
    assert r.json()["perimees"] == 1
    assert sorted(t["titre"] for t in r.json()["taches"]) == ["Par Nicolas", "n1"]
    assert await _etat(sessions, Etape, eid) == "terminee"


async def test_retrait_accepte_supprime_et_journalise(client, sessions, faux_llm):
    pid = await _projet(sessions)
    tid = await _tache_agent(sessions, pid)
    retrait = {"sorte": "retrait", "tache_id": tid, "raison": "inutile"}
    _, _, eid = await _lancer(client, sessions, faux_llm, _json(retrait), pid=pid)
    (p,) = await _propositions(sessions, eid)
    r = await client.post(f"/api/propositions/{p.id}/accepter")
    assert r.status_code == 200, r.text
    assert r.json()["taches"] == []
    async with sessions() as s:
        ev = (
            await s.scalars(
                select(TacheEvenement)
                .where(TacheEvenement.tache_id == tid)
                .order_by(TacheEvenement.id)
            )
        ).all()
    assert [(e.type, e.auteur) for e in ev] == [
        ("creation", "agent:taches"),
        ("suppression", "agent:taches"),
    ]


async def test_aucune_proposition_termine_l_etape(client, sessions, faux_llm):
    _, pipeline_id, eid = await _lancer(client, sessions, faux_llm, _json())
    assert await _etat(sessions, Etape, eid) == "terminee"
    assert await _etat(sessions, Pipeline, pipeline_id) == "terminee"


async def test_proposition_inconnue_404(client):
    assert (await client.post("/api/propositions/999/accepter")).status_code == 404


async def test_annexe_montre_ce_qu_une_modification_reecrit(client, sessions, faux_llm):
    pid = await _projet(sessions)
    t1 = await _tache_agent(sessions, pid, "Base")
    async with sessions() as s:
        donnees = DonneesTache(titre="Suite", description="Détail précis", depend_de=[t1])
        t2 = (await creer_tache(s, pid, donnees, "nicolas")).id
        await s.commit()
    await _lancer(client, sessions, faux_llm, _json(), pid=pid)
    annexe = next(
        m["content"]
        for m in faux_llm.appels[-1]["messages"]
        if m["content"].startswith("Tâches existantes (JSON) :")
    )
    taches = {t["id"]: t for t in json.loads(annexe.split("\n\n", 1)[1])}
    assert taches[t2]["description"] == "Détail précis"
    assert taches[t2]["depend_de"] == [f"T{t1}"]
    assert {"criteres", "fichiers", "verrou"} <= taches[t2].keys()


async def test_dependance_inverse_ignore_les_cibles_de_modification(client, sessions, faux_llm):
    pid = await _projet(sessions)
    tid = await _tache_agent(sessions, pid)
    modif = {**_m(tid, "Par l'agent"), "depend_de": ["n1"]}
    _, _, eid = await _lancer(client, sessions, faux_llm, _json(modif, _n("n1")), pid=pid)
    pm, pn = await _propositions(sessions, eid)
    assert (await client.post(f"/api/propositions/{pm.id}/accepter")).status_code == 200
    assert (await client.post(f"/api/propositions/{pn.id}/accepter")).status_code == 200
    deps, _ = await _deps(client, pid)
    assert deps["Par l'agent"] == []


async def test_etape_de_propositions_refuse_le_chat(client, sessions, faux_llm):
    _, _, eid = await _lancer(client, sessions, faux_llm, _json(_n("n1")))
    for r in (
        await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "Salut"}),
        await client.post(f"/api/etapes/{eid}/rediger"),
    ):
        assert r.status_code == 409
        assert r.json()["detail"] == "étape de propositions : utiliser le kanban"


async def test_modification_partielle_garde_le_reste(client, sessions, faux_llm):
    pid = await _projet(sessions)
    t1 = await _tache_agent(sessions, pid, "Base")
    async with sessions() as s:
        donnees = DonneesTache(titre="Suite", criteres=["c"], depend_de=[t1])
        t2 = (
            await creer_tache(s, pid, donnees, "agent:taches", origine="agent", protegee=False)
        ).id
        await s.commit()
    modif = {"sorte": "modification", "tache_id": t2, "description": "Plus clair", "raison": "r"}
    _, _, eid = await _lancer(client, sessions, faux_llm, _json(modif), pid=pid)
    (p,) = await _propositions(sessions, eid)
    assert p.donnees == {"description": "Plus clair", "raison": "r"}
    assert (await client.post(f"/api/propositions/{p.id}/accepter")).status_code == 200
    kanban = (await client.get(f"/api/projets/{pid}/kanban")).json()
    t = next(x for x in kanban["taches"] if x["id"] == t2)
    assert (t["titre"], t["description"], t["criteres"], t["depend_de"]) == (
        "Suite",
        "Plus clair",
        ["c"],
        [t1],
    )


def test_modification_sans_titre_valide():
    (m,) = lire_propositions(_json({"sorte": "modification", "tache_id": 1, "criteres": []}), {1})
    assert m.model_dump(exclude_unset=True) == {
        "sorte": "modification",
        "tache_id": 1,
        "criteres": [],
    }
