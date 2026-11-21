"""Relais sans état vers l'agent A2A `agent-musique` de LiteLLM (JSON-RPC `message/send`)."""

import uuid

import httpx


class ErreurMusique(Exception):
    pass


def _textes(parts: list | None) -> list[str]:
    return [p["text"] for p in parts or [] if p.get("kind") == "text" and p.get("text")]


def texte_de(resultat: dict) -> str:
    """Concatène les parts texte d'un résultat A2A : Message, ou Task (artefacts, sinon statut)."""
    if resultat.get("kind") == "message":
        return "\n\n".join(_textes(resultat.get("parts")))
    morceaux = [t for a in resultat.get("artifacts") or [] for t in _textes(a.get("parts"))]
    if not morceaux:
        morceaux = _textes(((resultat.get("status") or {}).get("message") or {}).get("parts"))
    return "\n\n".join(morceaux)


async def demander(
    url: str,
    cle: str,
    texte: str,
    context_id: str | None,
    transport: httpx.AsyncBaseTransport | None = None,
    delai_s: float = 120,
) -> dict:
    message: dict = {
        "role": "user",
        "parts": [{"kind": "text", "text": texte}],
        "messageId": str(uuid.uuid4()),
    }
    if context_id:
        message["contextId"] = context_id
    corps = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {"message": message},
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(delai_s, connect=10), transport=transport
        ) as client:
            r = await client.post(
                f"{url.rstrip('/')}/v1/a2a/agent-musique/message/send",
                json=corps,
                headers={"Authorization": f"Bearer {cle}"} if cle else {},
            )
    except httpx.TimeoutException as e:
        raise ErreurMusique("L'agent musique n'a pas répondu à temps.") from e
    except httpx.HTTPError as e:
        raise ErreurMusique("L'agent musique est injoignable.") from e
    if r.status_code in (401, 403):
        raise ErreurMusique("LiteLLM refuse l'accès du Portail à l'agent musique.")
    if not r.is_success:
        raise ErreurMusique(f"L'agent musique a répondu {r.status_code}.")
    try:
        reponse = r.json()
        if reponse.get("error"):  # message fixe : jamais le texte amont
            raise ErreurMusique("L'agent musique a renvoyé une erreur.")
        resultat = reponse["result"]
        return {"texte": texte_de(resultat), "context_id": resultat.get("contextId") or context_id}
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ErreurMusique("Réponse de l'agent musique illisible.") from e
