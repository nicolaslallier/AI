import asyncio

import pytest
from asgi_lifespan import LifespanManager
from conftest import CATALOGUE_TEST, git
from sqlalchemy import select

from portail.api import create_app
from portail.db import Document, Etape, Message, Pipeline, Projet
from portail.etats import Etat
from portail.moteur import changer_etat


def _chat(client):
    return client._transport.app.state.chat


def _arbre(client, eid):
    return client._transport.app.state.reglages.donnees_dir / "arbres" / str(eid)


async def _attendre(client, etape_id):
    t = _chat(client).taches.get(etape_id)
    if t:
        await asyncio.wait_for(t, 10)


async def _projet(sessions, depot_url=None) -> int:
    """Projet écrit en base avec une spec validée : l'URL file:// contourne la validation."""
    async with sessions() as s:
        projet = Projet(nom="P", depot_url=depot_url)
        s.add(projet)
        await s.flush()
        p = Pipeline(projet_id=projet.id, type="spec", etat="terminee")
        p.etapes = [Etape(ordre=0, agent="spec", etat="terminee")]
        s.add(p)
        await s.flush()
        s.add(
            Document(
                projet_id=projet.id, pipeline_id=p.id, etape_id=p.etapes[0].id,
                type="spec", contenu="# Spec", etat="validee",
            )
        )  # fmt: skip
        await s.commit()
        return projet.id


def _outil(id_, nom, arguments):
    return {
        "content": None,
        "tool_calls": [{"id": id_, "function": {"name": nom, "arguments": arguments}}],
    }


async def _planifier(client, projet_id):
    r = await client.post("/api/pipelines", json={"projet_id": projet_id, "type": "planification"})
    assert r.status_code == 201, r.text
    p = r.json()
    eid = p["etapes"][0]["id"]
    await _attendre(client, eid)
    return p["id"], eid


async def _etape(sessions, eid) -> Etape:
    async with sessions() as s:
        return await s.get(Etape, eid)


def _systemes(appel) -> list[str]:
    return [m["content"] for m in appel["messages"] if m["role"] == "system"]


async def test_plan_demarre_seul_et_lit_le_depot(client, sessions, faux_llm, depot_origine):
    pid = await _projet(sessions, f"file://{depot_origine}")
    faux_llm.reponses = [_outil("1", "lire", '{"chemin": "README.md"}'), {"content": "# Plan"}]
    pipeline_id, eid = await _planifier(client, pid)

    sha = git(depot_origine, "rev-parse", "HEAD")
    systemes = _systemes(faux_llm.appels[0])
    assert "Spec courante :\n\n# Spec" in systemes
    assert any(t.startswith(f"Aperçu du dépôt (SHA {sha}) :\n\n") for t in systemes)
    assert "# Projet" in faux_llm.appels[1]["messages"][-1]["content"]  # résultat de lire

    etape = await _etape(sessions, eid)
    assert (etape.etat, etape.sha) == ("en_attente", sha)
    async with sessions() as s:
        doc = await s.scalar(select(Document).where(Document.etape_id == eid))
        outils = (
            await s.scalars(select(Message).where(Message.etape_id == eid, Message.role == "tool"))
        ).all()
    assert (doc.type, doc.etat, doc.contenu) == ("plan", "brouillon", "# Plan")
    assert [m.outil for m in outils] == ["lire(README.md)"]

    jauge = (await client.get(f"/api/pipelines/{pipeline_id}")).json()["etapes"][0]["jauge"]
    assert jauge["utilises"] > len(etape.apercu) // 4  # la jauge compte les annexes


