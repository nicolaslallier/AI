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
    agents = brut.get("agents") or {}
    if not isinstance(agents, dict):
        raise CatalogueInvalide("`agents` doit être un dictionnaire")
    try:
        cat = Catalogue(
            agents={
                n: Agent(nom=n, **(a if isinstance(a, dict) else {})) for n, a in agents.items()
            },
            pipelines=brut.get("pipelines") or {},
        )
    except ValidationError as e:
        details = "; ".join(f"{'.'.join(map(str, x['loc']))} : {x['msg']}" for x in e.errors())
        # loc ne contient pas le nom de l agent : on le retrouve en revalidant
        nom = next((n for n, a in agents.items() if _invalide(n, a)), "?")
        raise CatalogueInvalide(f"agent « {nom} » invalide ({details})") from e
    for p, etapes in cat.pipelines.items():
        if not etapes:
            raise CatalogueInvalide(f"pipeline « {p} » vide")
        for a in etapes:
            if a not in cat.agents:
                raise CatalogueInvalide(f"pipeline « {p} » : agent inconnu « {a} »")
    return cat


def _invalide(nom: str, a: object) -> bool:
    try:
        Agent(nom=nom, **(a if isinstance(a, dict) else {}))
    except ValidationError:
        return True
    return False
