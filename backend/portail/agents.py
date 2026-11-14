from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

OUTILS_LECTURE_PORTAIL = (
    "lister_projets",
    "lire_projet",
    "lister_pipelines",
    "lire_pipeline",
    "lire_kanban",
)


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
    produit: Literal["spec", "plan", "taches", "travail", "verdict"] = "spec"
    auto: bool = False
    outils: list[
        Literal[
            "lister",
            "lire",
            "chercher",
            "ecrire",
            "supprimer",
            "lancer",
            "lister_projets",
            "lire_projet",
            "lister_pipelines",
            "lire_pipeline",
            "lire_kanban",
        ]
    ] = []
    tours_max: int = Field(default=20, gt=0)
    role: Literal["tests", "code", "revue"] | None = None

    @model_validator(mode="after")
    def _coherent(self):
        if self.auto and not self.consigne_redaction:
            raise ValueError(f"l'agent « {self.nom} » est auto : consigne_redaction requise")
        portail = set(self.outils) & set(OUTILS_LECTURE_PORTAIL)
        if portail and portail != set(self.outils):
            raise ValueError(f"l'agent « {self.nom} » mélange outils du portail et outils de dépôt")
        if self.produit == "taches" and self.outils:
            raise ValueError(f"l'agent « {self.nom} » produit des tâches : pas d'outils")
        if self.produit == "travail" and (self.role is None or "lancer" not in self.outils):
            raise ValueError(f"l'agent « {self.nom} » produit du travail : role et lancer requis")
        if self.produit == "verdict" and (
            self.role != "revue" or {"ecrire", "supprimer", "lancer"} & set(self.outils)
        ):
            raise ValueError(
                f"l'agent « {self.nom} » produit un verdict : role revue, sans ecrire, "
                "supprimer ni lancer"
            )
        return self


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
    for p, etapes in cat.pipelines.items():
        for a in etapes:
            if set(cat.agents[a].outils) & set(OUTILS_LECTURE_PORTAIL):
                raise CatalogueInvalide(
                    f"pipeline « {p} » : l'agent « {a} » a des outils du portail"
                )
    return cat


def _details(e: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(map(str, x['loc']))} : {x['msg']}"
        + (f" (reçu « {x['input']} »)" if x["type"] == "literal_error" else "")
        for x in e.errors()
    )
