"""Ordonnanceur de la boucle de dev : les tâches *Prêtes* partent seules, une à la fois
(`paralleles_max`), et un pipeline interrompu par un redémarrage repart une seule fois."""

import asyncio
import logging

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from portail.db import Etape, ExecutionDev, Pipeline, Projet, Tache, TacheDependance
from portail.dev import Orchestrateur
from portail.etats import Etat

logger = logging.getLogger(__name__)

PERIODE_S = 30


async def choisir(session: AsyncSession) -> Tache | None:
    """La tâche *Prête* sans verrou, aux dépendances terminées, de plus petit `(rang, id)` ;
    sa ligne reste verrouillée jusqu'à la fin de la transaction de l'appelant."""
    dep = aliased(Tache)
    bloquante = exists().where(
        TacheDependance.tache_id == Tache.id,
        dep.id == TacheDependance.depend_de_id,
        dep.colonne != "terminee",
    )
    return await session.scalar(
        select(Tache)
        .join(Projet, Projet.id == Tache.projet_id)
        .where(
            Tache.colonne == "prete",
            Tache.verrou.is_(None),
            Projet.depot_url.is_not(None),
            Projet.config_execution.is_not(None),
            ~bloquante,
        )
        .order_by(Tache.rang, Tache.id)
        .limit(1)
        .with_for_update(skip_locked=True, of=Tache)
    )


class Ordonnanceur:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        orchestrateur: Orchestrateur,
        paralleles_max: int,
    ):
        self._sessions = sessions
        self._orch = orchestrateur
        self._max = paralleles_max
        self._reveil = asyncio.Event()

    def reveiller(self) -> None:
        self._reveil.set()

    async def tour(self) -> None:
        """Démarre des tâches tant qu'il reste de la place."""
        while len(self._orch.taches) < self._max:
            async with self._sessions() as s:
                tache = await choisir(s)
                if tache is None:
                    return
                # ordre des verrous : le projet passe avant les tâches partout ailleurs ;
                # tenir la tâche en attendant le projet pourrait s'interbloquer avec une route
                libre = await s.scalar(
                    select(Projet.id)
                    .where(Projet.id == tache.projet_id)
                    .with_for_update(skip_locked=True)
                )
                if libre is None:
                    return  # la route occupée réveillera l'ordonnanceur après son commit
                pipeline = await self._orch.demarrer(s, tache)
                await s.commit()
            self._orch.lancer(pipeline.id)
            self._orch.taches[pipeline.id].add_done_callback(lambda _: self.reveiller())

    async def tourner(self) -> None:
        while True:
            self._reveil.clear()
            try:
                await self.tour()
            except Exception:  # la boucle ne meurt jamais ; CancelledError l'arrête
                logger.exception("ordonnanceur : tour en échec")
            try:
                async with asyncio.timeout(PERIODE_S):
                    await self._reveil.wait()
            except TimeoutError:
                pass


async def reprendre_interrompues(
    sessions: async_sessionmaker[AsyncSession], orchestrateur: Orchestrateur
) -> None:
    """Au démarrage : chaque pipeline `dev` en cours repart de sa phase, une seule fois."""
    async with sessions() as s:
        executions = (
            await s.scalars(
                select(ExecutionDev)
                .join(Pipeline, Pipeline.id == ExecutionDev.pipeline_id)
                .where(ExecutionDev.phase != "fini", Pipeline.etat == Etat.EN_COURS)
                .order_by(ExecutionDev.id)
            )
        ).all()
        for ex in executions:
            await s.execute(
                update(Etape)
                .where(Etape.pipeline_id == ex.pipeline_id, Etape.etat == Etat.EN_COURS)
                .values(etat=Etat.ECHOUEE, erreur="interrompue par un redémarrage")
            )
            ex.interruptions += 1
        reprises = [(ex.pipeline_id, ex.interruptions) for ex in executions]
        await s.commit()
    for pipeline_id, interruptions in reprises:
        if interruptions <= 1:
            orchestrateur.lancer(pipeline_id)
        else:
            await orchestrateur.bloquer(pipeline_id, "interrompue deux fois")
