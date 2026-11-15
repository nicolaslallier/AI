import asyncio
import json

from conftest import FauxAgent, _agent
from sqlalchemy import select

from portail.agents import Catalogue
from portail.db import Proposition
from portail.llm import ErreurLLM


async def _etape(client, type_="spec"):
    projet = (await client.post("/api/projets", json={"nom": "P"})).json()
    p = (
        await client.post("/api/pipelines", json={"projet_id": projet["id"], "type": type_})
    ).json()
    return p["id"], p["etapes"][0]["id"]


def _chat(client):
    return client._transport.app.state.chat


async def _attendre(client, etape_id):
    t = _chat(client).taches.get(etape_id)
    if t:
        await asyncio.wait_for(t, 5)


async def _etat(client, pipeline_id):
    return (await client.get(f"/api/pipelines/{pipeline_id}")).json()["etapes"][0]


async def _envoyer(client, etape_id, contenu):
    return await client.post(f"/api/etapes/{etape_id}/messages", json={"contenu": contenu})


async def test_echange_complet(client, faux_llm):
    pid, eid = await _etape(client)
    faux_llm.morceaux = ["<think>hm</think>", "Quelle ", "cible ?"]
    assert (await _envoyer(client, eid, "  Un portail ")).status_code == 202
    await _attendre(client, eid)
    e = await _etat(client, pid)
    assert [(m["role"], m["contenu"]) for m in e["messages"]] == [
        ("user", "Un portail"),
        ("assistant", "Quelle cible ?"),
    ]
    assert e["etat"] == "en_attente"
    assert faux_llm.appels[0]["messages"][0] == {"role": "system", "content": "Tu es spec."}


async def test_message_enregistre_avant_l_appel_et_reessayer(client, faux_llm):
    pid, eid = await _etape(client)
    faux_llm.exception = ErreurLLM("injoignable")
    await _envoyer(client, eid, "Salut")
    await _attendre(client, eid)
    e = await _etat(client, pid)
    assert e["etat"] == "echouee" and "injoignable" in e["erreur"]
    assert [m["role"] for m in e["messages"]] == ["user"]

    faux_llm.exception = None
    faux_llm.morceaux = ["Ok"]
    assert (await client.post(f"/api/etapes/{eid}/reessayer")).status_code == 202
    await _attendre(client, eid)
    e = await _etat(client, pid)
    assert [(m["role"], m["contenu"]) for m in e["messages"]] == [
        ("user", "Salut"),
        ("assistant", "Ok"),
    ]
    assert e["etat"] == "en_attente"


async def test_reessayer_refuse_si_pas_echouee(client):
    _, eid = await _etape(client)
    assert (await client.post(f"/api/etapes/{eid}/reessayer")).status_code == 409


async def test_double_envoi_409(client, faux_llm):
    _, eid = await _etape(client)
    pause = asyncio.Event()
    faux_llm.morceaux = [pause, "x"]
    assert (await _envoyer(client, eid, "un")).status_code == 202
    r = await _envoyer(client, eid, "deux")
    assert r.status_code == 409 and "déjà en cours" in r.json()["detail"]
    pause.set()
    await _attendre(client, eid)


async def test_message_vide_422(client):
    _, eid = await _etape(client)
    assert (await _envoyer(client, eid, "   ")).status_code == 422


async def test_reponse_vide_echoue(client, faux_llm):
    pid, eid = await _etape(client)
    faux_llm.morceaux = ["<think>rien</think>", "  "]
    await _envoyer(client, eid, "Salut")
    await _attendre(client, eid)
    e = await _etat(client, pid)
    assert e["etat"] == "echouee" and e["erreur"] == "réponse vide du modèle"
    assert [m["role"] for m in e["messages"]] == ["user"]


async def test_rediger_cree_le_brouillon_et_reduit_le_contexte(client, faux_llm):
    pid, eid = await _etape(client)
    for q, r in (("un", "r1"), ("deux", "r2")):
        faux_llm.morceaux = [r]
        await _envoyer(client, eid, q)
        await _attendre(client, eid)
    faux_llm.morceaux = ["# Spec\n", "..."]
    assert (await client.post(f"/api/etapes/{eid}/rediger")).status_code == 202
    await _attendre(client, eid)
    e = await _etat(client, pid)
    assert e["etat"] == "en_attente"
    assert e["document"]["etat"] == "brouillon" and e["document"]["contenu"] == "# Spec\n..."
    assert faux_llm.appels[-1]["messages"][-1] == {"role": "user", "content": "Rédige la spec."}
    dernier = e["messages"][-1]["id"]

    faux_llm.morceaux = ["ok"]
    await _envoyer(client, eid, "nouveau")
    await _attendre(client, eid)
    msgs = faux_llm.appels[-1]["messages"]
    assert [m["role"] for m in msgs] == ["system", "system", "user"]
    assert msgs[1]["content"].endswith("# Spec\n...") and msgs[2]["content"] == "nouveau"
    assert dernier == max(m["id"] for m in e["messages"])


