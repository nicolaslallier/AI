"""Suivi minimal des PR : une PR fusionnée termine la tâche, une PR fermée la renvoie à faire."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portail.db import CommentairePris, ExecutionDev, Projet, Tache
from portail.dev import Orchestrateur
from portail.github import CommentaireGitHub
from portail.ordonnanceur import Ordonnanceur
from portail.taches import deplacer_tache

logger = logging.getLogger(__name__)

PERIODE_S = 120
ARRIVEE = {"fusionnee": "terminee", "fermee": "a_faire"}


def lot_pret(
    commentaires: list[CommentaireGitHub],
    deja: set[tuple[str, int]],
    proprietaire: str,
    depuis: datetime,
    maintenant: datetime,
    delai_s: int,
) -> list[CommentaireGitHub]:
    """Les commentaires de Nicolas à confier à une reprise ; `[]` : rien à lancer.
    Une revue part tout de suite avec ses lignes et les conversations ; des conversations
    seules attendent `delai_s` sans nouveau commentaire, pour partir groupées."""
    gardes = [
        c
        for c in commentaires
        if c.auteur.casefold() == proprietaire.casefold()
        and c.auteur_type == "User"
        and c.cree_le >= depuis
        and (c.type, c.id) not in deja
    ]
    ecartees = {
        c.id for c in gardes if c.type == "revue" and c.etat_revue in ("APPROVED", "DISMISSED")
    }
    revues = [
        c
        for c in gardes
        if c.type == "revue" and c.etat_revue not in ("APPROVED", "DISMISSED") and c.texte.strip()
    ]
    lignes = [c for c in gardes if c.type == "ligne" and c.revue_id not in ecartees]
    conversations = [c for c in gardes if c.type == "conversation"]
    if revues or lignes:
        return [*revues, *lignes, *conversations]
    if conversations and maintenant - max(c.cree_le for c in conversations) >= timedelta(
        seconds=delai_s
    ):
        return conversations
    return []


class SuiviPR:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        github,
        orchestrateur: Orchestrateur,
        ordonnanceur: Ordonnanceur,
        proprietaire: str = "",
        delai_s: int = 600,
        horloge: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._sessions = sessions
        self._github = github
        self._orch = orchestrateur
        self._ordo = ordonnanceur
        self._proprietaire = proprietaire
        self._delai_s = delai_s
        self._horloge = horloge

    async def _a_suivre(self) -> list[tuple]:
        """Par tâche en revue : sa dernière exécution, si elle a une PR et tient le verrou."""
        async with self._sessions() as s:
            lignes = (
                await s.execute(
                    select(ExecutionDev, Tache, Projet.depot_url)
                    .join(Tache, Tache.id == ExecutionDev.tache_id)
                    .join(Projet, Projet.id == Tache.projet_id)
                    .where(Tache.colonne == "en_revue")
                    .order_by(ExecutionDev.id)
                )
            ).all()
        derniere = {ex.tache_id: (ex, t, depot) for ex, t, depot in lignes}
        return [
            (ex, t, depot)
            for ex, t, depot in derniere.values()
            if ex.pr_numero is not None and t.verrou == ex.pipeline_id and depot
        ]

    async def _traiter(self, ex: ExecutionDev, tache: Tache, depot_url: str) -> None:
        etat = await self._github.etat_pr(self._orch.depot(depot_url), ex.pr_numero)
        if etat not in ARRIVEE:  # ouverte
            if self._proprietaire:
                await self._lire(ex, tache, depot_url)
            return
        async with self._sessions() as s:
            # ordre des verrous : le projet d'abord, comme les routes
            await s.scalar(select(Projet.id).where(Projet.id == tache.projet_id).with_for_update())
            t = await s.scalar(
                select(Tache)
                .where(Tache.id == tache.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if t is None or t.colonne != "en_revue" or t.verrou != ex.pipeline_id:
                return  # déplacée entre-temps
            t.verrou = None
            await deplacer_tache(s, t, ARRIVEE[etat], None, "portail")
            await s.commit()
        await self._orch.nettoyer_espace(ex.espace, depot_url)
        if etat == "fusionnee":
            self._ordo.reveiller()  # les tâches dépendantes peuvent partir

    async def _lire(self, ex: ExecutionDev, tache: Tache, depot_url: str) -> None:
        """Les commentaires de la PR ouverte : un lot prêt devient une reprise en attente."""
        depot = self._orch.depot(depot_url)
        commentaires = [
            *await self._github.revues(depot, ex.pr_numero),
            *await self._github.commentaires_ligne(depot, ex.pr_numero),
            *await self._github.commentaires_conversation(depot, ex.pr_numero),
        ]
        async with self._sessions() as s:
            deja = {
                (t, g)
                for t, g in await s.execute(
                    select(CommentairePris.type, CommentairePris.github_id).where(
                        CommentairePris.tache_id == tache.id
                    )
                )
            }
            depuis = await s.scalar(
                select(func.min(ExecutionDev.debut)).where(
                    ExecutionDev.tache_id == tache.id, ExecutionDev.pr_numero == ex.pr_numero
                )
            )
        lot = lot_pret(
            commentaires, deja, self._proprietaire, depuis, self._horloge(), self._delai_s
        )
        if not lot:
            return
        async with self._sessions() as s:
            await s.scalar(select(Projet.id).where(Projet.id == tache.projet_id).with_for_update())
            t = await s.scalar(
                select(Tache)
                .where(Tache.id == tache.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if t is None or t.colonne != "en_revue" or t.verrou != ex.pipeline_id:
                return  # déplacée entre-temps
            try:
                await self._orch.creer_reprise(s, ex, lot)
                await s.commit()
            except IntegrityError:  # commentaire déjà pris par une autre passe
                logger.warning("suivi des PR : tâche %s, commentaires déjà pris", tache.id)
                return
        self._ordo.reveiller()

    async def passer(self) -> None:
        for ex, tache, depot_url in await self._a_suivre():
            try:
                await self._traiter(ex, tache, depot_url)
            except Exception:  # une PR en échec n'arrête pas les autres
                logger.exception("suivi des PR : tâche %s", tache.id)

    async def tourner(self) -> None:
        while True:
            try:
                await self.passer()
            except Exception:  # la boucle ne meurt jamais ; CancelledError l'arrête
                logger.exception("suivi des PR : passage en échec")
            await asyncio.sleep(PERIODE_S)
