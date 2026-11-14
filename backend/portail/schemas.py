import re
from datetime import datetime

from pydantic import BaseModel, field_validator

from portail.contexte import Jauge

DEPOT_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?(\.git)?$")


def _nom_valide(v: str | None) -> str:
    if v is None:
        raise ValueError("le nom est obligatoire")
    v = v.strip()
    if not 1 <= len(v) <= 200:
        raise ValueError("le nom doit faire de 1 à 200 caractères")
    return v


class ProjetIn(BaseModel):
    nom: str
    description: str = ""
    depot_url: str | None = None
    branche_ref: str | None = None

    _nom = field_validator("nom")(_nom_valide)


class ProjetPatch(BaseModel):
    """Mise à jour partielle : un champ absent est intact, un null explicite l'efface."""

    nom: str | None = None
    description: str | None = None
    depot_url: str | None = None
    branche_ref: str | None = None

    _nom = field_validator("nom")(_nom_valide)

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        if v is None:
            raise ValueError("la description ne peut pas être nulle")
        return v


class ProjetOut(BaseModel):
    id: int
    nom: str
    description: str
    depot_url: str | None
    branche_ref: str | None
    cree_le: datetime


class PipelineResume(BaseModel):
    id: int
    projet_id: int
    projet_nom: str
    type: str
    etat: str
    maj_le: datetime


class SpecCourante(BaseModel):
    id: int
    contenu: str
    maj_le: datetime


class ProjetDetail(ProjetOut):
    pipelines: list[PipelineResume]
    spec_courante: SpecCourante | None


class PipelineIn(BaseModel):
    projet_id: int
    type: str


class MessageOut(BaseModel):
    id: int
    role: str
    contenu: str
    cree_le: datetime


class DocumentOut(BaseModel):
    id: int
    contenu: str
    etat: str
    maj_le: datetime


class EtapeOut(BaseModel):
    id: int
    ordre: int
    agent: str
    etat: str
    erreur: str | None
    action: str | None
    messages: list[MessageOut]
    document: DocumentOut | None
    jauge: Jauge | None


class ProjetRef(BaseModel):
    id: int
    nom: str


class PipelineDetail(BaseModel):
    id: int
    projet: ProjetRef
    type: str
    etat: str
    maj_le: datetime
    etapes: list[EtapeOut]
