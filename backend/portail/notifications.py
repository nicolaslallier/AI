"""Notifications ntfy au mieux : une erreur est journalisée, jamais levée."""

import logging

import httpx

logger = logging.getLogger(__name__)


def lien_absolu(base: str, chemin: str) -> str | None:
    return base.rstrip("/") + chemin if base else None


def raison_courte(raison: str) -> str:
    """Première ligne non vide, 200 caractères au plus (jamais la sortie d'une commande)."""
    ligne = next((ligne.strip() for ligne in raison.splitlines() if ligne.strip()), "")
    return ligne[:200]


class Notifieur:
    def __init__(
        self, url: str, sujet: str, jeton: str, transport: httpx.AsyncBaseTransport | None = None
    ):
        self._url, self._sujet, self._jeton, self._transport = url, sujet, jeton, transport

    async def envoyer(self, titre: str, message: str, lien: str | None = None) -> None:
        if not self._jeton:
            return
        corps = {"topic": self._sujet, "title": titre, "message": message}
        if lien:
            corps["click"] = lien
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=5) as c:
                r = await c.post(
                    self._url, json=corps, headers={"Authorization": f"Bearer {self._jeton}"}
                )
            if r.status_code >= 400:
                logger.warning("ntfy : réponse %s", r.status_code)
        except Exception as e:  # noqa: BLE001 — le jeton n'est jamais journalisé
            logger.warning("ntfy : envoi impossible (%s)", type(e).__name__)