async def test_plan_revise_le_plan_precedent(client, sessions, faux_llm, depot_origine):
    pid = await _projet(sessions, f"file://{depot_origine}")
    faux_llm.reponses = [{"content": "# Plan 1"}]
    _, eid = await _planifier(client, pid)
    r = await client.post(f"/api/etapes/{eid}/valider")
    assert r.status_code == 200, r.text
    assert not _arbre(client, eid).exists()  # libéré après la validation
    await _attendre(client, r.json()["etapes"][1]["id"])  # tâches : réponse vide, échoue

    faux_llm.appels.clear()
    faux_llm.reponses = [{"content": "# Plan 2"}]
    await _planifier(client, pid)
    assert "Plan validé précédent (à réviser) :\n\n# Plan 1" in _systemes(faux_llm.appels[0])


async def test_sha_fige_entre_deux_redactions(client, sessions, faux_llm, depot_origine):
    pid = await _projet(sessions, f"file://{depot_origine}")
    faux_llm.reponses = [{"content": "# Plan"}]
    _, eid = await _planifier(client, pid)
    avant = await _etape(sessions, eid)

    (depot_origine / "nouveau.txt").write_text("x")
    git(depot_origine, "add", "nouveau.txt")
    git(depot_origine, "commit", "-m", "nouveau")
    faux_llm.reponses = [{"content": "# Plan bis"}]
    assert (await client.post(f"/api/etapes/{eid}/rediger")).status_code == 202
    await _attendre(client, eid)

    apres = await _etape(sessions, eid)
    assert apres.etat == "en_attente"
    assert (apres.sha, apres.apercu) == (avant.sha, avant.apercu)


async def test_depot_injoignable_echoue_proprement(client, sessions, faux_llm, tmp_path):
    pid = await _projet(sessions, f"file://{tmp_path}/absent")
    _, eid = await _planifier(client, pid)
    etape = await _etape(sessions, eid)
    assert etape.etat == "echouee"
    assert etape.erreur.startswith("dépôt : ")
    assert faux_llm.appels == []


async def test_outils_mal_geres_echoue(client, sessions, faux_llm, depot_origine):
    pid = await _projet(sessions, f"file://{depot_origine}")
    faux_llm.reponses = [_outil(str(i), "inconnu", "{}") for i in range(3)]
    _, eid = await _planifier(client, pid)
    etape = await _etape(sessions, eid)
    assert etape.etat == "echouee"
    assert etape.erreur == "le modèle m ne gère pas correctement les outils"
    assert not _arbre(client, eid).exists()


async def test_spec_sans_depot_reste_streamee(client, faux_llm):
    projet = (await client.post("/api/projets", json={"nom": "P"})).json()
    corps = {"projet_id": projet["id"], "type": "spec"}
    eid = (await client.post("/api/pipelines", json=corps)).json()["etapes"][0]["id"]
    faux_llm.morceaux = ["Bonjour"]
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "Salut"})
    assert r.status_code == 202
    await _attendre(client, eid)
    assert len(faux_llm.appels) == 1
    assert "outils" not in faux_llm.appels[0]  # flux, pas completer


async def test_annuler_pipeline_en_cours(client, sessions, faux_llm, depot_origine):
    pid = await _projet(sessions, f"file://{depot_origine}")
    faux_llm.reponses = [asyncio.Event()]  # jamais signalé : le modèle reste bloqué
    r = await client.post("/api/pipelines", json={"projet_id": pid, "type": "planification"})
    pipeline_id, eid = r.json()["id"], r.json()["etapes"][0]["id"]
    for _ in range(200):
        if faux_llm.appels:
            break
        await asyncio.sleep(0.05)
    assert _arbre(client, eid).exists()

    r = await client.post(f"/api/pipelines/{pipeline_id}/annuler")
    assert r.status_code == 200, r.text
    etape = r.json()["etapes"][0]
    assert (etape["etat"], etape["erreur"]) == ("echouee", "annulé")
    assert r.json()["etat"] == "echouee"
    assert not _arbre(client, eid).exists()
    assert eid not in _chat(client).taches


