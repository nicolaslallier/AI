"""Pipeline architecture : annexes des étapes et contrôle des blocs de modèle."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from portail.agents import Catalogue
from portail.archimate import lire_bloc, valider, valider_synthese
from portail.db import Document, Etape


async def documents_precedents(s: AsyncSession, etape: Etape) -> list[tuple[Etape, Document]]:
    """Documents validés des étapes d'ordre inférieur du même pipeline, dans l'ordre."""
    lignes = await s.execute(
        select(Etape, Document)
        .join(Document, Document.etape_id == Etape.id)
        .where(
            Etape.pipeline_id == etape.pipeline_id,
            Etape.ordre < etape.ordre,
            Document.etat == "validee",
        )
        .order_by(Etape.ordre)
    )
    return [(e, d) for e, d in lignes.all()]


async def annexes_architecture(s: AsyncSession, catalogue: Catalogue, etape: Etape) -> list[str]:
    """La vision validée puis chaque volet précédent, bloc JSON compris."""
    sortie = []
    for e, doc in await documents_precedents(s, etape):
        agent = catalogue.agents.get(e.agent)
        if agent and agent.produit == "volet":
            sortie.append(f"Volet {agent.volet} ({agent.nom}) :\n\n{doc.contenu}")
        elif agent and agent.produit == "vision":
            sortie.append("Vision validée :\n\n" + doc.contenu)
    return sortie


async def verifier_bloc(s: AsyncSession, catalogue: Catalogue, etape: Etape, contenu: str) -> None:
    """Lève BlocInvalide si le bloc de modèle de `contenu` ne respecte pas les règles de l'étape."""
    agent = catalogue.agents[etape.agent]
    _, modele = lire_bloc(contenu)
    connus = {
        el.id
        for _, doc in await documents_precedents(s, etape)
        for el in lire_bloc(doc.contenu)[1].elements
    }
    if agent.produit == "architecture":
        valider_synthese(modele, connus)
    else:
        valider(modele, agent.prefixe, connus)
