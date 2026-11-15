import asyncio
import json

from asgi_lifespan import LifespanManager
from conftest import CATALOGUE_TEST, FauxLLM, _agent
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from portail import conversations
from portail.actions import ACTIONS
from portail.agents import OUTILS_ACTIONS_PORTAIL, Catalogue
from portail.api import create_app
from portail.db import (
    ActionConversation,
    Conversation,
    Etape,
    MessageConversation,
    Pipeline,
    Tache,
)
from portail.llm import ErreurLLM
from portail.outils_portail import OutilsPortail


def _service(client):
    return client._transport.app.state.conversations


async def _attendre(client, cid):
    t = _service(client).taches.get(cid)
    if t:
        await asyncio.wait_for(t, 5)


async def _creer(client) -> int:
    r = await client.post("/api/conversations")
    assert r.status_code == 201
    return r.json()["id"]


async def _envoyer(client, cid, contenu):
    return await client.post(f"/api/conversations/{cid}/messages", json={"contenu": contenu})


async def _detail(client, cid):
    return (await client.get(f"/api/conversations/{cid}")).json()


def _texte(contenu):
    return {"content": contenu}


def _appel(nom, arguments="{}"):
    return {
        "content": None,
        "tool_calls": [
            {"id": "a1", "type": "function", "function": {"name": nom, "arguments": arguments}}
        ],
    }


async def test_echange_complet(client, faux_llm):
    cid = await _creer(client)
    faux_llm.reponses = [_texte("<think>hm</think>Salut !")]
    assert (await _envoyer(client, cid, "  Bonjour ")).status_code == 202
    await _attendre(client, cid)
    d = await _detail(client, cid)
    assert [(m["role"], m["contenu"]) for m in d["messages"]] == [
        ("user", "Bonjour"),
        ("assistant", "Salut !"),
    ]
    assert d["etat"] == "pret" and d["titre"] == "Bonjour" and d["erreur"] is None
    assert d["jauge"]["niveau"] == "ok"
    assert faux_llm.appels[0]["messages"][0] == {
        "role": "system",
        "content": "Tu es orchestrateur.",
    }
    liste = (await client.get("/api/conversations")).json()
    assert [(c["id"], c["titre"], c["etat"]) for c in liste] == [(cid, "Bonjour", "pret")]


async def test_identifiants_d_une_conversation(client, faux_llm):
    cid = await _creer(client)
    faux_llm.reponses = [_texte("Salut")]
    await _envoyer(client, cid, "Bonjour")
    await _attendre(client, cid)
    c = faux_llm.appels[0]["contexte"]
    assert (c["conversation"], c["agent"]) == (cid, "orchestrateur")
    assert c["mission"] and "etape" not in c


async def test_message_enregistre_avant_l_appel(client, faux_llm):
    cid = await _creer(client)
    faux_llm.exception = ErreurLLM("boom")
    await _envoyer(client, cid, "Salut")
    await _attendre(client, cid)
    d = await _detail(client, cid)
    assert d["etat"] == "erreur" and "boom" in d["erreur"]
    assert [m["role"] for m in d["messages"]] == ["user"]

    faux_llm.exception = None
    faux_llm.reponses = [_texte("Ok")]
    assert (await client.post(f"/api/conversations/{cid}/reessayer")).status_code == 202
    await _attendre(client, cid)
    d = await _detail(client, cid)
    assert d["etat"] == "pret" and d["erreur"] is None
    assert [(m["role"], m["contenu"]) for m in d["messages"]] == [
        ("user", "Salut"),
        ("assistant", "Ok"),
    ]


async def test_envoi_accepte_apres_erreur(client, faux_llm):
    cid = await _creer(client)
    faux_llm.exception = ErreurLLM("boom")
    await _envoyer(client, cid, "un")
    await _attendre(client, cid)
    faux_llm.exception = None
    faux_llm.reponses = [_texte("Ok")]
    assert (await _envoyer(client, cid, "deux")).status_code == 202
    await _attendre(client, cid)
    assert (await _detail(client, cid))["etat"] == "pret"


