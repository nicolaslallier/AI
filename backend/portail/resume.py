"""Résumé du matin : le PM raconte la nuit à Nicolas, par ntfy, au plus une fois par jour."""

import asyncio
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from portail.conversations import ServiceConversation
from portail.db import MessageConversation, Resume
from portail.notifications import lien_absolu
from portail.outils_portail import activite_depuis

logger = logging.getLogger(__name__)

TORONTO = ZoneInfo("America/Toronto")
CONSIGNE = (
    "Ce qui s'est passé depuis le dernier résumé, ce qui est bloqué, ce qui attend Nicolas. "
    "Court, en puces."
)


def _a(jour, heure: str) -> datetime:
    return datetime.combine(jour, time.fromisoformat(heure), tzinfo=TORONTO)


def prochaine_echeance(maintenant: datetime, heure: str) -> datetime:
    local = maintenant.astimezone(TORONTO)
    aujourdhui = _a(local.date(), heure)
    return aujourdhui if local < aujourdhui else _a(local.date() + timedelta(days=1), heure)


async def resumer_si_du(
    sessions,
    conversations: ServiceConversation,
    notifieur,
    maintenant: datetime,
    heure: str,
    url_publique: str,
) -> bool:
    local = maintenant.astimezone(TORONTO)
    jour = local.date()
    if local < _a(jour, heure):
        return False
    async with sessions() as s:
        if await s.scalar(select(Resume.id).where(Resume.jour == jour)):
            return False
        dernier = await s.scalar(select(Resume.cree_le).order_by(Resume.cree_le.desc()).limit(1))
        actif = bool(await activite_depuis(s, dernier or maintenant - timedelta(hours=24), 1))
        s.add(Resume(jour=jour, cree_le=maintenant))
        await s.commit()
    if not actif:
        return False
    c = await conversations.creer("pm")
    await conversations.renommer(c.id, f"Résumé du {jour.isoformat()}")
    async with sessions() as s:
        resume = await s.scalar(select(Resume).where(Resume.jour == jour))
        resume.conversation_id = c.id
        await s.commit()
    await conversations.envoyer(c.id, CONSIGNE)
    await conversations.taches[c.id]
    async with sessions() as s:
        texte = await s.scalar(
            select(MessageConversation.contenu)
            .where(MessageConversation.conversation_id == c.id)
            .where(MessageConversation.role == "assistant")
            .order_by(MessageConversation.id.desc())
            .limit(1)
        )
    if not texte:  # la conversation finit en erreur : rien à envoyer
        return False
    await notifieur.envoyer(
        "Résumé du matin", texte[:4000], lien_absolu(url_publique, f"/chat/{c.id}")
    )
    return True


async def tourner(
    sessions, conversations, notifieur, heure: str, url_publique: str, horloge
) -> None:
    """Une fois au démarrage, puis chaque jour à `heure`. Une erreur est journalisée."""
    while True:
        try:
            await resumer_si_du(sessions, conversations, notifieur, horloge(), heure, url_publique)
        except Exception:
            logger.exception("résumé du matin impossible")
        await asyncio.sleep(
            max((prochaine_echeance(horloge(), heure) - horloge()).total_seconds(), 1)
        )
