"""Boucle d'outils en lecture seule : le modèle explore le dépôt, tour après tour."""

import json
from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from portail.agents import Agent
from portail.contexte import elaguer_resultats_outils
from portail.llm import retirer_reflexion
from portail.outils import SCHEMAS_OUTILS, OutilsDepot

_LIMITE = "Limite d'outils atteinte : conclus maintenant avec ce que tu as, sans appeler d'outil."
_MAL_FORMES_MAX = 3


class ErreurOutils(Exception):
    pass


class ResultatBoucle(BaseModel):
    texte: str
    limite_atteinte: bool


def _libelle(nom: str, arguments: str) -> str:
    try:
        args = json.loads(arguments or "{}")
        if isinstance(args, dict):
            return f"{nom}({', '.join(str(v) for v in args.values())})"
    except (ValueError, RecursionError):
        pass
    return nom


def _texte(message: dict) -> str:
    return retirer_reflexion(message.get("content") or "")


async def boucle_outils(
    llm,
    agent: Agent,
    messages: list[dict],
    outils: OutilsDepot,
    sur_appel: Callable[[str, str], Awaitable[None]],
) -> ResultatBoucle:
    schemas = [SCHEMAS_OUTILS[n] for n in agent.outils]
    mal_formes = 0
    for _ in range(agent.tours_max):
        elaguer_resultats_outils(messages, agent.contexte_max)
        reponse = await llm.completer(agent.modele, messages, agent.temperature, outils=schemas)
        appels = reponse.get("tool_calls")
        if not appels:
            return ResultatBoucle(texte=_texte(reponse), limite_atteinte=False)
        messages.append(reponse)
        for appel in appels:
            nom = appel["function"]["name"]
            arguments = appel["function"].get("arguments") or ""
            resultat, mal_forme = await outils.executer(nom, arguments)
            mal_formes = mal_formes + 1 if mal_forme else 0
            messages.append({"role": "tool", "tool_call_id": appel["id"], "content": resultat})
            await sur_appel(_libelle(nom, arguments), resultat)
            if mal_formes >= _MAL_FORMES_MAX:
                raise ErreurOutils(f"le modèle {agent.modele} ne gère pas correctement les outils")
    messages.append({"role": "user", "content": _LIMITE})
    elaguer_resultats_outils(messages, agent.contexte_max)
    reponse = await llm.completer(agent.modele, messages, agent.temperature)
    return ResultatBoucle(texte=_texte(reponse), limite_atteinte=True)
