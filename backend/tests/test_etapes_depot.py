import asyncio

from asgi_lifespan import LifespanManager
from conftest import CATALOGUE_TEST, git
from sqlalchemy import select

from portail.api import create_app
from portail.db import Document, Etape, Message, Pipeline, Projet


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
