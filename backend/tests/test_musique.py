import json

import httpx
import pytest

from portail.musique import ErreurMusique, demander


def _rpc(resultat: dict) -> httpx.MockTransport:
    vues = []

    def handler(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": resultat})

    t = httpx.MockTransport(handler)
    t.vues = vues
    return t


async def test_reponse_task():
    t = _rpc(
        {
            "kind": "task",
            "contextId": "ctx-1",
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"kind": "text", "text": "Abbey Road"}, {"kind": "data"}]}],
        }
    )
    r = await demander("http://litellm:4000/", "k", "Beatles ?", "ctx-0", transport=t)
    assert r == {"texte": "Abbey Road", "context_id": "ctx-1"}
    requete = t.vues[0]
    assert requete.url.path == "/v1/a2a/agent-musique/message/send"
    assert requete.headers["Authorization"] == "Bearer k"
    corps = json.loads(requete.content)
    assert corps["method"] == "message/send"
    msg = corps["params"]["message"]
    assert msg["role"] == "user" and msg["contextId"] == "ctx-0"
    assert msg["parts"] == [{"kind": "text", "text": "Beatles ?"}] and msg["messageId"]


async def test_reponse_message():
    t = _rpc(
        {
            "kind": "message",
            "role": "agent",
            "contextId": "c",
            "parts": [{"kind": "text", "text": "A"}, {"kind": "text", "text": "B"}],
        }
    )
    r = await demander("http://l", "k", "x", None, transport=t)
    assert r == {"texte": "A\n\nB", "context_id": "c"}
    assert "contextId" not in json.loads(t.vues[0].content)["params"]["message"]


async def test_reponse_message_a2a_1_0():
    # Forme de a2a-sdk 1.1 : MessageToDict(SendMessageResponse(message=new_text_message(...)))
    t = _rpc(
        {
            "message": {
                "messageId": "m1",
                "contextId": "c1",
                "role": "ROLE_AGENT",
                "parts": [{"text": "A"}, {"text": "B"}],
            }
        }
    )
    r = await demander("http://l", "k", "x", None, transport=t)
    assert r == {"texte": "A\n\nB", "context_id": "c1"}


async def test_reponse_task_a2a_1_0():
    t = _rpc(
        {
            "task": {
                "id": "t1",
                "contextId": "c2",
                "status": {"state": "TASK_STATE_COMPLETED"},
                "artifacts": [{"artifactId": "a", "parts": [{"text": "Abbey Road"}]}],
            }
        }
    )
    r = await demander("http://l", "k", "x", "c0", transport=t)
    assert r == {"texte": "Abbey Road", "context_id": "c2"}


@pytest.mark.parametrize("statut", [403, 500])
async def test_erreur_http(statut):
    t = httpx.MockTransport(lambda r: httpx.Response(statut, text="non"))
    with pytest.raises(ErreurMusique):
        await demander("http://l", "k", "x", None, transport=t)


async def test_erreur_jsonrpc():
    t = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "error": {"code": -1}})
    )
    with pytest.raises(ErreurMusique):
        await demander("http://l", "k", "x", None, transport=t)


async def test_api_passe_le_delai_llm(monkeypatch):
    from portail import api
    from portail.config import Reglages

    vus = {}

    async def faux(*args, **kwargs):
        vus.update(kwargs)
        return {"texte": "ok"}

    monkeypatch.setattr(api, "demander", faux)
    r = Reglages(database_url="postgresql+psycopg://x@l/x", llm_delai_s=321)
    app = api.create_app(r)
    app.state.reglages, app.state.reseau_agents = r, None  # sans lifespan : aucune base
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        rep = await c.post("/api/musique", json={"texte": "Beatles ?"})
    assert rep.status_code == 200, rep.text
    assert vus["delai_s"] == 321