async def test_reessayer_refuse_si_pas_en_erreur(client):
    cid = await _creer(client)
    r = await client.post(f"/api/conversations/{cid}/reessayer")
    assert r.status_code == 409 and r.json()["detail"] == "rien à relancer"


async def test_double_envoi_409(client, faux_llm):
    cid = await _creer(client)
    pause = asyncio.Event()
    faux_llm.reponses = [pause, _texte("x")]
    assert (await _envoyer(client, cid, "un")).status_code == 202
    r = await _envoyer(client, cid, "deux")
    assert r.status_code == 409 and r.json()["detail"] == "une réponse est déjà en cours"
    pause.set()
    await _attendre(client, cid)


async def test_message_vide_422(client):
    cid = await _creer(client)
    r = await _envoyer(client, cid, "   ")
    assert r.status_code == 422 and r.json()["detail"] == "le message est vide"


async def test_conversation_inconnue_404(client):
    assert (await _envoyer(client, 999, "x")).status_code == 404
    assert (await client.get("/api/conversations/999")).status_code == 404
    assert (await client.get("/api/conversations/999/flux")).status_code == 404


async def test_reponse_vide_erreur(client, faux_llm):
    cid = await _creer(client)
    faux_llm.reponses = [_texte("<think>rien</think>  ")]
    await _envoyer(client, cid, "Salut")
    await _attendre(client, cid)
    d = await _detail(client, cid)
    assert d["etat"] == "erreur" and d["erreur"] == "réponse vide du modèle"
    assert [m["role"] for m in d["messages"]] == ["user"]


async def test_contexte_plein_409(client):
    cid = await _creer(client)
    r = await _envoyer(client, cid, "x" * 130_000)
    assert r.status_code == 409
    assert r.json()["detail"] == "contexte plein : ouvre une nouvelle conversation"
    assert (await _detail(client, cid))["messages"] == []


async def test_outils_de_lecture(client, faux_llm):
    await client.post("/api/projets", json={"nom": "Alpha"})
    cid = await _creer(client)
    faux_llm.reponses = [_appel("lister_projets"), _texte("Un projet : Alpha.")]
    await _envoyer(client, cid, "Quels projets ?")
    await _attendre(client, cid)
    d = await _detail(client, cid)
    assert [m["role"] for m in d["messages"]] == ["user", "tool", "assistant"]
    outil = d["messages"][1]
    assert outil["outil"].startswith("lister_projets") and "Alpha" in outil["contenu"]
    noms = {o["function"]["name"] for o in faux_llm.appels[0]["outils"]}
    assert "lister_projets" in noms


async def test_outils_non_rejoues(client, faux_llm):
    cid = await _creer(client)
    faux_llm.reponses = [_appel("lister_projets"), _texte("Aucun.")]
    await _envoyer(client, cid, "un")
    await _attendre(client, cid)
    faux_llm.reponses = [_texte("Toujours aucun.")]
    await _envoyer(client, cid, "deux")
    await _attendre(client, cid)
    msgs = faux_llm.appels[-1]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]


async def test_agent_sans_outils_streame(moteur, reglages):
    llm = FauxLLM()
    cat = Catalogue(
        agents={**CATALOGUE_TEST.agents, "orchestrateur": _agent("orchestrateur")},
        pipelines=CATALOGUE_TEST.pipelines,
    )
    app = create_app(reglages=reglages, llm=llm, catalogue=cat)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        cid = await _creer(c)
        llm.morceaux = ["<think>x</think>", "Bon", "jour"]
        await _envoyer(c, cid, "Salut")
        await _attendre(c, cid)
        d = await _detail(c, cid)
    assert [(m["role"], m["contenu"]) for m in d["messages"]] == [
        ("user", "Salut"),
        ("assistant", "Bonjour"),
    ]


async def test_agent_absent_409(moteur, reglages):
    agents = {k: v for k, v in CATALOGUE_TEST.agents.items() if k != "orchestrateur"}
    cat = Catalogue(agents=agents, pipelines=CATALOGUE_TEST.pipelines)
    app = create_app(reglages=reglages, llm=FauxLLM(), catalogue=cat)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        r = await c.post("/api/conversations")
    assert r.status_code == 409
    assert r.json()["detail"] == "agent « orchestrateur » absent de agents.yaml"


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


