import asyncio
import json

from asgi_lifespan import LifespanManager
from conftest import CATALOGUE_TEST, FauxLLM, _agent
from httpx import ASGITransport, AsyncClient

from portail.agents import Catalogue
from portail.api import create_app
from portail.db import Conversation
from portail.llm import ErreurLLM


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
        cid = await _creer(c)
        r = await _envoyer(c, cid, "Salut")
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
