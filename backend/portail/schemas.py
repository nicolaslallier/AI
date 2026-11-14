from datetime import datetime

from pydantic import BaseModel, field_validator

from portail.contexte import Jauge


class ProjetIn(BaseModel):
    nom: str
    description: str = ""

    @field_validator("nom")
    @classmethod
    def _nom(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 200:
            raise ValueError("le nom doit faire de 1 à 200 caractères")
        return v


class ProjetOut(BaseModel):
    id: int
    nom: str
    description: str
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
    jauge: Jauge


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