async def test_annuler_pipeline_termine_409(client, sessions):
    pid = await _projet(sessions)
    async with sessions() as s:
        pipeline_id = await s.scalar(select(Pipeline.id).where(Pipeline.projet_id == pid))
    assert (await client.post(f"/api/pipelines/{pipeline_id}/annuler")).status_code == 409


async def test_redemarrage_nettoie_les_arbres(moteur, sessions, reglages, faux_llm):
    pid = await _projet(sessions)
    async with sessions() as s:
        p = Pipeline(projet_id=pid, type="spec")
        p.etapes = [Etape(ordre=0, agent="spec", etat="en_attente")]
        s.add(p)
        await s.flush()
        attente = p.etapes[0].id
        terminee = await s.scalar(select(Etape.id).where(Etape.etat == "terminee"))
        await s.commit()
    arbres = reglages.donnees_dir / "arbres"
    for i in (attente, terminee):
        (arbres / str(i)).mkdir(parents=True)

    app = create_app(reglages=reglages, llm=faux_llm, catalogue=CATALOGUE_TEST)
    async with LifespanManager(app):
        pass
    assert (arbres / str(attente)).exists()
    assert not (arbres / str(terminee)).exists()


async def _annuler_en_cours(client, sessions, faux_llm, depot_origine):
    pid = await _projet(sessions, f"file://{depot_origine}")
    faux_llm.reponses = [asyncio.Event()]
    r = await client.post("/api/pipelines", json={"projet_id": pid, "type": "planification"})
    pipeline_id, eid = r.json()["id"], r.json()["etapes"][0]["id"]
    for _ in range(200):
        if faux_llm.appels:
            break
        await asyncio.sleep(0.05)
    assert (await client.post(f"/api/pipelines/{pipeline_id}/annuler")).status_code == 200
    return eid


async def test_etape_annulee_ne_se_relance_pas(client, sessions, faux_llm, depot_origine):
    eid = await _annuler_en_cours(client, sessions, faux_llm, depot_origine)
    for route in ("reessayer", "rediger"):
        r = await client.post(f"/api/etapes/{eid}/{route}")
        assert (r.status_code, r.json()["detail"]) == (409, "étape annulée")
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "x"})
    assert (r.status_code, r.json()["detail"]) == (409, "étape annulée")
    assert (await _etape(sessions, eid)).etat == "echouee"


@pytest.mark.parametrize("echec", [False, True])
async def test_tache_n_ecrase_pas_une_etape_annulee(client, sessions, faux_llm, echec):
    """Course : l'étape est annulée en base pendant que la tâche de fond tourne encore."""
    projet = (await client.post("/api/projets", json={"nom": "P"})).json()
    corps = {"projet_id": projet["id"], "type": "spec"}
    eid = (await client.post("/api/pipelines", json=corps)).json()["etapes"][0]["id"]
    signal = asyncio.Event()
    faux_llm.morceaux = ["Bonjour", signal]
    faux_llm.exception = RuntimeError("boum") if echec else None
    assert (
        await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "S"})
    ).status_code == 202
    for _ in range(200):
        if faux_llm.appels:
            break
        await asyncio.sleep(0.05)
    async with sessions() as s:
        e = await s.get(Etape, eid)
        await changer_etat(s, e, Etat.ECHOUEE, "annulé")
        await s.commit()
    signal.set()
    await _attendre(client, eid)
    etape = await _etape(sessions, eid)
    assert (etape.etat, etape.erreur) == ("echouee", "annulé")
    async with sessions() as s:
        roles = (await s.scalars(select(Message.role).where(Message.etape_id == eid))).all()
    assert roles == ["user"]


