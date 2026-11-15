"""Ordonnanceur de la boucle de dev : les tâches *Prêtes* et les reprises partent seules,
une à la fois (`paralleles_max`), et un pipeline interrompu par un redémarrage repart une seule fois."""

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from portail import journal
from portail.audit import inscrire
from portail.db import (
    CommentairePris,
    Etape,
    ExecutionDev,
    Pipeline,
    Projet,
    Tache,
    TacheDependance,
)
from portail.dev import Orchestrateur
from portail.etats import Etat
from portail.github import ErreurGitHub
from portail.taches import deplacer_tache

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


async def choisir_reprise(session: AsyncSession) -> ExecutionDev | None:
    """La reprise en attente aux commentaires les plus anciens ; sa ligne reste verrouillée
    jusqu'à la fin de la transaction de l'appelant."""
    premier = (
        select(func.min(CommentairePris.cree_le))
        .where(CommentairePris.execution_id == ExecutionDev.id)
        .scalar_subquery()
    )
    return await session.scalar(
        select(ExecutionDev)
        .join(Pipeline, Pipeline.id == ExecutionDev.pipeline_id)
        .where(ExecutionDev.mode == "reprise", Pipeline.etat == Etat.EN_ATTENTE)
        .order_by(premier, ExecutionDev.id)
        .limit(1)
        .with_for_update(skip_locked=True, of=ExecutionDev)
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

    def lancer(self, pipeline_id: int) -> None:
        """Lance en tâche de fond ; sa fin libère une place et réveille l'ordonnanceur."""
        self._orch.lancer(pipeline_id)
        self._orch.taches[pipeline_id].add_done_callback(lambda _: self.reveiller())

    async def tour(self) -> None:
        """Démarre des tâches tant qu'il reste de la place : les reprises d'abord."""
        while len(self._orch.taches) < self._max:
            reprise = await self._reprise()
            if reprise is None:
                return
            if reprise:
                continue
            async with self._sessions() as s:  # repérage : verrou relâché avant GitHub
                tache = await choisir(s)
                if tache is None:
                    return
                tache_id, projet = tache.id, await s.get(Projet, tache.projet_id)
            try:
                base = await self._orch.base(projet)
                async with self._sessions() as s:
                    tache = await choisir(s)
                    if tache is None:
                        return
                    if tache.id != tache_id:
                        continue  # la file a changé entre-temps : on recommence
                    # ordre des verrous : le projet passe avant les tâches partout ailleurs ;
                    # tenir la tâche en attendant le projet pourrait s'interbloquer avec une route
                    libre = await s.scalar(
                        select(Projet.id)
                        .where(Projet.id == tache.projet_id)
                        .with_for_update(skip_locked=True)
                    )
                    if libre is None:
                        return  # la route occupée réveillera l'ordonnanceur après son commit
                    pipeline = await self._orch.demarrer(s, tache, base)
                    inscrire(s, "ordonnanceur", "pipeline.lancer", "pipeline", pipeline.id)
                    await s.commit()
            except Exception as e:  # noqa: BLE001
                passagere = isinstance(e, SQLAlchemyError) or (
                    isinstance(e, ErreurGitHub) and e.transitoire
                )
                if passagere:  # GitHub ou base : la tâche reste Prête, retentée au tour suivant
                    logger.warning(
                        "ordonnanceur : tâche %s reportée (%s)", tache_id, type(e).__name__
                    )
                    return
                # sinon elle reviendrait à chaque tour, devant les autres
                journal.erreur(
                    logger, "ordonnanceur : démarrage de la tâche %s impossible", tache_id
                )
                await self._bloquer(tache_id, f"démarrage impossible : {e}")
                continue
            self.lancer(pipeline.id)

    async def _reprise(self) -> bool | None:
        """Démarre la plus ancienne reprise en attente. `True` : une reprise a été traitée ;
        `False` : aucune ; `None` : projet occupé, le tour s'arrête."""
        async with self._sessions() as s:
            ex = await choisir_reprise(s)
            if ex is None:
                return False
            # comme pour les tâches : le projet en `skip_locked`, jamais en attente
            libre = await s.scalar(
                select(Projet.id)
                .join(Tache, Tache.projet_id == Projet.id)
                .where(Tache.id == ex.tache_id)
                .with_for_update(skip_locked=True, of=Projet)
            )
            if libre is None:
                return None
            pipeline_id = ex.pipeline_id
            demarree = await self._orch.demarrer_reprise(s, ex)
            await s.commit()
        if demarree:
            self.lancer(pipeline_id)
        return True

    async def _bloquer(self, tache_id: int, raison: str) -> None:
        async with self._sessions() as s:
            projet_id = await s.scalar(select(Tache.projet_id).where(Tache.id == tache_id))
            await s.scalar(select(Projet.id).where(Projet.id == projet_id).with_for_update())
            tache = await s.scalar(
                select(Tache)
                .where(Tache.id == tache_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if tache is None or tache.colonne != "prete" or tache.verrou is not None:
                return  # déplacée entre-temps : on n'y touche pas
            await deplacer_tache(s, tache, "bloquee", None, "portail")
            tache.resume_blocage = raison
            await s.commit()
        try:
            await self._orch.notifier(
                tache_id,
                "Bloquée",
                self._orch.lien(f"/projets/{projet_id}/kanban"),
            )
        except Exception as e:  # noqa: BLE001 — jamais str(e) : pas de fuite
            logger.warning("ordonnanceur : notification impossible (%s)", type(e).__name__)

    async def tourner(self) -> None:
        while True:
            self._reveil.clear()
            try:
                await self.tour()
            except Exception:  # la boucle ne meurt jamais ; CancelledError l'arrête  # noqa: BLE001
                journal.erreur(logger, "ordonnanceur : tour en échec")
            try:
                async with asyncio.timeout(PERIODE_S):
                    await self._reveil.wait()
            except TimeoutError:
                pass


async def reprendre_interrompues(
    sessions: async_sessionmaker[AsyncSession],
    orchestrateur: Orchestrateur,
    lancer: Callable[[int], None] | None = None,
) -> None:
    """Au démarrage : chaque pipeline `dev` en cours repart de sa phase, une seule fois.
    `lancer` : `Ordonnanceur.lancer`, pour que la fin d'une reprise libère sa place."""
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
            (lancer or orchestrateur.lancer)(pipeline_id)
        else:
            await orchestrateur.bloquer(pipeline_id, "interrompue deux fois")
