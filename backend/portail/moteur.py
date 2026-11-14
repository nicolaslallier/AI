from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from portail.agents import Catalogue
from portail.db import Document, Etape, Pipeline, Proposition
from portail.etats import Etat, etat_pipeline


class Refus(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


async def spec_courante(session: AsyncSession, projet_id: int) -> Document | None:
    return await session.scalar(
        select(Document)
        .where(
            Document.projet_id == projet_id,
            Document.type == "spec",
            Document.etat == "validee",
        )
        .order_by(Document.maj_le.desc())
        .limit(1)
    )


async def creer_pipeline(
    session: AsyncSession, catalogue: Catalogue, projet_id: int, type_: str
) -> tuple[Pipeline, Etape | None]:
    """Renvoie le pipeline et l'étape à lancer (agent auto), à lancer après le commit."""
    if type_ not in catalogue.pipelines:
        raise Refus(404, f"type de pipeline inconnu : {type_}")
    if type_ == "planification":
        if await spec_courante(session, projet_id) is None:
            raise Refus(409, "aucune spec validée pour ce projet")
        actif = await session.scalar(
            select(Pipeline.id)
            .where(
                Pipeline.projet_id == projet_id,
                Pipeline.type == "planification",
                Pipeline.etat.not_in([Etat.TERMINEE, Etat.ECHOUEE]),
            )
            .limit(1)
        )
        if actif is not None:
            raise Refus(409, "une planification est déjà en cours pour ce projet")
    pipeline = Pipeline(projet_id=projet_id, type=type_)
    pipeline.etapes = [
        Etape(ordre=i, agent=a, etat=Etat.A_FAIRE) for i, a in enumerate(catalogue.pipelines[type_])
    ]
    session.add(pipeline)
    await session.flush()
    premiere = pipeline.etapes[0]
    lancer = await demarrer_etape(session, catalogue, premiere)
    return pipeline, premiere if lancer else None


async def demarrer_etape(session: AsyncSession, catalogue: Catalogue, etape: Etape) -> bool:
    """True si l'agent est auto : l'appelant lance la tâche de fond après le commit."""
    agent = catalogue.agents.get(etape.agent)
    if agent is None or not agent.auto:
        await changer_etat(session, etape, Etat.EN_ATTENTE)
        return False
    etape.action = "taches" if agent.produit == "taches" else "rediger"
    await changer_etat(session, etape, Etat.EN_COURS)
    return True


async def changer_etat(
    session: AsyncSession, etape: Etape, etat: Etat, erreur: str | None = None
) -> None:
    etape.etat = etat
    etape.erreur = erreur
    await session.flush()
    etats = (
        await session.scalars(select(Etape.etat).where(Etape.pipeline_id == etape.pipeline_id))
    ).all()
    pipeline = await session.get(Pipeline, etape.pipeline_id)
    pipeline.etat = etat_pipeline([Etat(e) for e in etats])
    pipeline.maj_le = datetime.now(UTC)
    await session.flush()


async def terminer_etape(session: AsyncSession, catalogue: Catalogue, etape: Etape) -> Etape | None:
    """Renvoie l'étape suivante si elle doit être lancée (agent auto)."""
    await changer_etat(session, etape, Etat.TERMINEE)
    suivante = await session.scalar(
        select(Etape).where(Etape.pipeline_id == etape.pipeline_id, Etape.ordre == etape.ordre + 1)
    )
    if suivante and await demarrer_etape(session, catalogue, suivante):
        return suivante
    return None


async def annuler_pipeline(session: AsyncSession, pipeline: Pipeline) -> None:
    if pipeline.etat in (Etat.TERMINEE, Etat.ECHOUEE):
        raise Refus(409, "pipeline déjà terminé")
    etape = await session.scalar(
        select(Etape).where(
            Etape.pipeline_id == pipeline.id, Etape.etat.in_([Etat.EN_COURS, Etat.EN_ATTENTE])
        )
    )
    if etape:
        await changer_etat(session, etape, Etat.ECHOUEE, "annulé")
    await session.execute(
        update(Proposition)
        .where(Proposition.pipeline_id == pipeline.id, Proposition.etat == "ouverte")
        .values(etat="rejetee")
    )
    await session.flush()


async def recuperer_interrompues(session: AsyncSession) -> int:
    etapes = (await session.scalars(select(Etape).where(Etape.etat == Etat.EN_COURS))).all()
    for e in etapes:
        await changer_etat(session, e, Etat.ECHOUEE, "interrompue par un redémarrage du serveur")
    return len(etapes)
