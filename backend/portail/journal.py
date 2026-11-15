"""Journalisation d'erreurs sans contenu : le message d'une exception peut porter une sortie de
commande, un fichier, une réponse du LLM. On n'en garde que la classe et les cadres de pile."""

import json
import logging
import sys
import traceback
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

IDS = ("pipeline", "etape", "tache", "conversation", "agent", "mission")

# Identifiants de la tâche de fond en cours. Jamais muté en place : chaque écriture pose un dict
# neuf, donc une tâche asyncio enfant (copie du contexte) ne modifie pas celui du parent.
contexte: ContextVar[dict] = ContextVar("contexte_portail", default={})  # noqa: B039 (jamais muté)


def commencer(**valeurs: object) -> None:
    """Point d'entrée d'une tâche de fond : REMPLACE le contexte (pas d'identifiants périmés)."""
    contexte.set(dict(valeurs))


def lier(**valeurs: object) -> None:
    """Complète le contexte ; une valeur `None` retire la clé."""
    nouveau = {**contexte.get(), **valeurs}
    contexte.set({k: v for k, v in nouveau.items() if v is not None})


def nouvelle_mission(agent: str, contexte_max: int | None = None) -> str:
    mission = uuid.uuid4().hex[:12]
    lier(agent=agent, mission=mission, contexte_max=contexte_max)
    return mission


class FormatJSON(logging.Formatter):
    """Une ligne JSON par enregistrement. Une exception n'est rendue que par sa classe et ses
    cadres de pile : jamais `str(exception)`, qui peut porter du contenu."""

    def format(self, record: logging.LogRecord) -> str:
        ligne = {
            "quand": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "niveau": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        ids = contexte.get()
        ligne.update({k: ids[k] for k in IDS if k in ids})
        if record.exc_info and record.exc_info[1]:
            ligne["exception"] = type(record.exc_info[1]).__name__
            ligne["pile"] = "".join(traceback.format_tb(record.exc_info[2]))
        return json.dumps(ligne, ensure_ascii=False, default=str)


def erreur(logger: logging.Logger, message: str, *args: object) -> None:
    """À appeler dans un `except` : `message % args`, classe de l'exception, cadres, jamais `str(e)`."""
    exc = sys.exc_info()[1]
    cadres = "".join(traceback.format_tb(exc.__traceback__)) if exc else ""
    logger.error(
        "%s : %s\n%s", message % args if args else message, type(exc).__name__, cadres.rstrip()
    )