async def test_flux_sse(client, faux_llm):
    cid = await _creer(client)
    service = _service(client)
    pause = asyncio.Event()
    faux_llm.reponses = [_appel("lister_projets"), pause, _texte("Fini")]
    await _envoyer(client, cid, "go")
    await _poll(lambda: len(faux_llm.appels) == 2)
    get = asyncio.create_task(client.get(f"/api/conversations/{cid}/flux"))
    await _poll(lambda: service.diffuseur.abonnes.get(cid))
    pause.set()
    r = await asyncio.wait_for(get, 5)
    assert r.headers["content-type"].startswith("text/event-stream")
    assert _evenements(r.text) == [
        ("partiel", {"texte": ""}),
        ("delta", {"texte": "Fini"}),
        ("fin", {}),
    ]
    await _attendre(client, cid)
    assert not service.diffuseur.abonnes.get(cid)
    r = await asyncio.wait_for(client.get(f"/api/conversations/{cid}/flux"), 5)
    assert _evenements(r.text) == [("fin", {})]


async def test_flux_publie_les_outils(client, faux_llm):
    cid = await _creer(client)
    service = _service(client)
    pause = asyncio.Event()
    faux_llm.reponses = [pause, _appel("lister_projets"), _texte("Fini")]
    await _envoyer(client, cid, "go")
    await _poll(lambda: faux_llm.appels)
    _, file = service.diffuseur.abonner(cid)
    pause.set()
    await _attendre(client, cid)
    vus = [file.get_nowait() for _ in range(file.qsize())]
    assert [e["type"] for e in vus] == ["outil", "delta", "fin"]
    assert vus[0]["libelle"].startswith("lister_projets")


async def test_erreur_publiee_meme_si_l_enregistrement_echoue(client, faux_llm):
    cid = await _creer(client)
    service = _service(client)
    pause = asyncio.Event()
    faux_llm.reponses = [pause]  # puis IndexError : plus de réponse
    await _envoyer(client, cid, "go")
    await _poll(lambda: faux_llm.appels)

    def _hs():
        raise RuntimeError("base hors service")

    service._sessions = _hs
    _, file = service.diffuseur.abonner(cid)
    pause.set()
    await _attendre(client, cid)
    assert file.get_nowait()["type"] == "erreur"


async def test_renommer(client):
    cid = await _creer(client)
    r = await client.patch(f"/api/conversations/{cid}", json={"titre": "Revue"})
    assert r.status_code == 200 and r.json()["titre"] == "Revue"
    assert (await _detail(client, cid))["titre"] == "Revue"


async def test_supprimer_en_cours_409(client, faux_llm):
    cid = await _creer(client)
    pause = asyncio.Event()
    faux_llm.reponses = [pause, _texte("x")]
    await _envoyer(client, cid, "un")
    assert (await client.delete(f"/api/conversations/{cid}")).status_code == 409
    pause.set()
    await _attendre(client, cid)


async def test_supprimer(client, faux_llm):
    cid = await _creer(client)
    faux_llm.reponses = [_texte("x")]
    await _envoyer(client, cid, "un")
    await _attendre(client, cid)
    assert (await client.delete(f"/api/conversations/{cid}")).status_code == 204
    assert (await client.get(f"/api/conversations/{cid}")).status_code == 404
    assert (await client.get("/api/conversations")).json() == []


async def test_redemarrage_marque_erreur(client, sessions, reglages):
    cid = await _creer(client)
    async with sessions() as s:
        (await s.get(Conversation, cid)).etat = "en_cours"
        await s.commit()
    app = create_app(reglages=reglages, llm=FauxLLM(), catalogue=CATALOGUE_TEST)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        d = await _detail(c, cid)
    assert d["etat"] == "erreur" and d["erreur"] == "interrompue par un redémarrage du serveur"


