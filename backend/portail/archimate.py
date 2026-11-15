import json
import re

from pydantic import BaseModel, ValidationError

from portail.archimate_types import ELEMENTS, RELATIONS

BLOC = re.compile(r"```json[ \t]*\n(.*?)\n```", re.DOTALL)


class BlocInvalide(ValueError):
    pass


class Element(BaseModel):
    id: str
    type: str
    nom: str
    description: str = ""


class Relation(BaseModel):
    type: str
    source: str
    cible: str
    nom: str = ""


class Vue(BaseModel):
    nom: str
    point_de_vue: str = ""
    elements: list[str]


class Fusion(BaseModel):
    garder: str
    retirer: str


class Modele(BaseModel):
    elements: list[Element] = []
    relations: list[Relation] = []
    vues: list[Vue] = []
    fusions: list[Fusion] = []


def lire_bloc(contenu: str) -> tuple[str, Modele]:
    """Le dernier bloc ```json du contenu : (texte sans le bloc, modèle)."""
    blocs = list(BLOC.finditer(contenu))
    if not blocs:
        raise BlocInvalide("bloc de modèle absent")
    dernier = blocs[-1]
    try:
        brut = json.loads(dernier.group(1))
    except json.JSONDecodeError as e:
        raise BlocInvalide(f"JSON illisible : {e}") from e
    if not isinstance(brut, dict):
        raise BlocInvalide("un objet est attendu")
    try:
        modele = Modele.model_validate(brut)
    except ValidationError as e:
        erreur = e.errors()[0]
        chemin = ".".join(str(p) for p in erreur["loc"])
        raise BlocInvalide(f"{chemin} : {erreur['msg']}") from e
    return contenu[: dernier.start()] + contenu[dernier.end() :], modele


def valider(modele: Modele, prefixe: str, connus: set[str]) -> None:
    """Lève BlocInvalide à la première erreur ; `connus` : identifiants des étapes précédentes."""
    if modele.fusions:
        raise BlocInvalide("fusions réservées à la synthèse")
    forme = re.compile(rf"^{re.escape(prefixe)}[a-z0-9]+(-[a-z0-9]+)*$")
    propres: set[str] = set()
    for e in modele.elements:
        if e.type not in ELEMENTS:
            raise BlocInvalide(f"type d'élément inconnu : {e.type}")
        if not e.id.startswith(prefixe):
            raise BlocInvalide(f"identifiant « {e.id} » : préfixe « {prefixe} » attendu")
        if not forme.match(e.id):
            raise BlocInvalide(f"identifiant « {e.id} » : minuscules, chiffres et tirets")
        if e.id in propres:
            raise BlocInvalide(f"identifiant en double : {e.id}")
        if e.id in connus:
            raise BlocInvalide(f"identifiant déjà pris par une étape précédente : {e.id}")
        propres.add(e.id)
    citables = propres | connus
    for r in modele.relations:
        if r.type not in RELATIONS:
            raise BlocInvalide(f"type de relation inconnu : {r.type}")
        for ident in (r.source, r.cible):
            if ident not in citables:
                raise BlocInvalide(f"relation : identifiant inconnu « {ident} »")
    if not modele.vues:
        raise BlocInvalide("au moins une vue est attendue")
    for v in modele.vues:
        if not v.elements:
            raise BlocInvalide(f"vue « {v.nom} » vide")
        for ident in v.elements:
            if ident not in citables:
                raise BlocInvalide(f"vue « {v.nom} » : identifiant inconnu « {ident} »")
