"""Métriques Prometheus : identifiants, noms et compteurs seulement, jamais de contenu."""

from prometheus_client import Counter, Gauge, Histogram

from portail.config import Reglages

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


def initialiser(r: Reglages) -> None:
    INFO.clear()  # ponytail: une seule version à la fois, même si l'application est recréée
    INFO.labels(version=r.version).set(1)
    DEPLOIEMENT.set(r.deploye_le)
    DUREE_MAX_TACHE.set(r.duree_max_tache_s)