async def test_annuler_ne_touche_que_les_etapes_actives(client, sessions, monkeypatch):
    pid = await _projet(sessions)
    async with sessions() as s:
        p = Pipeline(projet_id=pid, type="double")
        p.etapes = [
            Etape(ordre=0, agent="a", etat="terminee"),
            Etape(ordre=1, agent="b", etat="en_attente"),
        ]
        s.add(p)
        await s.flush()
        pipeline_id, faite, active = p.id, p.etapes[0].id, p.etapes[1].id
        await s.commit()
    liberees = []

    async def liberer(etape_id):
        liberees.append(etape_id)

    monkeypatch.setattr(_chat(client)._depots, "liberer", liberer)
    _, file_faite = _chat(client).diffuseur.abonner(faite)
    _, file_active = _chat(client).diffuseur.abonner(active)
    assert (await client.post(f"/api/pipelines/{pipeline_id}/annuler")).status_code == 200
    assert liberees == [active]
    assert file_faite.empty()
    assert file_active.get_nowait() == {"type": "erreur", "message": "annulé"}


async def test_limite_d_appels_signalee(client, sessions, faux_llm, depot_origine, monkeypatch):
    plan = CATALOGUE_TEST.agents["plan"]
    monkeypatch.setitem(CATALOGUE_TEST.agents, "plan", plan.model_copy(update={"tours_max": 1}))
    pid = await _projet(sessions, f"file://{depot_origine}")
    faux_llm.reponses = [_outil("1", "lire", '{"chemin": "README.md"}'), {"content": "# Plan"}]
    _, eid = await _planifier(client, pid)
    async with sessions() as s:
        systemes = (
            await s.scalars(
                select(Message.contenu).where(Message.etape_id == eid, Message.role == "system")
            )
        ).all()
    assert systemes == ["limite de 1 appels d'outils atteinte : la réponse peut être incomplète"]
    assert (await _etape(sessions, eid)).etat == "en_attente"


async def test_reessayer_refuse_si_une_autre_planification_est_active(client, sessions, faux_llm):
    pid = await _projet(sessions)
    faux_llm.exception = RuntimeError("boum")
    p1, e1 = await _planifier(client, pid)
    assert (await _etape(sessions, e1)).etat == "echouee"
    faux_llm.exception, faux_llm.morceaux = None, ["# Plan"]
    p2, _ = await _planifier(client, pid)
    r = await client.post(f"/api/etapes/{e1}/reessayer")
    assert (r.status_code, r.json()["detail"]) == (
        409,
        "une autre planification est active pour ce projet",
    )
    assert (await _etape(sessions, e1)).etat == "echouee"
    assert (await client.post(f"/api/pipelines/{p2}/annuler")).status_code == 200
    assert (await client.post(f"/api/etapes/{e1}/reessayer")).status_code == 202
    await _attendre(client, e1)
    assert (await _etape(sessions, e1)).etat == "en_attente"
    assert p1 != p2


async def test_annuler_clot_un_pipeline_echoue(client, sessions, faux_llm):
    pid = await _projet(sessions)
    faux_llm.exception = RuntimeError("boum")
    pipeline_id, eid = await _planifier(client, pid)
    r = await client.post(f"/api/pipelines/{pipeline_id}/annuler")
    assert r.status_code == 200, r.text
    assert (r.json()["etat"], r.json()["etapes"][0]["erreur"]) == ("echouee", "annulé")
    r = await client.post(f"/api/etapes/{eid}/reessayer")
    assert (r.status_code, r.json()["detail"]) == (409, "étape annulée")
    r = await client.post(f"/api/pipelines/{pipeline_id}/annuler")
    assert (r.status_code, r.json()["detail"]) == (409, "pipeline déjà annulé")


async def test_corriger_refuse_une_etape_annulee(client, sessions, faux_llm):
    pid = await _projet(sessions)
    faux_llm.morceaux = ["# Plan"]
    pipeline_id, eid = await _planifier(client, pid)
    assert (await client.post(f"/api/pipelines/{pipeline_id}/annuler")).status_code == 200
    r = await client.put(f"/api/etapes/{eid}/document", json={"contenu": "x"})
    assert (r.status_code, r.json()["detail"]) == (409, "étape annulée")
