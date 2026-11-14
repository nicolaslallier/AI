import json

import httpx
import pytest

from portail.llm import ClientLLM, ErreurLLM, FiltreReflexion, retirer_reflexion


def _sse(*deltas: dict) -> str:
    lignes = [f"data: {json.dumps({'choices': [{'delta': d}]})}\n" for d in deltas]
    return "\n".join(lignes) + "\ndata: [DONE]\n\n"


async def test_flux_concatene_les_deltas():
    vues = []

    def handler(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return httpx.Response(
            200, text=_sse({"content": "Bon"}, {"content": "jour"}, {"role": "assistant"})
        )

    client = ClientLLM("http://litellm:4000/", "k", transport=httpx.MockTransport(handler))
    morceaux = [m async for m in client.flux("m", [{"role": "user", "content": "x"}], None)]
    assert "".join(morceaux) == "Bonjour"
    requete = vues[0]
    assert requete.url.path == "/v1/chat/completions"
    assert requete.headers["Authorization"] == "Bearer k"
    corps = json.loads(requete.content)
    assert corps["stream"] is True
    assert "temperature" not in corps


async def test_flux_envoie_la_temperature():
    vues = []

    def handler(requete: httpx.Request) -> httpx.Response:
        vues.append(json.loads(requete.content))
        return httpx.Response(200, text=_sse({"content": "a"}))

    client = ClientLLM("http://l", "k", transport=httpx.MockTransport(handler))
    _ = [m async for m in client.flux("m", [], 0.2)]
    assert vues[0]["temperature"] == 0.2


async def test_flux_erreur_http():
    client = ClientLLM(
        "http://l", "k", transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))
    )
    with pytest.raises(ErreurLLM, match="500"):
        _ = [m async for m in client.flux("m", [], None)]


async def test_flux_erreur_reseau():
    def handler(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("non")

    client = ClientLLM("http://l", "k", transport=httpx.MockTransport(handler))
    with pytest.raises(ErreurLLM):
        _ = [m async for m in client.flux("m", [], None)]


async def test_flux_json_invalide():
    client = ClientLLM(
        "http://l",
        "k",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="data: {pas du json\n\n")),
    )
    with pytest.raises(ErreurLLM):
        _ = [m async for m in client.flux("m", [], None)]


CAS = [
    ("<think>x</think>Salut", "Salut"),
    ("A<think>x</think>B", "AB"),
    ("pas de balise", "pas de balise"),
    ("<think>jamais fermé", ""),
    ("a < b", "a < b"),
]


@pytest.mark.parametrize(("entree", "attendu"), CAS)
def test_filtre_reflexion(entree, attendu):
    assert retirer_reflexion(entree) == attendu
    for i in range(len(entree) + 1):
        f = FiltreReflexion()
        sortie = f.envoyer(entree[:i]) + f.envoyer(entree[i:]) + f.finir()
        assert sortie == attendu, i


def test_filtre_retient_peu():
    f = FiltreReflexion()
    f.envoyer("x" * 100)
    assert len(f._tampon) <= len("</think>")
    f.envoyer("<think>" + "y" * 100)
    assert len(f._tampon) <= len("</think>")