# --- actions -----------------------------------------------------------


async def _proposer(client, faux_llm, nom, parametres, cid=None):
    cid = cid or await _creer(client)
    faux_llm.reponses = [_appel(nom, json.dumps(parametres)), _texte("Je propose.")]
    await _envoyer(client, cid, "fais-le")
    await _attendre(client, cid)
    return cid, (await _detail(client, cid))["actions"]


async def _confirmer(client, aid):
    return await client.post(f"/api/actions/{aid}/confirmer")


async def _projets(client):
    return (await client.get("/api/projets")).json()


async def _tache_verrouillee(client, sessions) -> tuple[int, int, int]:
    pid = (await client.post("/api/projets", json={"nom": "P"})).json()["id"]
    tid = (await client.post(f"/api/projets/{pid}/taches", json={"titre": "T"})).json()["id"]
    async with sessions() as s:
        pl = Pipeline(projet_id=pid, type="spec", etat="en_cours")
        s.add(pl)
        await s.flush()
        t = await s.get(Tache, tid)
        t.verrou, t.colonne = pl.id, "en_cours"
        await s.commit()
        return pid, tid, pl.id


def test_noms_d_actions_alignes():
    assert set(OUTILS_ACTIONS_PORTAIL) == set(ACTIONS)


async def test_suppression_efface_messages_et_actions(client, sessions, faux_llm):
    cid, _ = await _proposer(client, faux_llm, "creer_projet", {"nom": "Beta"})

    async def compter(modele):
        async with sessions() as s:
            return await s.scalar(
                select(func.count()).select_from(modele).where(modele.conversation_id == cid)
            )

    assert await compter(MessageConversation) >= 2 and await compter(ActionConversation) == 1
    assert (await client.delete(f"/api/conversations/{cid}")).status_code == 204
    assert await compter(MessageConversation) == 0 and await compter(ActionConversation) == 0


async def test_proposition_cree_une_carte(client, faux_llm):
    cid, actions = await _proposer(client, faux_llm, "creer_projet", {"nom": "Beta"})
    assert [(a["nom"], a["parametres"], a["etat"]) for a in actions] == [
        ("creer_projet", {"nom": "Beta"}, "proposee")
    ]
    assert await _projets(client) == []
    d = await _detail(client, cid)
    assert d["etat"] == "pret"
    assert d["messages"][1]["contenu"] == (
        f"action n°{actions[0]['id']} proposée, en attente de la confirmation de Nicolas. "
        "Termine ta réponse sans appeler d'outil."
    )
    assert faux_llm.appels[-1]["outils"] is None


async def test_proposition_invalide_sans_carte(client, faux_llm):
    pid = (await client.post("/api/projets", json={"nom": "P"})).json()["id"]
    faux_llm.reponses = [
        _appel("lancer_pipeline", json.dumps({"projet_id": pid, "type": "dev"})),
        _texte("Compris."),
    ]
    cid = await _creer(client)
    await _envoyer(client, cid, "lance le dev")
    await _attendre(client, cid)
    d = await _detail(client, cid)
    assert d["actions"] == []
    outil = next(m for m in d["messages"] if m["role"] == "tool")
    assert outil["contenu"].startswith("erreur : ") and "Prête" in outil["contenu"]


async def test_deuxieme_proposition_du_tour_ignoree(client, sessions):
    cid = await _creer(client)
    outils = OutilsPortail(sessions, ["creer_projet"], CATALOGUE_TEST, cid)
    texte, mal = await outils.executer("creer_projet", '{"nom": "A"}')
    assert texte.startswith("action n°") and not mal and outils.arret
    texte, _ = await outils.executer("creer_projet", '{"nom": "B"}')
    assert texte == "ignoré : une action attend la confirmation de Nicolas"
    async with sessions() as s:
        assert len((await s.scalars(select(ActionConversation))).all()) == 1


