from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError


class CatalogueInvalide(Exception):
    pass


class Agent(BaseModel):
    nom: str
    description: str
    modele: str
    prompt_systeme: str
    contexte_max: int = Field(gt=0)
    temperature: float | None = None
    consigne_redaction: str | None = None


class Catalogue(BaseModel):
    agents: dict[str, Agent]
    pipelines: dict[str, list[str]]


def charger_catalogue(chemin: Path) -> Catalogue:
    try:
        brut = yaml.safe_load(Path(chemin).read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as e:
        raise CatalogueInvalide(f"{chemin} illisible : {e}") from e
    if not isinstance(brut, dict):
        raise CatalogueInvalide(f"{chemin} : un dictionnaire est attendu")
    brut_agents = brut.get("agents") or {}
    if not isinstance(brut_agents, dict):
        raise CatalogueInvalide("`agents` doit être un dictionnaire")
    agents = {}
    for nom, a in brut_agents.items():
        if not isinstance(a, dict) or "nom" in a:
            raise CatalogueInvalide(
                f"agent « {nom} » invalide : un dictionnaire sans clé `nom` est attendu"
            )
        try:
            agents[nom] = Agent(nom=nom, **a)
        except ValidationError as e:
            raise CatalogueInvalide(f"agent « {nom} » invalide ({_details(e)})") from e
    try:
        cat = Catalogue(agents=agents, pipelines=brut.get("pipelines") or {})
    except ValidationError as e:
        raise CatalogueInvalide(f"`pipelines` invalide ({_details(e)})") from e
    for p, etapes in cat.pipelines.items():
        if not etapes:
            raise CatalogueInvalide(f"pipeline « {p} » vide")
        for a in etapes:
            if a not in cat.agents:
                raise CatalogueInvalide(f"pipeline « {p} » : agent inconnu « {a} »")
    return cat


def _details(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, x['loc']))} : {x['msg']}" for x in e.errors())
