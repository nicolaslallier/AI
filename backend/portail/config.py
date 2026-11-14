from pathlib import Path

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
