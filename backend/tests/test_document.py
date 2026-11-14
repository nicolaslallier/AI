import asyncio

from tests.test_chat import _attendre, _envoyer, _etape, _etat


async def _rediger(client, faux_llm, eid, texte="# Spec"):
    faux_llm.morceaux = [texte]
    assert (await client.post(f"/api/etapes/{eid}/rediger")).status_code == 202
    await _attendre(client, eid)


async def _put(client, eid, contenu):
    return await client.put(f"/api/etapes/{eid}/document", json={"contenu": contenu})


async def test_corriger_puis_valider(client, faux_llm):
    _, eid = await _etape(client)
    await _rediger(client, faux_llm, eid)
    r = await _put(client, eid, "# Spec corrigée\n")
    assert r.status_code == 200 and r.json()["contenu"] == "# Spec corrigée\n"
    r = await client.post(f"/api/etapes/{eid}/valider")
    assert r.status_code == 200
    d = r.json()
    assert d["etat"] == "terminee" and d["etapes"][0]["etat"] == "terminee"
    assert d["etapes"][0]["document"]["etat"] == "validee"
    assert d["etapes"][0]["document"]["contenu"] == "# Spec corrigée\n"
    projet = (await client.get(f"/api/projets/{d['projet']['id']}")).json()
    assert projet["spec_courante"]["contenu"] == "# Spec corrigée\n"


async def test_correction_prise_en_compte_par_l_agent(client, faux_llm):
    _, eid = await _etape(client)
    await _rediger(client, faux_llm, eid)
    await _put(client, eid, "# Spec corrigée")
    faux_llm.morceaux = ["ok"]
    await _envoyer(client, eid, "suite")
    await _attendre(client, eid)
    assert "Spec corrigée" in faux_llm.appels[-1]["messages"][1]["content"]


async def test_put_valide_le_contenu(client, faux_llm):
    _, eid = await _etape(client)
    await _rediger(client, faux_llm, eid)
    assert (await _put(client, eid, "  \n")).status_code == 422
    assert (await _put(client, 999999, "x")).status_code == 404


async def test_put_sans_brouillon_409(client):
    _, eid = await _etape(client)
    r = await _put(client, eid, "x")
    assert r.status_code == 409 and r.json()["detail"] == "aucun brouillon à corriger"


async def test_valider_sans_brouillon_409(client):
    _, eid = await _etape(client)
    r = await client.post(f"/api/etapes/{eid}/valider")
    assert r.status_code == 409
    assert r.json()["detail"] == "rien à valider : clique d'abord « Rédiger la spec »"
    assert (await client.post("/api/etapes/999999/valider")).status_code == 404


async def test_valider_pendant_une_reponse_409(client, faux_llm):
    _, eid = await _etape(client)
    await _rediger(client, faux_llm, eid)
    pause = asyncio.Event()
    faux_llm.morceaux = [pause, "x"]
    await _envoyer(client, eid, "encore")
    r = await client.post(f"/api/etapes/{eid}/valider")
    assert r.status_code == 409 and r.json()["detail"] == "une réponse est en cours"
    assert (await _put(client, eid, "x")).status_code == 409
    pause.set()
    await _attendre(client, eid)


async def test_spec_validee_figee(client, faux_llm):
    pid, eid = await _etape(client)
    await _rediger(client, faux_llm, eid)
    await client.post(f"/api/etapes/{eid}/valider")
    r = await _put(client, eid, "autre")
    assert r.status_code == 409 and r.json()["detail"] == "spec déjà validée"
    assert (await _etat(client, pid))["document"]["contenu"] == "# Spec"
