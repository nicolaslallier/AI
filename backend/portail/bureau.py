"""Le bureau des agents : qui travaille, attend ou a échoué aujourd'hui. Aucun contenu, que des identifiants."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from portail.agents import Catalogue, rangement
from portail.db import (
    ActionConversation,
    Avis,
    Conversation,
    Document,
    Etape,
    ExecutionDev,
    Pipeline,
)
from portail.etats import Etat
from portail.schemas import Bureau, Groupe, Poste, Travail

FUSEAU = ZoneInfo("America/Toronto")
LIMITE = 500  # par requête : un bureau n'a que quelques travaux en cours
ORDRE = {"au_travail": 0, "en_attente": 1, "en_erreur": 2}


def debut_du_jour(maintenant: datetime) -> datetime:
    return maintenant.astimezone(FUSEAU).replace(hour=0, minute=0, second=0, microsecond=0)


async def lire_bureau(s: AsyncSession, cat: Catalogue, maintenant: datetime) -> Bureau:
    debut = debut_du_jour(maintenant)
    agents = list(cat.agents)
    trouves: dict[str, list[tuple[int, int, Travail]]] = {a: [] for a in agents}

    def ajouter(agent: str, ident: int, **t) -> None:
        trouves[agent].append((ORDRE[t["etat"]], ident, Travail(**t)))

    # étapes de pipeline : actives, ou échouées aujourd'hui (une étape annulée n'est pas une erreur)
    tache = (
        select(ExecutionDev.tache_id)
        .where(ExecutionDev.pipeline_id == Pipeline.id)
        .order_by(ExecutionDev.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    actif = [Etat.EN_COURS, Etat.EN_ATTENTE]
    rows = await s.execute(
        select(Etape.id, Etape.agent, Etape.etat, Pipeline.id, Pipeline.type, tache)
        .join(Pipeline, Pipeline.id == Etape.pipeline_id)
        .where(
            Etape.agent.in_(agents),
            (Etape.etat.in_(actif) & Pipeline.etat.in_(actif))
            | (
                (Etape.etat == Etat.ECHOUEE)
                & Etape.erreur.is_distinct_from("annulé")
                & (Pipeline.etat == Etat.ECHOUEE)
                & (Pipeline.maj_le >= debut)
            ),
        )
        .limit(LIMITE)
    )
    for eid, agent, etat, pid, type_, tid in rows:
        etat = {Etat.EN_COURS: "au_travail", Etat.EN_ATTENTE: "en_attente"}.get(etat, "en_erreur")
        libelle = f"T{tid}" if type_ == "dev" and tid else f"{type_} #{pid}"
        ajouter(agent, eid, sorte="etape", etat=etat, libelle=libelle, lien=f"/pipelines/{pid}")

    # conversations : en cours, en attente d'une action proposée, ou en erreur aujourd'hui
    proposees = select(ActionConversation.conversation_id).where(
        ActionConversation.etat == "proposee"
    )
    rows = await s.execute(
        select(Conversation.id, Conversation.agent, Conversation.etat)
        .where(
            Conversation.agent.in_(agents),
            (Conversation.etat == "en_cours")
            | ((Conversation.etat == "pret") & Conversation.id.in_(proposees))
            | ((Conversation.etat == "erreur") & (Conversation.maj_le >= debut)),
        )
        .limit(LIMITE)
    )
    for cid, agent, etat in rows:
        etat = {"en_cours": "au_travail", "pret": "en_attente"}.get(etat, "en_erreur")
        ajouter(
            agent,
            cid,
            sorte="conversation",
            etat=etat,
            libelle=f"conversation #{cid}",
            lien=f"/chat/{cid}",
        )

    # avis en cours
    rows = await s.execute(
        select(Avis.id, Avis.agent, Document.type, Document.pipeline_id)
        .join(Document, Document.id == Avis.document_id)
        .where(Avis.agent.in_(agents), Avis.etat == "en_cours")
        .limit(LIMITE)
    )
    for aid, agent, type_, pid in rows:
        ajouter(
            agent, aid, sorte="avis", etat="au_travail", libelle=f"avis {type_} #{pid}",
            lien=f"/pipelines/{pid}",
        )  # fmt: skip

    postes = {}
    for a in agents:
        travaux = [t for _, _, t in sorted(trouves[a], key=lambda x: x[:2])]
        etat = next(
            (
                e
                for e in ("au_travail", "en_attente", "en_erreur")
                if any(t.etat == e for t in travaux)
            ),
            "libre",
        )
        postes[a] = Poste(nom=a, etat=etat, travaux=travaux)
    return Bureau(groupes=[Groupe(nom=n, agents=g) for n, g in rangement(cat)], postes=postes)
