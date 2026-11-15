import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from portail.contexte import Jauge
from portail.moteur import Refus

DEPOT_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?(\.git)?$")

# identifiant venu d'un agent : borné à un INTEGER Postgres, sans coercition (ni bool, ni str)
Id = Annotated[int, Field(strict=True, ge=1, le=2**31 - 1)]


def verifier_depot(url: str | None) -> None:
    if url is not None and not DEPOT_RE.fullmatch(url):
        raise Refus(422, "URL de dépôt GitHub invalide")


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


class ExecutionIn(BaseModel):
    yaml: str


class ProjetDetail(ProjetOut):
    config_execution: str | None = None
    pipelines: list[PipelineResume]
    spec_courante: SpecCourante | None


class PipelineIn(BaseModel):
    projet_id: int
    type: str


class MessageOut(BaseModel):
    id: int
    role: str
    contenu: str
    outil: str | None
    cree_le: datetime


class ConversationIn(BaseModel):
    agent: str = "orchestrateur"


class ConversationResume(BaseModel):
    id: int
    agent: str
    titre: str
    etat: str
    maj_le: datetime


class ActionOut(BaseModel):
    id: int
    nom: str
    parametres: dict
    etat: str
    resultat: str | None
    lien: str | None
    cree_le: datetime


class ConversationDetail(BaseModel):
    id: int
    agent: str
    titre: str
    etat: str
    erreur: str | None
    messages: list[MessageOut]
    actions: list[ActionOut]
    jauge: Jauge | None  # None si l'agent manque au catalogue


class ConversationPatch(BaseModel):
    titre: str = Field(max_length=200)


class AvisOut(BaseModel):
    id: int
    agent: str
    contenu: str
    etat: str
    version: int
    ancienne: bool = False


class DocumentOut(BaseModel):
    id: int
    contenu: str
    etat: str
    version: int
    maj_le: datetime
    avis: list[AvisOut] = []


class EtapeOut(BaseModel):
    id: int
    ordre: int
    agent: str
    etat: str
    erreur: str | None
    action: str | None
    sha: str | None
    produit: str | None
    modele: str | None
    modele_fige: bool
    modeles: list[str]
    messages: list[MessageOut]
    document: DocumentOut | None
    jauge: Jauge | None


class ProjetRef(BaseModel):
    id: int
    nom: str


class ExecutionVue(BaseModel):
    branche: str
    phase: str
    renvois: int
    pr_url: str | None
    mode: str
    notes: list[dict] = []


class CommentaireVue(BaseModel):
    id: int
    type: str
    auteur: str
    texte: str
    url: str
    chemin: str | None
    ligne: int | None
    tri: str | None
    consigne: str | None
    repondu_le: datetime | None


class CommandeVue(BaseModel):
    etape_id: int
    nom: str
    code: int | None
    delai_depasse: bool
    sortie: str
    debut: datetime
    fin: datetime


class PipelineDetail(BaseModel):
    id: int
    projet: ProjetRef
    type: str
    etat: str
    maj_le: datetime
    etapes: list[EtapeOut]
    execution: ExecutionVue | None = None
    commandes: list[CommandeVue] = []
    commentaires: list[CommentaireVue] = []


COLONNES = ("a_faire", "prete", "en_cours", "en_revue", "terminee", "bloquee")


def _titre_valide(v: str | None) -> str | None:
    if v is None:
        raise ValueError("le titre ne peut pas être nul")
    v = v.strip()
    if not 1 <= len(v) <= 200:
        raise ValueError("le titre doit faire de 1 à 200 caractères")
    return v


class DonneesTache(BaseModel):
    titre: str
    description: str = ""
    criteres: list[str] = []
    fichiers: list[str] = []
    depend_de: list[int] = []

    _titre = field_validator("titre")(_titre_valide)


class DonneesTachePartielles(BaseModel):
    titre: str | None = None
    description: str | None = None
    criteres: list[str] | None = None
    fichiers: list[str] | None = None
    depend_de: list[int] | None = None

    _titre = field_validator("titre")(_titre_valide)

    @field_validator("description", "criteres", "fichiers", "depend_de")
    @classmethod
    def _pas_nul(cls, v):
        if v is None:
            raise ValueError("valeur nulle interdite")
        return v


class TacheVue(BaseModel):
    id: int
    projet_id: int
    titre: str
    description: str
    criteres: list[str]
    fichiers: list[str]
    colonne: str
    rang: int
    origine: str
    document_id: int | None
    protegee: bool
    verrou: int | None
    version: int
    cree_le: datetime
    maj_le: datetime
    depend_de: list[int] = []
    dependances_non_terminees: list[int] = []
    pr_url: str | None = None
    resume_blocage: str | None = None
    reprise: bool = False


class PropositionVue(BaseModel):
    id: int
    pipeline_id: int
    etape_id: int
    projet_id: int
    sorte: str
    cle: str | None
    tache_id: int | None
    version_tache: int | None
    donnees: dict
    etat: str
    tache_creee_id: int | None
    cree_le: datetime


class Kanban(BaseModel):
    config_execution: bool = False
    taches: list[TacheVue]
    propositions: list[PropositionVue]


class KanbanToutAccepte(Kanban):
    perimees: int


class Acceptation(BaseModel):
    donnees: DonneesTache | None = None


class Deplacement(BaseModel):
    colonne: str
    avant_id: int | None = None

    @field_validator("colonne")
    @classmethod
    def _colonne(cls, v):
        if v not in COLONNES:
            raise ValueError("colonne inconnue")
        return v


class AuditOut(BaseModel):
    id: int
    quand: datetime
    auteur: str
    action: str
    objet: str
    objet_id: int


class Travail(BaseModel):
    sorte: Literal["etape", "conversation", "avis"]
    etat: Literal["au_travail", "en_attente", "en_erreur"]
    libelle: str  # fait d'identifiants : jamais de titre ni de texte d'erreur
    lien: str
    tour: int | None = None
    jauge: Jauge | None = None


class ConteneurVue(BaseModel):
    """Le conteneur d'un agent : répond-il, et quelle version (validée, jamais l'adresse)."""

    repond: bool
    version: str | None


class Poste(BaseModel):
    nom: str
    etat: Literal["libre", "au_travail", "en_attente", "en_erreur"]
    travaux: list[Travail]
    appels_jour: int = 0
    jetons_jour: int = 0
    conteneur: ConteneurVue | None = None  # None : l'agent tourne dans le portail


class Groupe(BaseModel):
    nom: str | None  # None : agents hors pipeline
    agents: list[str]


class Bureau(BaseModel):
    groupes: list[Groupe]
    postes: dict[str, Poste]


class MissionOut(BaseModel):
    mission: str
    debut: datetime
    duree_ms: int
    appels: int
    jetons_entree: int
    jetons_sortie: int
    issue: str  # ok | erreur | delai
    libelle: str | None  # fait d'identifiants, comme `Travail.libelle`
    lien: str | None


class PosteDetail(BaseModel):
    """Ce que le catalogue dit d'un poste, et ses dernières missions. Aucun prompt ni consigne."""

    nom: str
    description: str
    modele: str
    modele_si_meme: str | None
    outils: list[str]
    tours_max: int
    contexte_max: int
    missions: list[MissionOut]
