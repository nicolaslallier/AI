from typing import Literal

from pydantic import BaseModel

from portail.agents import Agent
from portail.db import Document, Message


def construire(
    agent: Agent,
    messages: list[Message],
    document: Document | None,
    consigne: str | None = None,
    annexes: list[str] | None = None,
) -> list[dict]:
    sortie = [{"role": "system", "content": agent.prompt_systeme}]
    sortie += [{"role": "system", "content": a} for a in annexes or []]
    gardes = [m for m in messages if m.role in ("user", "assistant")]
    if document:
        sortie.append(
            {
                "role": "system",
                "content": "Brouillon courant :\n\n" + document.contenu,
            }
        )
        if document.dernier_message_id is not None:
            gardes = [m for m in gardes if m.id > document.dernier_message_id]
    sortie += [{"role": m.role, "content": m.contenu} for m in gardes]
    if consigne:
        sortie.append({"role": "user", "content": consigne})
    return sortie


def estimer_jetons(messages: list[dict]) -> int:
    # content peut être None (message assistant qui n'a fait qu'appeler des outils)
    return sum(len(m.get("content") or "") // 4 + 4 for m in messages)


RESULTAT_RETIRE = "[résultat retiré : relire si besoin]"


def elaguer_resultats_outils(messages: list[dict], contexte_max: int) -> int:
    """Remplace les résultats d'outils, du plus ancien au plus récent, de 0,90 à 0,75."""
    if estimer_jetons(messages) < 0.90 * contexte_max:
        return 0
    n = 0
    for m in messages:
        if estimer_jetons(messages) < 0.75 * contexte_max:
            break
        if m["role"] == "tool" and m["content"] != RESULTAT_RETIRE:
            m["content"] = RESULTAT_RETIRE
            n += 1
    return n


class Jauge(BaseModel):
    utilises: int
    max: int
    ratio: float
    niveau: Literal["ok", "alerte", "plein"]


def _niveau(ratio: float) -> Literal["ok", "alerte", "plein"]:
    return "plein" if ratio >= 0.90 else "alerte" if ratio >= 0.75 else "ok"


def jauge(agent: Agent, messages_llm: list[dict]) -> Jauge:
    utilises = estimer_jetons(messages_llm)
    ratio = utilises / agent.contexte_max
    return Jauge(utilises=utilises, max=agent.contexte_max, ratio=ratio, niveau=_niveau(ratio))
