import json

import httpx

from portail.notifications import Notifieur, lien_absolu, raison_courte


def _notifieur(jeton, gestionnaire):
    return Notifieur("http://ntfy", "portail", jeton, httpx.MockTransport(gestionnaire))


async def test_sans_jeton_rien():
    appels = []
    await _notifieur("", lambda r: appels.append(r) or httpx.Response(200)).envoyer("t", "m")
    assert appels == []


async def test_json_et_auth():
    vus = []
    await _notifieur("sec", lambda r: vus.append(r) or httpx.Response(200)).envoyer(
        "Tâche bloquée", "msg", "https://p/x"
    )
    (r,) = vus
    corps = json.loads(r.content)
    assert corps == {
        "topic": "portail",
        "title": "Tâche bloquée",
        "message": "msg",
        "click": "https://p/x",
    }
    assert r.headers["Authorization"] == "Bearer sec"
    vus.clear()
    await _notifieur("sec", lambda r: vus.append(r) or httpx.Response(200)).envoyer("t", "m")
    assert "click" not in json.loads(vus[0].content)


async def test_panne_ne_leve_pas():
    def panne(requete):
        raise httpx.ConnectError("non")

    await _notifieur("sec", panne).envoyer("t", "m")
    await _notifieur("sec", lambda r: httpx.Response(500)).envoyer("t", "m")


def test_lien_absolu():
    assert lien_absolu("https://p/", "/projets/1/kanban") == "https://p/projets/1/kanban"
    assert lien_absolu("", "/projets/1/kanban") is None


def test_raison_courte():
    assert (
        raison_courte("vérification échouée (tests) :\nsortie…") == "vérification échouée (tests) :"
    )
