"""Métriques Prometheus : identifiants, noms et compteurs seulement, jamais de contenu."""

from prometheus_client import Gauge

from portail.config import Reglages

INFO = Gauge("portail_info", "Version du portail déployée", ["version"])
DEPLOIEMENT = Gauge("portail_deploiement_horodatage_secondes", "Instant du déploiement (Unix)")
DUREE_MAX_TACHE = Gauge("portail_duree_max_tache_secondes", "Durée maximale d'une tâche")


def initialiser(r: Reglages) -> None:
    INFO.clear()  # ponytail: une seule version à la fois, même si l'application est recréée
    INFO.labels(version=r.version).set(1)
    DEPLOIEMENT.set(r.deploye_le)
    DUREE_MAX_TACHE.set(r.duree_max_tache_s)
