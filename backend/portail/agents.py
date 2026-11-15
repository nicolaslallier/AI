from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

OUTILS_SUIVI = ("en_attente_de_nicolas", "activite")
OUTILS_LECTURE_PORTAIL = (
    "lister_projets",
    "lire_projet",
    "lister_pipelines",
    "lire_pipeline",
    "lire_kanban",
) + OUTILS_SUIVI
# n'enregistrent qu'une proposition : l'action ne s'exécute que sur confirmation de Nicolas
OUTILS_ACTIONS_PORTAIL = (
    "creer_projet",
    "deposer_spec",
    "lancer_pipeline",
    "creer_tache",
    "modifier_tache",
    "deplacer_tache",
    "annuler_tache",
)
OUTILS_PORTAIL = OUTILS_LECTURE_PORTAIL + OUTILS_ACTIONS_PORTAIL


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
            "en_attente_de_nicolas",
            "activite",
            "creer_projet",
            "deposer_spec",
            "lancer_pipeline",
            "creer_tache",
            "modifier_tache",
            "deplacer_tache",
            "annuler_tache",
        ]
    ] = []
    tours_max: int = Field(default=20, gt=0)
    role: Literal["tests", "code", "revue", "doc"] | None = None
    modele_si_meme: str | None = None
    consigne_avis: str | None = None

    @model_validator(mode="after")
    def _coherent(self):
        if self.auto and not self.consigne_redaction:
            raise ValueError(f"l'agent « {self.nom} » est auto : consigne_redaction requise")
        portail = set(self.outils) & set(OUTILS_PORTAIL)
        if portail and portail != set(self.outils):
            raise ValueError(f"l'agent « {self.nom} » mélange outils du portail et outils de dépôt")
        if self.produit == "taches" and self.outils:
            raise ValueError(f"l'agent « {self.nom} » produit des tâches : pas d'outils")
        if self.modele_si_meme == self.modele:
            raise ValueError(f"l'agent « {self.nom} » : modele_si_meme doit différer de modele")
        if self.produit == "travail":
            if self.role is None or (self.role != "doc" and "lancer" not in self.outils):
                raise ValueError(
                    f"l'agent « {self.nom} » produit du travail : role et lancer requis"
                )
            if self.role == "doc" and "lancer" in self.outils:
                raise ValueError(f"l'agent « {self.nom} » est doc : pas de lancer")
        if self.produit == "verdict" and (
            self.role != "revue" or {"ecrire", "supprimer"} & set(self.outils)
        ):
            raise ValueError(
                f"l'agent « {self.nom} » produit un verdict : role revue, sans ecrire ni supprimer"
            )
        return self


def modele_pour(agent: Agent, auteur: Agent) -> str:
    """Le modèle de `agent` quand il conteste `auteur` : jamais le même que l'auteur, si possible."""
    if agent.modele == auteur.modele and agent.modele_si_meme:
        return agent.modele_si_meme
    return agent.modele


class Catalogue(BaseModel):
    modeles_permis: list[str] = []
    agents: dict[str, Agent]
    pipelines: dict[str, list[str]]
    avis: dict[Literal["spec", "plan"], list[str]] = {}


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
    permis = brut.get("modeles_permis")
    if not isinstance(permis, list) or not permis or not all(isinstance(m, str) for m in permis):
        raise CatalogueInvalide("`modeles_permis` doit être une liste non vide de noms de modèles")
    for nom, a in agents.items():
        for m in (a.modele, a.modele_si_meme):
            if m is not None and m not in permis:
                raise CatalogueInvalide(
                    f"agent « {nom} » : le modèle « {m} » n'est pas dans `modeles_permis`"
                )
    try:
        cat = Catalogue(
            modeles_permis=permis,
            agents=agents,
            pipelines=brut.get("pipelines") or {},
            avis=brut.get("avis") or {},
        )
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
            if set(cat.agents[a].outils) & set(OUTILS_PORTAIL):
                raise CatalogueInvalide(
                    f"pipeline « {p} » : l'agent « {a} » a des outils du portail"
                )
    for etape, noms in cat.avis.items():
        for a in noms:
            if a not in cat.agents:
                raise CatalogueInvalide(f"avis « {etape} » : agent inconnu « {a} »")
            if not cat.agents[a].consigne_avis:
                raise CatalogueInvalide(
                    f"avis « {etape} » : l'agent « {a} » n'a pas de consigne_avis"
                )
    pm = cat.agents.get("pm")
    if pm and set(pm.outils) & set(OUTILS_ACTIONS_PORTAIL):
        raise CatalogueInvalide("l'agent « pm » a des outils d'action du portail")
    return cat


def _details(e: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(map(str, x['loc']))} : {x['msg']}"
        + (f" (reçu « {x['input']} »)" if x["type"] == "literal_error" else "")
        for x in e.errors()
    )
