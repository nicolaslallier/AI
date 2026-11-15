"""Métriques Prometheus : identifiants, noms et compteurs seulement, jamais de contenu."""

import asyncio
import logging
from datetime import UTC, datetime

from prometheus_client import REGISTRY, Counter, Gauge, Histogram
from sqlalchemy import func, select

from portail import journal
from portail.config import Reglages
from portail.db import ExecutionDev, Pipeline, Tache
from portail.etats import Etat
from portail.schemas import COLONNES

logger = logging.getLogger(__name__)

INFO = Gauge("portail_info", "Version du portail déployée", ["version"])
DEPLOIEMENT = Gauge("portail_deploiement_horodatage_secondes", "Instant du déploiement (Unix)")
DUREE_MAX_TACHE = Gauge("portail_duree_max_tache_secondes", "Durée maximale d'une tâche")

_LLM = ["agent", "modele", "lieu"]
LLM_APPELS = Counter("portail_llm_appels_total", "Appels au modèle", [*_LLM, "issue"])
LLM_JETONS = Counter("portail_llm_jetons_total", "Jetons rendus par LiteLLM", [*_LLM, "sens"])
LLM_DUREE = Histogram(
    "portail_llm_duree_secondes", "Durée d'un appel au modèle", _LLM,
    buckets=(1, 5, 15, 30, 60, 120, 300),
)  # fmt: skip
CONTEXTE_REMPLISSAGE = Histogram(
    "portail_contexte_remplissage", "Jetons d'entrée / contexte maximal de l'agent", ["agent"],
    buckets=(0.25, 0.5, 0.75, 0.9, 1.0),
)  # fmt: skip
TOURS_MISSION = Histogram(
    "portail_tours_mission", "Appels au modèle d'une boucle d'outils", ["agent"],
    buckets=(1, 2, 4, 8, 12, 16, 20, 30),
)  # fmt: skip
OUTILS_APPELS = Counter(
    "portail_outils_appels_total", "Appels d'outils", ["agent", "outil", "issue"]
)
HTTP_REQUETES = Counter(
    "portail_http_requetes_total", "Requêtes HTTP", ["methode", "route", "code"]
)
HTTP_DUREE = Histogram(
    "portail_http_duree_secondes", "Durée d'une requête HTTP", ["methode", "route"]
)
FLUX_OUVERTS = Gauge("portail_flux_ouverts", "Flux SSE ouverts", ["flux"])

PHASES_DEV = Counter("portail_phases_dev_total", "Phases de la boucle de dev", ["phase", "issue"])
EXECUTIONS_DEV = Counter(
    "portail_executions_dev_total", "Exécutions de la boucle de dev", ["mode", "issue"]
)
RENVOIS = Counter(
    "portail_renvois_total", "Renvois en arrière de la boucle de dev", ["agent", "vers"]
)
BLOCAGES = Counter("portail_blocages_total", "Blocages de la boucle de dev", ["cause", "phase"])
DUREE_TACHE = Histogram(
    "portail_duree_tache_secondes", "Durée d'une exécution normale, du démarrage à la revue",
    buckets=(300, 900, 1800, 3600, 7200, 14400),
)  # fmt: skip
REPRISES = Counter("portail_reprises_total", "Reprises créées sur commentaires de PR")
LANCEUR_COMMANDES = Counter(
    "portail_lanceur_commandes_total", "Commandes lancées dans le lanceur", ["nom", "code"]
)
LANCEUR_DUREE = Histogram(
    "portail_lanceur_duree_secondes", "Durée d'une commande du lanceur", ["nom"],
    buckets=(1, 5, 15, 60, 300, 600, 1800),
)  # fmt: skip
TACHES = Gauge("portail_taches", "Tâches par colonne du kanban", ["colonne"])
TACHE_AGE_MAX = Gauge(
    "portail_tache_en_cours_age_max_secondes", "Âge de la plus ancienne exécution dev en cours"
)
ECHECS_DEV = Gauge(
    "portail_echecs_dev_consecutifs", "Échecs consécutifs parmi les derniers pipelines dev"
)
BASE_JOIGNABLE = Gauge("portail_base_joignable", "1 si la base répond à la collecte")
BASE_JOIGNABLE.set(1)  # présumée joignable : la première panne est journalisée
for _c in COLONNES:  # chaque colonne existe dès le démarrage, même vide
    TACHES.labels(_c).set(0)

DELAI_COLLECTE_S = 5


async def _lire(sessions):
    async with sessions() as s:
        par_colonne = dict((await s.execute(
            select(Tache.colonne, func.count()).group_by(Tache.colonne)
        )).all())  # fmt: skip
        debut = await s.scalar(
            select(func.min(ExecutionDev.debut))
            .join(Pipeline, Pipeline.id == ExecutionDev.pipeline_id)
            .where(Pipeline.type == "dev", Pipeline.etat == Etat.EN_COURS)
        )
        derniers = (await s.scalars(
            select(Pipeline.etat)
            .where(Pipeline.type == "dev", Pipeline.etat.in_((Etat.TERMINEE, Etat.ECHOUEE)))
            .order_by(Pipeline.maj_le.desc(), Pipeline.id.desc())
            .limit(10)
        )).all()  # fmt: skip
    return par_colonne, debut, derniers


async def rafraichir(sessions) -> None:
    """Jauges lues en base : trois requêtes d'agrégat, bornées dans le temps. En cas d'échec les
    jauges gardent leur dernière valeur et seule `portail_base_joignable` passe à 0."""
    try:
        async with asyncio.timeout(DELAI_COLLECTE_S):
            par_colonne, debut, derniers = await _lire(sessions)
    except Exception:  # noqa: BLE001 — la collecte ne doit jamais rendre /metrics inutilisable
        if REGISTRY.get_sample_value("portail_base_joignable") != 0:  # seulement à la transition
            journal.erreur(logger, "collecte des jauges en base impossible")
        BASE_JOIGNABLE.set(0)
        return
    for c in COLONNES:  # ponytail: ensemble fixe ; une colonne inconnue en base est ignorée
        TACHES.labels(c).set(par_colonne.get(c, 0))
    age = 0.0
    if debut is not None:
        age = (datetime.now(UTC) - debut.replace(tzinfo=debut.tzinfo or UTC)).total_seconds()
    TACHE_AGE_MAX.set(max(age, 0.0))
    ECHECS_DEV.set(next((i for i, e in enumerate(derniers) if e == Etat.TERMINEE), len(derniers)))
    BASE_JOIGNABLE.set(1)


def initialiser(r: Reglages) -> None:
    INFO.clear()  # ponytail: une seule version à la fois, même si l'application est recréée
    INFO.labels(version=r.version).set(1)
    DEPLOIEMENT.set(r.deploye_le)
    DUREE_MAX_TACHE.set(r.duree_max_tache_s)
