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
_MAX_APPELS_PAR_TOUR = 8


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
    if not agent.outils:
        raise ErreurOutils(f"l'agent « {agent.nom} » n'a aucun outil")
    schemas = [SCHEMAS_OUTILS[n] for n in agent.outils]
    mal_formes = 0
    for _ in range(agent.tours_max):
        elaguer_resultats_outils(messages, agent.contexte_max)
        reponse = await llm.completer(agent.modele, messages, agent.temperature, outils=schemas)
        appels = reponse.get("tool_calls")
        if not isinstance(appels, list) or not appels:
            return ResultatBoucle(texte=_texte(reponse), limite_atteinte=False)
        messages.append(reponse)
        for i, appel in enumerate(appels):
            appel = appel if isinstance(appel, dict) else {}
            fonction = appel.get("function")
            fonction = fonction if isinstance(fonction, dict) else {}
            id_ = appel.get("id")
            id_ = id_ if isinstance(id_, str) and id_ else f"appel_{len(messages)}_{i}"
            nom, arguments = fonction.get("name"), fonction.get("arguments") or ""
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments)
            if i >= _MAX_APPELS_PAR_TOUR:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": id_,
                        "content": "erreur : trop d'appels dans un même tour, ignoré",
                    }
                )
                continue
            if isinstance(nom, str) and nom not in agent.outils:
                resultat, mal_forme, libelle = f"erreur : outil non autorisé : {nom}", True, nom
            elif isinstance(nom, str) and isinstance(arguments, str):
                resultat, mal_forme = await outils.executer(nom, arguments)
                libelle = _libelle(nom, arguments)
            else:
                resultat, mal_forme = "erreur : appel d'outil mal formé", True
                libelle = nom if isinstance(nom, str) else "outil inconnu"
            mal_formes = mal_formes + 1 if mal_forme else 0
            messages.append({"role": "tool", "tool_call_id": id_, "content": resultat})
            await sur_appel(libelle, resultat)
            if mal_formes >= _MAL_FORMES_MAX:
                raise ErreurOutils(f"le modèle {agent.modele} ne gère pas correctement les outils")
    messages.append({"role": "user", "content": _LIMITE})
    elaguer_resultats_outils(messages, agent.contexte_max)
    reponse = await llm.completer(agent.modele, messages, agent.temperature)
    return ResultatBoucle(texte=_texte(reponse), limite_atteinte=True)
