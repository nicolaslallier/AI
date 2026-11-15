"""Contrat `v1` entre le portail et les agents en conteneur (voir docs/agents-contrat-v1.md).

Les demandes venues d'un agent sont en `extra="forbid"` : le portail n'y lit que ce qu'il
autorise (messages, drapeau `outils`, `response_format`, `flux`, nom et arguments d'un outil).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

CONTRAT = "v1"


class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MessageLLM(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None


class ParametresAgent(BaseModel):
    modele: str
    temperature: float | None = None
    contexte_max: int
    tours_max: int
    produit: str
    role: str | None = None


class DemandeMission(BaseModel):
    contrat: Literal["v1"]
    mission: str
    agent: str
    jeton: str
    messages: list[MessageLLM]
    outils: list[dict]
    parametres: ParametresAgent
    response_format: dict | None = None
    flux: bool = False


class LigneTexte(BaseModel):
    type: Literal["texte"]
    texte: str


class LigneFin(BaseModel):
    type: Literal["fin"]
    texte: str
    messages: list[MessageLLM]
    limite_atteinte: bool


class LigneErreur(BaseModel):
    type: Literal["erreur"]
    erreur: str


LigneMission = Annotated[LigneTexte | LigneFin | LigneErreur, Field(discriminator="type")]


class DemandeModele(_Forbid):
    messages: list[MessageLLM]
    outils: bool = False
    response_format: dict | None = None
    flux: bool = False


class ReponseModele(BaseModel):
    message: MessageLLM


class DemandeOutil(_Forbid):
    nom: str
    arguments: str  # JSON en chaîne, comme OpenAI


class ReponseOutil(BaseModel):
    resultat: str
    arret: bool = False


class Sante(BaseModel):
    contrat: str
    agent: str
    version: str
