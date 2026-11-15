"""Journal d'audit : qui a fait quoi sur quoi, quand. Jamais de contenu (message, document, secret)."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from portail.db import Audit


def inscrire(session: AsyncSession, auteur: str, action: str, objet: str, objet_id: int) -> None:
    """Ajoute à la session, sans valider : la ligne vaut ce que vaut la transaction de l'action."""
    session.add(Audit(auteur=auteur, action=action, objet=objet, objet_id=objet_id))


def auteur_de(request: Request) -> str:
    """Sans oauth2-proxy (`exiger_utilisateur` faux), l'en-tête vient du client : on ne le lit pas."""
    if not request.app.state.reglages.exiger_utilisateur:
        return "local"
    return (request.headers.get("X-Auth-Request-Email") or "local")[:320]