async def test_confirmer_execute_et_relance(client, faux_llm):
    cid, [a] = await _proposer(client, faux_llm, "creer_projet", {"nom": "Beta"})
    faux_llm.reponses = [_texte("C'est fait.")]
    assert (await _confirmer(client, a["id"])).status_code == 202
    await _attendre(client, cid)
    [projet] = await _projets(client)
    d = await _detail(client, cid)
    [a] = d["actions"]
    assert projet["nom"] == "Beta"
    assert (a["etat"], a["resultat"], a["lien"]) == (
        "confirmee",
        f"projet n°{projet['id']} « Beta » créé",
        f"/projets/{projet['id']}",
    )
    systeme = f"Action n°{a['id']} (creer_projet) confirmée par Nicolas : projet n°{projet['id']} « Beta » créé"
    assert [(m["role"], m["contenu"]) for m in d["messages"][-2:]] == [
        ("system", systeme),
        ("assistant", "C'est fait."),
    ]
    assert d["etat"] == "pret"
    assert {"role": "system", "content": systeme} in faux_llm.appels[-1]["messages"]


async def test_refuser_relance(client, faux_llm):
    cid, [a] = await _proposer(client, faux_llm, "creer_projet", {"nom": "Beta"})
    faux_llm.reponses = [_texte("D'accord.")]
    assert (await client.post(f"/api/actions/{a['id']}/refuser")).status_code == 202
    await _attendre(client, cid)
    d = await _detail(client, cid)
    assert d["actions"][0]["etat"] == "refusee" and await _projets(client) == []
    assert [(m["role"], m["contenu"]) for m in d["messages"][-2:]] == [
        ("system", f"Nicolas a refusé l'action n°{a['id']} (creer_projet)"),
        ("assistant", "D'accord."),
    ]
    assert (await _confirmer(client, a["id"])).json()["detail"] == "action déjà traitée"


async def test_action_inconnue_404(client):
    assert (await _confirmer(client, 999)).status_code == 404
    assert (await client.post("/api/actions/999/refuser")).status_code == 404


async def test_confirmer_deux_fois_en_parallele(client, faux_llm):
    cid, [a] = await _proposer(client, faux_llm, "creer_projet", {"nom": "Beta"})
    faux_llm.reponses = [_texte("Fait.")]
    r1, r2 = await asyncio.gather(_confirmer(client, a["id"]), _confirmer(client, a["id"]))
    await _attendre(client, cid)
    assert sorted([r1.status_code, r2.status_code]) == [202, 409]
    assert len(await _projets(client)) == 1


async def test_confirmer_pendant_reponse_409(client, faux_llm):
    cid = await _creer(client)
    pause = asyncio.Event()
    faux_llm.reponses = [_appel("creer_projet", '{"nom": "Beta"}'), pause, _texte("Voilà.")]
    await _envoyer(client, cid, "crée Beta")
    await _poll(lambda: len(faux_llm.appels) == 2)
    [a] = (await _detail(client, cid))["actions"]
    r = await _confirmer(client, a["id"])
    assert r.status_code == 409 and r.json()["detail"] == "attends la fin de la réponse"
    pause.set()
    await _attendre(client, cid)
    assert (await _detail(client, cid))["actions"][0]["etat"] == "proposee"
    assert await _projets(client) == []


async def test_confirmer_refus_relance_le_modele(client, faux_llm, sessions):
    pid = (await client.post("/api/projets", json={"nom": "P"})).json()["id"]
    tid = (await client.post(f"/api/projets/{pid}/taches", json={"titre": "T"})).json()["id"]
    cid, [a] = await _proposer(
        client, faux_llm, "deplacer_tache", {"tache_id": tid, "colonne": "prete"}
    )
    async with sessions() as s:
        pl = Pipeline(projet_id=pid, type="spec")
        s.add(pl)
        await s.flush()
        (await s.get(Tache, tid)).verrou = pl.id
        await s.commit()
    faux_llm.reponses = [_texte("La tâche est verrouillée.")]
    assert (await _confirmer(client, a["id"])).status_code == 202
    await _attendre(client, cid)
    d = await _detail(client, cid)
    motif = f"tâche verrouillée par le pipeline {pl.id}"
    assert (d["actions"][0]["etat"], d["actions"][0]["resultat"]) == ("echouee", motif)
    systeme = f"Action n°{a['id']} (deplacer_tache) refusée par le portail : {motif}"
    assert {"role": "system", "content": systeme} in faux_llm.appels[-1]["messages"]
    assert d["etat"] == "pret"
    async with sessions() as s:
        assert (await s.get(Tache, tid)).colonne == "a_faire"


