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


def valider_synthese(modele: Modele, connus: set[str]) -> None:
    """Règles de l'étape 8 : ajouts préfixés `ent-`, fusions entre éléments `connus`."""
    valider(modele.model_copy(update={"fusions": []}), "ent-", connus)
    gardes: set[str] = set()
    retires: set[str] = set()
    for f in modele.fusions:
        for ident in (f.garder, f.retirer):
            if ident not in connus:
                raise BlocInvalide(f"fusion : identifiant inconnu « {ident} »")
        if f.garder == f.retirer:
            raise BlocInvalide(f"fusion : « {f.garder} » ne peut pas se remplacer lui-même")
        if f.retirer in retires:
            raise BlocInvalide(f"fusion : « {f.retirer} » retiré deux fois")
        retires.add(f.retirer)
        gardes.add(f.garder)
    if conflit := sorted(gardes & retires):
        raise BlocInvalide(f"fusion : « {conflit[0]} » est gardé et retiré")


def fusionner(blocs: list[Modele], synthese: Modele | None) -> Modele:
    """Union des blocs, ajouts de la synthèse, puis fusions appliquées."""
    tous = [*blocs, *([synthese] if synthese else [])]
    remplace = {f.retirer: f.garder for m in tous for f in m.fusions}

    def nouveau(ident: str) -> str:
        return remplace.get(ident, ident)

    elements = [e for m in tous for e in m.elements if e.id not in remplace]
    relations: list[Relation] = []
    vues: list[Vue] = []
    vus: set[tuple[str, str, str]] = set()
    for m in tous:
        for r in m.relations:
            s, c = nouveau(r.source), nouveau(r.cible)
            if s != c and (r.type, s, c) not in vus:
                vus.add((r.type, s, c))
                relations.append(r.model_copy(update={"source": s, "cible": c}))
        for v in m.vues:
            ids = list(dict.fromkeys(nouveau(i) for i in v.elements))
            if ids:
                vues.append(v.model_copy(update={"elements": ids}))
    return Modele(elements=elements, relations=relations, vues=vues)


def _ligne(*cellules: str) -> str:
    return "| " + " | ".join(c.replace("|", "\\|") for c in cellules) + " |"


def catalogues_markdown(modele: Modele, origine: dict[str, str]) -> str:
    """Les éléments, relations et vues en trois tableaux markdown ; `origine` : préfixe → volet."""

    def volet(ident: str) -> str:
        return next((n for p, n in origine.items() if ident.startswith(p)), "")

    lignes = [
        _ligne("Identifiant", "Type", "Nom", "Volet d'origine"),
        _ligne("---", "---", "---", "---"),
        *(_ligne(e.id, e.type, e.nom, volet(e.id)) for e in modele.elements),
        "",
        _ligne("Source", "Relation", "Cible", "Note"),
        _ligne("---", "---", "---", "---"),
        *(_ligne(r.source, r.type, r.cible, r.nom) for r in modele.relations),
        "",
        _ligne("Vue", "Point de vue", "Éléments"),
        _ligne("---", "---", "---"),
        *(_ligne(v.nom, v.point_de_vue, str(len(v.elements))) for v in modele.vues),
    ]
    return "\n".join(lignes) + "\n"