async def test_rediger_refuse_sans_consigne(client):
    projet = (await client.post("/api/projets", json={"nom": "P"})).json()
    p = (
        await client.post("/api/pipelines", json={"projet_id": projet["id"], "type": "double"})
    ).json()
    r = await client.post(f"/api/etapes/{p['etapes'][0]['id']}/rediger")
    assert r.status_code == 409


async def test_contexte_plein_refuse(client):
    pid, eid = await _etape(client, "petit")
    r = await _envoyer(client, eid, "x" * 400)
    assert r.status_code == 409 and "Rédiger la spec" in r.json()["detail"]
    assert (await _etat(client, pid))["messages"] == []


def _evenements(corps: str):
    sortie = []
    for bloc in corps.strip().split("\n\n"):
        type_, donnees = bloc.split("\n")
        sortie.append((type_.removeprefix("event: "), json.loads(donnees.removeprefix("data: "))))
    return sortie


async def _poll(cond):
    for _ in range(500):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition jamais remplie")


async def test_flux_sse_et_reprise_en_cours(client, faux_llm):
    _, eid = await _etape(client)
    chat = _chat(client)
    pause = asyncio.Event()
    faux_llm.morceaux = ["A", pause, "B"]
    await _envoyer(client, eid, "go")
    await _poll(lambda: chat.diffuseur.partiels.get(eid) == "A")
    get = asyncio.create_task(client.get(f"/api/etapes/{eid}/flux"))
    await _poll(lambda: chat.diffuseur.abonnes.get(eid))
    pause.set()
    r = await asyncio.wait_for(get, 5)
    assert r.headers["content-type"].startswith("text/event-stream")
    assert _evenements(r.text) == [
        ("partiel", {"texte": "A"}),
        ("delta", {"texte": "B"}),
        ("fin", {}),
    ]
    await _attendre(client, eid)
    assert not chat.diffuseur.abonnes.get(eid)


async def test_flux_etape_inactive(client):
    _, eid = await _etape(client)
    r = await asyncio.wait_for(client.get(f"/api/etapes/{eid}/flux"), 5)
    assert _evenements(r.text) == [("fin", {})]


async def test_flux_etape_inconnue(client):
    assert (await client.get("/api/etapes/999/flux")).status_code == 404


async def test_erreur_publiee_meme_si_l_enregistrement_echoue(client, faux_llm):
    _, eid = await _etape(client)
    chat = _chat(client)
    pause = asyncio.Event()
    faux_llm.morceaux = [pause]
    faux_llm.exception = ErreurLLM("boum")
    await _envoyer(client, eid, "go")
    await _poll(lambda: faux_llm.appels)

    def _hs():
        raise RuntimeError("base hors service")

    chat._sessions = _hs
    _, file = chat.diffuseur.abonner(eid)
    tache = chat.taches[eid]
    pause.set()
    await asyncio.wait_for(tache, 5)  # lèverait si l'exception fuyait de la tâche
    assert file.get_nowait() == {"type": "erreur", "message": "boum"}


# --- agents en conteneur --------------------------------------------------


def _catalogue(nom, **kw):
    return Catalogue(
        agents={nom: _agent(nom, service=f"http://agent-{nom}:8080", **kw)},
        pipelines={nom: [nom]},
    )


async def test_agent_en_conteneur_streame(client_conteneur, faux_llm):
    faux = FauxAgent("spec")

    async def jouer(demande, portail):
        for t in ("Quelle ", "cible ?"):
            yield {"type": "texte", "texte": t}
        yield {
            "type": "fin", "texte": " Quelle cible ? ", "limite_atteinte": False,
            "messages": [{"role": "assistant", "content": "Quelle cible ?"}],
        }  # fmt: skip

    faux.jouer = jouer
    client = await client_conteneur(_catalogue("spec"), faux)
    pid, eid = await _etape(client)
    chat = _chat(client)
    _, file = chat.diffuseur.abonner(eid)
    await _envoyer(client, eid, "Un portail")
    await _attendre(client, eid)
    evenements = []
    while not file.empty():
        evenements.append(file.get_nowait())
    assert [e["texte"] for e in evenements if e["type"] == "delta"] == ["Quelle ", "cible ?"]
    e = await _etat(client, pid)
    assert [(m["role"], m["contenu"]) for m in e["messages"]] == [
        ("user", "Un portail"),
        ("assistant", "Quelle cible ?"),
    ]
    [mission] = faux.missions
    assert mission["corps"]["flux"] is True and mission["corps"]["outils"] == []
    assert faux_llm.appels == []


