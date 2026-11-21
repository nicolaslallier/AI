"""Relais sans état vers l'agent A2A `agent-musique` de LiteLLM (A2A 1.0, `SendMessage`).

L'agent n'a pas de mémoire : chaque message est traité seul.
"""

import uuid

import httpx

ILLISIBLE = "Réponse de l'agent musique illisible."


class ErreurMusique(Exception):
    pass


def _textes(message: dict | None) -> list[str]:
    parts = (message or {}).get("parts") or []
    return [p["text"] for p in parts if isinstance(p, dict) and p.get("text")]


def texte_de(resultat: dict) -> str:
    """Parts texte d'un résultat A2A : {message}, {task}, ou un message/une tâche direct (0.3)."""
    if "message" in resultat:
        return "\n\n".join(_textes(resultat["message"]))
    tache = resultat.get("task", resultat)
    morceaux = [t for a in tache.get("artifacts") or [] for t in _textes(a)]
    if not morceaux:
        morceaux = _textes((tache.get("status") or {}).get("message")) or _textes(tache)
    return "\n\n".join(morceaux)


async def demander(
    url: str,
    cle: str,
    texte: str,
    transport: httpx.AsyncBaseTransport | None = None,
    delai_s: float = 120,  # nginx lit /api/musique 150 s : garder au-dessous
) -> str:
    corps = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"text": texte}],
            }
        },
    }
    entetes = {"A2A-Version": "1.0"}
    if cle:
        entetes["Authorization"] = f"Bearer {cle}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(delai_s, connect=10), transport=transport
        ) as client:
            r = await client.post(
                f"{url.rstrip('/')}/v1/a2a/agent-musique/message/send", json=corps, headers=entetes
            )
    except httpx.TimeoutException as e:
        raise ErreurMusique(
            "L'agent musique n'a pas répondu à temps ; l'action a pu être effectuée quand même, "
            "vérifie avant de renvoyer."
        ) from e
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
        texte = texte_de(reponse["result"])
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ErreurMusique(ILLISIBLE) from e
    if not texte.strip():
        raise ErreurMusique(ILLISIBLE)
    return texte