async def test_confirmer_erreur_de_base_echoue_proprement(client, faux_llm, monkeypatch):
    cid, [a] = await _proposer(client, faux_llm, "creer_projet", {"nom": "Beta"})

    async def _casse(s, catalogue, action):
        await s.execute(text("SELECT 1/0"))

    monkeypatch.setattr(conversations, "executer_action", _casse)
    faux_llm.reponses = [_texte("Raté.")]
    assert (await _confirmer(client, a["id"])).status_code == 202
    await _attendre(client, cid)
    d = await _detail(client, cid)
    assert d["actions"][0]["etat"] == "echouee" and d["etat"] == "pret"
    assert [m["role"] for m in d["messages"][-2:]] == ["system", "assistant"]


async def test_nouveau_message_perime_l_action(client, faux_llm):
    cid, [a] = await _proposer(client, faux_llm, "creer_projet", {"nom": "Beta"})
    faux_llm.reponses = [_texte("Autre chose.")]
    await _envoyer(client, cid, "finalement non")
    await _attendre(client, cid)
    d = await _detail(client, cid)
    assert d["actions"][0]["etat"] == "perimee"
    note = f"Action(s) n°{a['id']} périmée(s) : Nicolas a écrit un nouveau message sans confirmer."
    assert [(m["role"], m["contenu"]) for m in d["messages"] if m["role"] == "system"] == [
        ("system", note)
    ]
    assert {"role": "system", "content": note} in faux_llm.appels[-1]["messages"]
    r = await _confirmer(client, a["id"])
    assert r.status_code == 409 and r.json()["detail"] == "action périmée"
    assert await _projets(client) == []


async def test_action_proposee_survit_au_redemarrage(client, faux_llm, reglages):
    cid, [a] = await _proposer(client, faux_llm, "creer_projet", {"nom": "Beta"})
    llm = FauxLLM()
    llm.reponses = [_texte("Fait.")]
    app = create_app(reglages=reglages, llm=llm, catalogue=CATALOGUE_TEST)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        assert (await _confirmer(c, a["id"])).status_code == 202
        await _attendre(c, cid)
        assert [p["nom"] for p in await _projets(c)] == ["Beta"]
        assert (await _detail(c, cid))["actions"][0]["etat"] == "confirmee"


async def test_lancer_planification_lance_l_etape_auto(client, faux_llm, sessions, monkeypatch):
    chat = client._transport.app.state.chat
    lancees = []
    origine = chat.lancer
    monkeypatch.setattr(chat, "lancer", lambda i: (lancees.append(i), origine(i)))
    pid = (await client.post("/api/projets", json={"nom": "P"})).json()["id"]
    cid, [spec] = await _proposer(
        client, faux_llm, "deposer_spec", {"projet_id": pid, "contenu": "# Spec"}
    )
    faux_llm.reponses = [_texte("Spec déposée.")]
    await _confirmer(client, spec["id"])
    await _attendre(client, cid)
    assert lancees == []
    _, actions = await _proposer(
        client, faux_llm, "lancer_pipeline", {"projet_id": pid, "type": "planification"}, cid
    )
    faux_llm.reponses = [_texte("ok")] * 5
    assert (await _confirmer(client, actions[-1]["id"])).status_code == 202
    async with sessions() as s:
        plan = await s.scalar(select(Etape.id).where(Etape.agent == "plan"))
    assert lancees == [plan]
    await _attendre(client, cid)
    if t := chat.taches.get(plan):
        await asyncio.gather(t, return_exceptions=True)


