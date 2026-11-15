"""Le bureau des agents : qui travaille, attend ou a échoué aujourd'hui. Aucun contenu, que des identifiants."""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from portail.agents import Catalogue, rangement
from portail.contexte import jauge_jetons
from portail.db import (
    ActionConversation,
    AppelLLM,
    Avis,
    Conversation,
    Document,
    Etape,
    ExecutionDev,
    Pipeline,
)
from portail.etats import ANNULE, REPRISE_ABANDONNEE, Etat
from portail.missions import Missions
from portail.moteur import Refus
from portail.schemas import (
    Bureau,
    ConteneurVue,
    Groupe,
    MissionOut,
    Poste,
    PosteDetail,
    Travail,
)

FUSEAU = ZoneInfo("America/Toronto")
LIMITE = 500  # par requête : un bureau n'a que quelques travaux en cours
FENETRE = 200  # lignes d'appel_llm lues par poste
MISSIONS = 10
SONDE_DELAI_S = 1  # délai total d'une sonde ; les sondes partent en parallèle
SONDE_TTL_S = 10  # le bureau recharge chaque seconde : une sonde par agent toutes les 10 s
ORDRE = {"au_travail": 0, "en_attente": 1, "en_erreur": 2}


def debut_du_jour(maintenant: datetime) -> datetime:
    return maintenant.astimezone(FUSEAU).replace(hour=0, minute=0, second=0, microsecond=0)


async def _tour_et_jauge(
    s: AsyncSession, cat: Catalogue, agent: str, travail: Travail, filtre: dict
) -> None:
    """Deux requêtes par travail : la mission de son dernier appel, puis ses appels (compte du tour,
    derniers vrais jetons d'entrée rendus par le modèle)."""
    # ponytail: appel_llm n'est écrit qu'à la fin d'un appel, donc pendant le premier appel d'une
    # nouvelle mission le poste montre encore le tour et la jauge de la précédente ; dater le début
    # de l'activité si cela gêne.
    mission = await s.scalar(
        select(AppelLLM.mission)
        .where(AppelLLM.agent == agent, *(getattr(AppelLLM, k) == v for k, v in filtre.items()))
        .order_by(AppelLLM.id.desc())
        .limit(1)
    )
    if mission is None:
        return
    dernier = (
        select(AppelLLM.jetons_entree)
        .where(AppelLLM.mission == mission, AppelLLM.jetons_entree.is_not(None))
        .order_by(AppelLLM.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    n, jetons = (
        await s.execute(select(func.count(), dernier).where(AppelLLM.mission == mission))
    ).one()
    if travail.etat == "au_travail":
        travail.tour = n
    if jetons:
        travail.jauge = jauge_jetons(jetons, cat.agents[agent].contexte_max)


async def _conteneurs(missions: Missions | None, cat: Catalogue) -> dict[str, ConteneurVue]:
    """Seuls les agents à `service:` sont sondés, en parallèle, sous un délai total court ; un échec
    (délai, réponse hors bornes, exception) vaut « ne répond pas ». Aucune erreur ne remonte."""
    if missions is None:
        return {}
    maintenant = missions.horloge()
    perimes = [
        n
        for n, a in cat.agents.items()
        if a.service
        and not (n in missions.sondes and maintenant - missions.sondes[n][0] < SONDE_TTL_S)
    ]
    rendus = await asyncio.gather(
        *(missions.sante(cat.agents[n], SONDE_DELAI_S) for n in perimes), return_exceptions=True
    )
    for n, r in zip(perimes, rendus, strict=True):
        missions.sondes[n] = (maintenant, None if isinstance(r, BaseException) else r)
    vues = {}
    for n, a in cat.agents.items():
        if a.service:
            sante = missions.sondes[n][1]
            vues[n] = ConteneurVue(
                repond=sante is not None, version=sante.version if sante else None
            )
    return vues


async def lire_bureau(
    s: AsyncSession, cat: Catalogue, maintenant: datetime, missions: Missions | None = None
) -> Bureau:
    conteneurs = await _conteneurs(missions, cat)
    debut = debut_du_jour(maintenant)
    agents = list(cat.agents)
    # par agent : (rang d'état, identifiant, travail, filtre des lignes d'appel_llm du travail)
    trouves: dict[str, list[tuple[int, int, Travail, dict]]] = {a: [] for a in agents}

    def ajouter(agent: str, ident: int, filtre: dict, **t) -> None:
        trouves[agent].append((ORDRE[t["etat"]], ident, Travail(**t), filtre))

    # étapes de pipeline : actives, ou échouées aujourd'hui (annulée ou abandonnée : pas une erreur)
    tache = (
        select(ExecutionDev.tache_id)
        .where(ExecutionDev.pipeline_id == Pipeline.id)
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
                & Etape.erreur.is_distinct_from(ANNULE)
                & Etape.erreur.is_distinct_from(REPRISE_ABANDONNEE)
                & (Pipeline.etat == Etat.ECHOUEE)
                # ponytail: un poste reste en erreur jusqu'à minuit même si la tâche a été reprise
                # avec succès ; ignorer l'erreur si un pipeline plus récent de la tâche a réussi.
                & (Pipeline.maj_le >= debut)
            ),
        )
        # les travaux actifs d'abord : la coupure ne doit pas les perdre au profit d'erreurs
        .order_by(case((Etape.etat == Etat.ECHOUEE, 1), else_=0), Etape.id.desc())
        .limit(LIMITE)
    )
    for eid, agent, etat, pid, type_, tid in rows:
        etat = {Etat.EN_COURS: "au_travail", Etat.EN_ATTENTE: "en_attente"}.get(etat, "en_erreur")
        libelle = f"T{tid}" if type_ == "dev" and tid else f"{type_} #{pid}"
        ajouter(
            agent,
            eid,
            {"etape_id": eid},
            sorte="etape",
            etat=etat,
            libelle=libelle,
            lien=f"/pipelines/{pid}",
        )

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
        .order_by(Conversation.id.desc())
        .limit(LIMITE)
    )
    for cid, agent, etat in rows:
        etat = {"en_cours": "au_travail", "pret": "en_attente"}.get(etat, "en_erreur")
        ajouter(
            agent,
            cid,
            {"conversation_id": cid},
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
        .order_by(Avis.id.desc())
        .limit(LIMITE)
    )
    for aid, agent, type_, pid in rows:
        # un avis ne pose que le pipeline dans le contexte du journal, jamais l'étape
        ajouter(
            agent,
            aid,
            {"pipeline_id": pid, "etape_id": None},
            sorte="avis",
            etat="au_travail",
            libelle=f"avis {type_} #{pid}",
            lien=f"/pipelines/{pid}",
        )

    # activité du jour : une requête pour tous les postes
    activite = {
        agent: (n, int(jetons))
        for agent, n, jetons in await s.execute(
            select(
                AppelLLM.agent,
                func.count(),
                func.sum(
                    func.coalesce(AppelLLM.jetons_entree, 0)
                    + func.coalesce(AppelLLM.jetons_sortie, 0)
                ),
            )
            .where(AppelLLM.quand >= debut)
            .group_by(AppelLLM.agent)
        )
        if agent in trouves
    }

    postes = {}
    for a in agents:
        travaux = []
        for _, _, t, filtre in sorted(trouves[a], key=lambda x: x[:2]):
            await _tour_et_jauge(s, cat, a, t, filtre)
            travaux.append(t)
        etat = next(
            (
                e
                for e in ("au_travail", "en_attente", "en_erreur")
                if any(t.etat == e for t in travaux)
            ),
            "libre",
        )
        n, jetons = activite.get(a, (0, 0))
        postes[a] = Poste(
            nom=a,
            etat=etat,
            travaux=travaux,
            appels_jour=n,
            jetons_jour=jetons,
            conteneur=conteneurs.get(a),
        )
    return Bureau(groupes=[Groupe(nom=n, agents=g) for n, g in rangement(cat)], postes=postes)


