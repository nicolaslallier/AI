from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from portail.agents import Catalogue
from portail.db import Etape, Pipeline
from portail.etats import Etat, etat_pipeline


class Refus(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


async def creer_pipeline(
    session: AsyncSession, catalogue: Catalogue, projet_id: int, type_: str
) -> Pipeline:
    if type_ not in catalogue.pipelines:
        raise Refus(404, f"type de pipeline inconnu : {type_}")
    pipeline = Pipeline(projet_id=projet_id, type=type_)
    pipeline.etapes = [
        Etape(ordre=i, agent=a, etat=Etat.A_FAIRE) for i, a in enumerate(catalogue.pipelines[type_])
    ]
    session.add(pipeline)
    await session.flush()
    await demarrer_etape(session, pipeline.etapes[0])
    return pipeline


async def demarrer_etape(session: AsyncSession, etape: Etape) -> None:
    # en A, toutes les étapes sont des chats : c'est à Nicolas de parler
    await changer_etat(session, etape, Etat.EN_ATTENTE)


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


async def terminer_etape(session: AsyncSession, etape: Etape) -> None:
    await changer_etat(session, etape, Etat.TERMINEE)
    suivante = await session.scalar(
        select(Etape).where(Etape.pipeline_id == etape.pipeline_id, Etape.ordre == etape.ordre + 1)
    )
    if suivante:
        await demarrer_etape(session, suivante)


async def recuperer_interrompues(session: AsyncSession) -> int:
    etapes = (await session.scalars(select(Etape).where(Etape.etat == Etat.EN_COURS))).all()
    for e in etapes:
        await changer_etat(session, e, Etat.ECHOUEE, "interrompue par un redémarrage du serveur")
    return len(etapes)