async def test_taches_en_conteneur_relance(client_conteneur, faux_llm, sessions):
    from test_etapes_depot import _planifier, _projet
    from test_propositions import _json, _n

    faux = FauxAgent("taches")
    catalogue = Catalogue(
        agents={
            "plan": _agent("plan", consigne_redaction="Rédige le plan.", produit="plan", auto=True),
            "taches": _agent(
                "taches", consigne_redaction="Propose les tâches.", produit="taches", auto=True,
                service="http://agent-taches:8080",
            ),
        },
        pipelines={"planification": ["plan", "taches"]},
    )  # fmt: skip
    client = await client_conteneur(catalogue, faux)
    pid = await _projet(sessions)
    faux_llm.morceaux = ["# Plan"]
    faux_llm.reponses = [{"content": "{oups"}, {"content": _json(_n("n1"))}]
    _, eid = await _planifier(client, pid)
    r = await client.post(f"/api/etapes/{eid}/valider")
    assert r.status_code == 200, r.text
    etape_taches = r.json()["etapes"][1]["id"]
    await _attendre(client, etape_taches)
    assert len(faux.missions) == 2  # la relance est une nouvelle mission
    assert faux.missions[1]["corps"]["messages"][-1]["content"].startswith("Réponse invalide : ")
    assert all(m["corps"]["outils"] == [] for m in faux.missions)
    async with sessions() as s:
        props = (
            await s.scalars(select(Proposition).where(Proposition.etape_id == etape_taches))
        ).all()
    assert [p.cle for p in props] == ["n1"]


async def test_modele_choisi_au_premier_message(client, faux_llm):
    pid, eid = await _etape(client)
    faux_llm.morceaux = ["r"]
    e = await _etat(client, pid)
    assert (e["modele"], e["modele_fige"], e["modeles"]) == ("m", False, ["m", "g"])
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "A", "modele": "g"})
    assert r.status_code == 202
    await _attendre(client, eid)
    assert faux_llm.appels[-1]["modele"] == "g"
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "B", "modele": "m"})
    assert r.status_code == 409  # figé : le changement n'est pas ignoré en silence
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "B", "modele": "g"})
    assert r.status_code == 202
    await _attendre(client, eid)
    assert faux_llm.appels[-1]["modele"] == "g"
    assert (await _etat(client, pid))["modele_fige"]


async def test_modele_non_permis_422(client):
    _, eid = await _etape(client)
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "A", "modele": "x"})
    assert r.status_code == 422


async def test_modele_non_enregistre_si_refus(client):
    pid, eid = await _etape(client)
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "  ", "modele": "g"})
    assert r.status_code == 422
    assert (await _etat(client, pid))["modele"] == "m"


async def test_rediger_utilise_le_modele_choisi(client, faux_llm):
    _, eid = await _etape(client)
    faux_llm.morceaux = ["r"]
    await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "A", "modele": "g"})
    await _attendre(client, eid)
    faux_llm.morceaux = ["# Spec"]
    assert (await client.post(f"/api/etapes/{eid}/rediger")).status_code == 202
    await _attendre(client, eid)
    assert faux_llm.appels[-1]["modele"] == "g"


async def test_modele_ignore_hors_spec(client_conteneur):
    cat = _catalogue("plan", produit="plan")
    cat.modeles_permis = ["m", "g"]
    client = await client_conteneur(cat, FauxAgent("plan"))
    pid, eid = await _etape(client, "plan")
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "A", "modele": "g"})
    assert r.status_code == 409
    e = await _etat(client, pid)
    assert (e["modele"], e["modele_fige"], e["modeles"]) == ("m", False, [])
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "A"})
    assert r.status_code == 202
    await _attendre(client, eid)
    assert not (await _etat(client, pid))["modele_fige"]  # hors spec : rien n'est figé


async def test_rediger_sans_message_fige_le_modele(client, faux_llm):
    pid, eid = await _etape(client)
    faux_llm.morceaux = ["# Spec"]
    assert (await client.post(f"/api/etapes/{eid}/rediger")).status_code == 202
    await _attendre(client, eid)
    faux_llm.morceaux = ["r"]
    assert (await _etat(client, pid))["modele_fige"]
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "A", "modele": "g"})
    assert r.status_code == 409
    assert (await _etat(client, pid))["modele"] == "m"


async def test_premier_message_sans_choix_fige_le_modele(client, faux_llm):
    pid, eid = await _etape(client)
    await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "A"})
    await _attendre(client, eid)
    e = await _etat(client, pid)
    assert (e["modele"], e["modele_fige"]) == ("m", True)
