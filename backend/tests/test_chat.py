import asyncio
import json

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
