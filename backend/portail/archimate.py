import json
import re
import xml.etree.ElementTree as ET

from pydantic import BaseModel, ValidationError

from portail.archimate_types import ELEMENTS, POINTS_DE_VUE, RELATIONS

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


_NS = "http://www.opengroup.org/xsd/archimate/3.0/"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
ET.register_namespace("", _NS)
ET.register_namespace("xsi", _XSI)


def _noeud(parent: ET.Element, balise: str, type_: str, ident: str, **attrs: str) -> ET.Element:
    return ET.SubElement(
        parent, f"{{{_NS}}}{balise}", {"identifier": ident, f"{{{_XSI}}}type": type_, **attrs}
    )


# Caractères interdits en XML 1.0 (tabulation, saut de ligne et retour chariot sont permis).
_INTERDITS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _texte(parent: ET.Element, balise: str, texte: str) -> None:
    ET.SubElement(parent, f"{{{_NS}}}{balise}", {_LANG: "fr"}).text = _INTERDITS.sub("", texte)


def xml_echange(modele: Modele, nom: str) -> str:
    """Fichier d'échange ArchiMate 3 (Open Group) : éléments, relations, un diagramme par vue."""
    racine = ET.Element(f"{{{_NS}}}model", {"identifier": "id-modele"})
    _texte(racine, "name", nom)
    if modele.elements:
        conteneur = ET.SubElement(racine, f"{{{_NS}}}elements")
        for e in modele.elements:
            noeud = _noeud(conteneur, "element", e.type, f"id-{e.id}")
            _texte(noeud, "name", e.nom)
            if e.description:
                _texte(noeud, "documentation", e.description)
    if modele.relations:
        conteneur = ET.SubElement(racine, f"{{{_NS}}}relationships")
        for n, r in enumerate(modele.relations, 1):
            noeud = _noeud(
                conteneur,
                "relationship",
                r.type,
                f"id-rel-{n}",
                source=f"id-{r.source}",
                target=f"id-{r.cible}",
            )
            if r.nom:
                _texte(noeud, "name", r.nom)
    if modele.vues:
        diagrammes = ET.SubElement(ET.SubElement(racine, f"{{{_NS}}}views"), f"{{{_NS}}}diagrams")
        for n, v in enumerate(modele.vues, 1):
            attrs = {"viewpoint": v.point_de_vue} if v.point_de_vue in POINTS_DE_VUE else {}
            vue = _noeud(diagrammes, "view", "Diagram", f"id-vue-{n}", **attrs)
            _texte(vue, "name", v.nom)
            noeuds: dict[str, str] = {}
            for k, ident in enumerate(dict.fromkeys(v.elements)):
                noeuds[ident] = f"id-vue-{n}-n{k + 1}"
                _noeud(
                    vue,
                    "node",
                    "Element",
                    noeuds[ident],
                    elementRef=f"id-{ident}",
                    x=str(40 + 200 * (k % 4)),
                    y=str(40 + 100 * (k // 4)),
                    w="160",
                    h="60",
                )
            internes = [
                (i, r)
                for i, r in enumerate(modele.relations, 1)
                if {r.source, r.cible} <= noeuds.keys()
            ]
            for c, (i, r) in enumerate(internes, 1):
                _noeud(
                    vue,
                    "connection",
                    "Relationship",
                    f"id-vue-{n}-c{c}",
                    relationshipRef=f"id-rel-{i}",
                    source=noeuds[r.source],
                    target=noeuds[r.cible],
                )
    ET.indent(racine)
    corps = ET.tostring(racine, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{corps}\n'
