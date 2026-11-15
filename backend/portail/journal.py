"""Journalisation d'erreurs sans contenu : le message d'une exception peut porter une sortie de
commande, un fichier, une réponse du LLM. On n'en garde que la classe et les cadres de pile."""

import logging
import sys
import traceback


def erreur(logger: logging.Logger, message: str, *args: object) -> None:
    """À appeler dans un `except` : `message % args`, classe de l'exception, cadres, jamais `str(e)`."""
    exc = sys.exc_info()[1]
    cadres = "".join(traceback.format_tb(exc.__traceback__)) if exc else ""
    logger.error(
        "%s : %s\n%s", message % args if args else message, type(exc).__name__, cadres.rstrip()
    )
