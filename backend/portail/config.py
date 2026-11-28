import ipaddress
import re
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Reglages(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PORTAIL_")

    database_url: str
    litellm_url: str = "http://litellm:4000"
    litellm_cle: str = ""
    # PORTAIL_LITELLM_CLE_AGENTS : clé de l'équipe `agents` (modèles locaux) pour les agents A2A ;
    # vide : repli sur litellm_cle
    litellm_cle_agents: str = ""
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
    paralleles_max: int = Field(default=1, ge=1)  # pipelines (dev + doc) menés en même temps
    # appels simultanés par modèle local : un par machine qui le sert derrière LiteLLM
    appels_par_modele: int = Field(default=1, ge=1)
    duree_max_tache_s: int = 7200
    delai_commande_s: int = 600
    renvois_max: int = 2
    github_proprietaire: str = ""
    ntfy_url: str = "http://ntfy"
    ntfy_sujet: str = "portail"
    ntfy_jeton: str = ""
    url_publique: str = ""
    jeton_service: str = ""  # PORTAIL_JETON_SERVICE : route /service/ ; vide : 503
    resume_heure: str = "07:00"  # HH:MM à Toronto ; "" désactive le résumé du matin
    delai_commentaires_s: int = 600
    version: str = ""  # PORTAIL_VERSION : tag de l'image déployée
    duree_mission_s: int = Field(
        default=3600, gt=0
    )  # PORTAIL_DUREE_MISSION_S : durée de vie d'une mission en conteneur
    reseau_agents: str = (
        ""  # PORTAIL_RESEAU_AGENTS : CIDR du réseau des agents ; vide : aucun filtrage
    )
    llm_delai_s: int = Field(
        default=440, gt=0, lt=450
    )  # PORTAIL_LLM_DELAI_S : délai de lecture LiteLLM ; 2 essais < 900, DELAI_LECTURE de l'agent.
    # Couvre le timeout du MacBook (120 s, ordre 1 dans Infra litellm/config.yaml) + la reprise sur le Studio.
    s3_url: str = "http://s3:8333"
    s3_bucket: str = "obsidian"
    s3_access_key: str = "portail"
    s3_secret_key: str = ""  # PORTAIL_S3_SECRET_KEY ; vide : coffre Obsidian éteint
    coffre_prefixe: str = ""  # PORTAIL_COFFRE_PREFIXE = ORGANIZER_VAULT_PREFIX d'Infra
    deploye_le: int = 0  # PORTAIL_DEPLOYE_LE : secondes Unix du déploiement

    @field_validator("reseau_agents")
    @classmethod
    def _reseau_agents(cls, v: str) -> str:
        if v:
            try:
                ipaddress.ip_network(v)
            except ValueError:
                raise ValueError("PORTAIL_RESEAU_AGENTS doit être vide ou un réseau CIDR") from None
        return v

    @field_validator("resume_heure")
    @classmethod
    def _resume_heure(cls, v: str) -> str:
        if v and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError(f"PORTAIL_RESUME_HEURE doit être vide ou au format HH:MM, reçu {v!r}")
        return v
