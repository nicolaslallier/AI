import json

import httpx
import pytest

from portail.musique import ErreurMusique, demander


def _rpc(resultat: dict | None) -> httpx.MockTransport:
    vues = []

    def handler(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        corps = {"jsonrpc": "2.0", "id": "1"}
        if resultat is not None:
            corps["result"] = resultat
        return httpx.Response(200, json=corps)

    t = httpx.MockTransport(handler)
    t.vues = vues
    return t


async def test_message_1_0():
    t = _rpc(
        {
            "message": {
                "messageId": "r1",
                "role": "ROLE_AGENT",
                "parts": [{"text": "Kind of Blue"}, {"text": "Sources : x.md"}],
            }
        }
    )
    assert await demander("http://litellm:4000/", "k", "Miles ?", transport=t) == (
        "Kind of Blue\n\nSources : x.md"
    )
    requete = t.vues[0]
    assert requete.url.path == "/v1/a2a/agent-musique/message/send"
    assert requete.headers["Authorization"] == "Bearer k"
    assert requete.headers["A2A-Version"] == "1.0"
    corps = json.loads(requete.content)
    assert corps["method"] == "SendMessage"
    msg = corps["params"]["message"]
    assert msg["role"] == "ROLE_USER" and msg["parts"] == [{"text": "Miles ?"}]
    assert msg["messageId"] and "contextId" not in msg


async def test_task_1_0():
    t = _rpc({"task": {"status": {"message": {"parts": [{"text": "Abbey Road"}]}}}})
    assert await demander("http://l", "k", "x", transport=t) == "Abbey Road"


async def test_task_0_3():
    t = _rpc(
        {
            "kind": "task",
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"kind": "text", "text": "A"}, {"kind": "data"}]}],
        }
    )
    assert await demander("http://l", "k", "x", transport=t) == "A"


async def test_message_direct_0_3():
    t = _rpc({"kind": "message", "parts": [{"kind": "text", "text": "B"}]})
    assert await demander("http://l", "k", "x", transport=t) == "B"


@pytest.mark.parametrize("resultat", [None, {"message": {"parts": [{"text": "  "}]}}])
async def test_result_absent_ou_texte_vide(resultat):
    with pytest.raises(ErreurMusique, match="illisible"):
        await demander("http://l", "k", "x", transport=_rpc(resultat))


@pytest.mark.parametrize("statut", [403, 500])
async def test_erreur_http(statut):
    t = httpx.MockTransport(lambda r: httpx.Response(statut, text="non"))
    with pytest.raises(ErreurMusique):
        await demander("http://l", "k", "x", transport=t)


async def test_erreur_jsonrpc():
    t = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "error": {"code": -1}})
    )
    with pytest.raises(ErreurMusique):
        await demander("http://l", "k", "x", transport=t)


async def test_delai_depasse():
    def handler(requete: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lent")

    with pytest.raises(ErreurMusique, match="vérifie avant de renvoyer"):
        await demander("http://l", "k", "x", transport=httpx.MockTransport(handler))
