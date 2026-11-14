"""Suivi minimal des PR : une PR fusionnée termine la tâche, une PR fermée la renvoie à faire."""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portail.db import ExecutionDev, Projet, Tache
from portail.dev import Orchestrateur
from portail.ordonnanceur import Ordonnanceur
from portail.taches import deplacer_tache

logger = logging.getLogger(__name__)

PERIODE_S = 120
ARRIVEE = {"fusionnee": "terminee", "fermee": "a_faire"}


class SuiviPR:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        github,
        orchestrateur: Orchestrateur,
        ordonnanceur: Ordonnanceur,
    ):
        self._sessions = sessions
        self._github = github
        self._orch = orchestrateur
        self._ordo = ordonnanceur

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
        if etat not in ARRIVEE:
            return  # ouverte
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