async def test_confirmer_annuler_tache(client, faux_llm, sessions):
    _, tid, _ = await _tache_verrouillee(client, sessions)
    cid, [a] = await _proposer(client, faux_llm, "annuler_tache", {"tache_id": tid})
    faux_llm.reponses = [_texte("Annulée.")]
    assert (await _confirmer(client, a["id"])).status_code == 202
    await _attendre(client, cid)
    async with sessions() as s:
        t = await s.get(Tache, tid)
        assert (t.colonne, t.verrou) == ("a_faire", None)
    d = await _detail(client, cid)
    assert d["actions"][0]["etat"] == "confirmee" and d["etat"] == "pret"
    assert d["messages"][-2]["contenu"].startswith(f"Action n°{a['id']} (annuler_tache) confirmée")

    _, actions = await _proposer(client, faux_llm, "annuler_tache", {"tache_id": tid}, cid)
    faux_llm.reponses = [_texte("Rien à faire.")]
    assert (await _confirmer(client, actions[-1]["id"])).status_code == 202
    await _attendre(client, cid)
    b = (await _detail(client, cid))["actions"][-1]
    assert (b["etat"], b["resultat"]) == ("echouee", "rien à annuler")


async def test_reessayer_perime_l_action(client, faux_llm):
    cid = await _creer(client)
    faux_llm.reponses = [_appel("creer_projet", '{"nom": "Beta"}'), _texte("  ")]
    await _envoyer(client, cid, "crée Beta")
    await _attendre(client, cid)
    d = await _detail(client, cid)
    assert d["etat"] == "erreur" and d["actions"][0]["etat"] == "proposee"
    faux_llm.reponses = [_texte("Repris.")]
    assert (await client.post(f"/api/conversations/{cid}/reessayer")).status_code == 202
    await _attendre(client, cid)
    [a] = (await _detail(client, cid))["actions"]
    assert a["etat"] == "perimee"
    r = await _confirmer(client, a["id"])
    assert r.status_code == 409 and r.json()["detail"] == "action périmée"


async def test_conversation_pm(client, faux_llm):
    r = await client.post("/api/conversations", json={"agent": "pm"})
    assert r.status_code == 201 and r.json()["agent"] == "pm"
    cid = r.json()["id"]
    faux_llm.reponses = [_appel("en_attente_de_nicolas"), _texte("Rien n'attend.")]
    await _envoyer(client, cid, "Où en est-on ?")
    await _attendre(client, cid)
    d = await _detail(client, cid)
    assert d["agent"] == "pm"
    assert [m["role"] for m in d["messages"]] == ["user", "tool", "assistant"]
    assert d["messages"][1]["outil"].startswith("en_attente_de_nicolas")
    assert faux_llm.appels[0]["messages"][0]["content"] == "Tu es pm."
    assert [(c["id"], c["agent"]) for c in (await client.get("/api/conversations")).json()] == [
        (cid, "pm")
    ]


async def test_pm_ne_peut_rien_proposer(client, faux_llm, sessions):
    pid = (await client.post("/api/projets", json={"nom": "P"})).json()["id"]
    cid = (await client.post("/api/conversations", json={"agent": "pm"})).json()["id"]
    faux_llm.reponses = [
        _appel("creer_tache", json.dumps({"projet_id": pid, "titre": "T"})),
        _texte("Je ne peux pas."),
    ]
    await _envoyer(client, cid, "crée une tâche")
    await _attendre(client, cid)
    d = await _detail(client, cid)
    assert d["actions"] == []
    assert "non autorisé" in next(m for m in d["messages"] if m["role"] == "tool")["contenu"]
    assert "creer_tache" not in {o["function"]["name"] for o in faux_llm.appels[0]["outils"]}
    async with sessions() as s:
        assert (await s.scalars(select(ActionConversation))).all() == []


async def test_agent_inconnu_422(client):
    r = await client.post("/api/conversations", json={"agent": "inconnu"})
    assert r.status_code == 422


async def test_conversation_par_defaut_orchestrateur(client):
    d = (await client.post("/api/conversations")).json()
    assert d["agent"] == "orchestrateur"
    assert (await client.get("/api/conversations")).json()[0]["agent"] == "orchestrateur"
