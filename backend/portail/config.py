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
