import re
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Reglages(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PORTAIL_")

    database_url: str
    litellm_url: str = "http://litellm:4000"
    litellm_cle: str = ""
    agents_fichier: Path = Path("agents.yaml")
    exiger_utilisateur: bool = False
    static_dir: Path | None = None
    github_jeton: str = ""
    donnees_dir: Path = Path("/donnees")
    lanceur_url: str = "http://lanceur:8080"
    lanceur_secret: str = ""
    espaces_dir: Path = Path("/espaces")
    github_app_id: str = ""
    github_app_cle: str = ""  # base64 du PEM
    paralleles_max: int = 1
    duree_max_tache_s: int = 7200
    delai_commande_s: int = 600
    renvois_max: int = 2
    github_proprietaire: str = ""
    ntfy_url: str = "http://ntfy"
    ntfy_sujet: str = "portail"
    ntfy_jeton: str = ""
    url_publique: str = ""
    resume_heure: str = "07:00"  # HH:MM à Toronto ; "" désactive le résumé du matin
    delai_commentaires_s: int = 600
    version: str = ""  # PORTAIL_VERSION : tag de l'image déployée
    duree_mission_s: int = 3600  # PORTAIL_DUREE_MISSION_S : durée de vie d'une mission en conteneur
    deploye_le: int = 0  # PORTAIL_DEPLOYE_LE : secondes Unix du déploiement

    @field_validator("resume_heure")
    @classmethod
    def _resume_heure(cls, v: str) -> str:
        if v and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError(f"PORTAIL_RESUME_HEURE doit être vide ou au format HH:MM, reçu {v!r}")
        return v
