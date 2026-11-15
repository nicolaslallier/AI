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


def initialiser(r: Reglages) -> None:
    INFO.clear()  # ponytail: une seule version à la fois, même si l'application est recréée
    INFO.labels(version=r.version).set(1)
    DEPLOIEMENT.set(r.deploye_le)
    DUREE_MAX_TACHE.set(r.duree_max_tache_s)
