"""Route de service : agent-doc demande une tâche de documentation seule, sans navigateur.

Authentifiée par `PORTAIL_JETON_SERVICE` (comparé en temps constant), hors de `/api/` et
de `/interne/` : aucune des trois portes n'ouvre les deux autres. Fermée sur le vhost public.
"""

import secrets

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from portail.audit import inscrire
from portail.config import Reglages
from portail.db import Projet, Tache
from portail.moteur import Refus
from portail.notifications import lien_absolu
from portail.schemas import DonneesTache
from portail.taches import creer_tache, deplacer_tache

MAX_OUVERTES = 5
OUVERTES = ("a_faire", "prete", "en_cours")


class DemandeDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depot: str = Field(pattern=r"^[A-Za-z0-9._-]{1,100}$")
    demande: str
    appelant: str = Field(pattern=r"^[a-z0-9-]{1,40}$")

    @field_validator("depot")
    @classmethod
    def _pas_de_point(cls, v: str) -> str:
        if v in (".", ".."):
            raise ValueError("nom de dépôt invalide")
        return v

    @field_validator("demande")
    @classmethod
    def _demande(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 4000:
            raise ValueError("la demande doit faire de 1 à 4000 caractères")
        return v


def _normaliser(url: str) -> str:
    url = url.lower().rstrip("/")
    return url.removesuffix(".git")


async def demander_doc(
    session: AsyncSession, reglages: Reglages, corps: DemandeDoc
) -> tuple[Tache, bool]:
    voulu = _normaliser(f"https://github.com/{reglages.github_proprietaire}/{corps.depot}")
    projets = [
        p
        for p in (await session.scalars(select(Projet).where(Projet.depot_url.is_not(None)))).all()
        if _normaliser(p.depot_url) == voulu
    ]
    if not projets:
        raise Refus(404, f"aucun projet pour le dépôt {corps.depot}")
    if len(projets) > 1:
        raise Refus(409, f"plusieurs projets pour le dépôt {corps.depot}")
    projet_id = projets[0].id
    # verrou du projet : deux appels identiques simultanés ne créent qu'une tâche
    await session.scalar(select(Projet.id).where(Projet.id == projet_id).with_for_update())
    ouvertes = (
        Tache.projet_id == projet_id,
        Tache.doc.is_(True),
        Tache.origine == "agent",
        Tache.colonne.in_(OUVERTES),
    )
    existante = await session.scalar(
        select(Tache).where(*ouvertes, Tache.description == corps.demande).limit(1)
    )
    if existante is not None:
        return existante, True
    if await session.scalar(select(func.count()).select_from(Tache).where(*ouvertes)) >= (
        MAX_OUVERTES
    ):
        raise Refus(429, "trop de demandes de documentation ouvertes")
    auteur = f"service:{corps.appelant}"
    titre = "Documentation : " + corps.demande.splitlines()[0][:180]
    tache = await creer_tache(
        session,
        projet_id,
        DonneesTache(titre=titre, description=corps.demande, doc=True),
        auteur=auteur,
        origine="agent",
        protegee=False,
    )
    await deplacer_tache(session, tache, "prete", None, auteur)
    return tache, False


def _verifier_jeton(request: Request) -> None:
    """Dépendance : jugée avant le corps, un appelant sans jeton n'apprend rien du schéma."""
    attendu = request.app.state.reglages.jeton_service
    if not attendu:
        raise Refus(503, "service désactivé")
    schema, _, valeur = request.headers.get("Authorization", "").partition(" ")
    if schema != "Bearer" or not secrets.compare_digest(valeur.encode(), attendu.encode()):
        raise Refus(401, "jeton de service invalide")


def routeur_service(reveiller) -> APIRouter:
    """`reveiller(state)` : réveille l'ordonnanceur (passé par api.py, qui le définit)."""
    routeur = APIRouter()

    @routeur.post("/service/taches-doc", status_code=201, dependencies=[Depends(_verifier_jeton)])
    async def taches_doc(corps: DemandeDoc, request: Request, response: Response):
        r = request.app.state.reglages
        async with request.app.state.sessions() as s:
            tache, existante = await demander_doc(s, r, corps)
            if not existante:
                inscrire(s, f"service:{corps.appelant}", "tache.creer", "tache", tache.id)
            await s.commit()
        if existante:
            response.status_code = 200
        else:
            reveiller(request.app.state)
        return {
            "tache_id": tache.id,
            "projet_id": tache.projet_id,
            "lien": lien_absolu(r.url_publique, f"/projets/{tache.projet_id}/kanban"),
            "existante": existante,
        }

    return routeur