def _libelle_et_lien(a: AppelLLM) -> tuple[str | None, str | None]:
    if a.tache_id:
        return f"T{a.tache_id}", f"/pipelines/{a.pipeline_id}" if a.pipeline_id else None
    if a.conversation_id:
        return f"conversation #{a.conversation_id}", f"/chat/{a.conversation_id}"
    if a.pipeline_id:
        return f"pipeline #{a.pipeline_id}", f"/pipelines/{a.pipeline_id}"
    return None, None


async def lire_poste(s: AsyncSession, cat: Catalogue, nom: str) -> PosteDetail:
    agent = cat.agents.get(nom)
    if agent is None:
        raise Refus(404, "agent inconnu")  # sans écho du nom : il vient de l'URL
    # ponytail: la fenêtre peut couper la plus ancienne mission (ses derniers appels manquent) ;
    # agréger en SQL par mission si cela gêne.
    lignes = (
        await s.scalars(
            select(AppelLLM)
            .where(AppelLLM.agent == nom, AppelLLM.mission.is_not(None))
            .order_by(AppelLLM.id.desc())
            .limit(FENETRE)
        )
    ).all()
    groupes: dict[str, list[AppelLLM]] = {}  # du plus récent au plus ancien
    for a in lignes:
        groupes.setdefault(a.mission, []).append(a)
    missions = []
    for mission, g in list(groupes.items())[:MISSIONS]:
        # la ligne est inscrite à la fin de l'appel : le début est `quand - duree_ms`
        debut = min(a.quand - timedelta(milliseconds=a.duree_ms) for a in g)
        libelle, lien = _libelle_et_lien(next((a for a in g if a.tache_id), g[0]))
        missions.append(
            MissionOut(
                mission=mission,
                debut=debut,
                duree_ms=int((max(a.quand for a in g) - debut).total_seconds() * 1000),
                appels=len(g),
                jetons_entree=sum(a.jetons_entree or 0 for a in g),
                jetons_sortie=sum(a.jetons_sortie or 0 for a in g),
                issue=g[0].issue,  # le dernier appel : une erreur suivie d'un succès est un succès
                libelle=libelle,
                lien=lien,
            )
        )
    return PosteDetail(
        nom=nom,
        description=agent.description,
        modele=agent.modele,
        modele_si_meme=agent.modele_si_meme,
        outils=list(agent.outils),
        tours_max=agent.tours_max,
        contexte_max=agent.contexte_max,
        missions=missions,
    )
