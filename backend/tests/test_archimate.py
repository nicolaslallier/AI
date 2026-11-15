import io
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import xmlschema

from portail.archimate import (
    BlocInvalide,
    Element,
    Modele,
    Relation,
    Vue,
    catalogues_markdown,
    fusionner,
    lire_bloc,
    valider,
    valider_synthese,
    xml_echange,
)

MODELE = {
    "elements": [{"id": "app-portail", "type": "ApplicationComponent", "nom": "Portail"}],
    "relations": [{"type": "Serving", "source": "app-portail", "cible": "aff-rediger"}],
    "vues": [{"nom": "Coopération", "elements": ["app-portail", "aff-rediger"]}],
}
VOLET = f"Texte.\n\n```json\n{json.dumps(MODELE)}\n```\n"


def test_lire_bloc_rend_le_texte_et_le_modele():
    texte, m = lire_bloc(VOLET)
    assert texte.strip() == "Texte."
    assert m.elements[0].id == "app-portail"


def test_lire_bloc_prend_le_dernier_bloc():
    contenu = '```json\n{"elements":[]}\n```\nPuis :\n' + VOLET
    texte, m = lire_bloc(contenu)
    assert m.elements[0].id == "app-portail"
    assert '{"elements":[]}' in texte


@pytest.mark.parametrize(
    "contenu, message",
    [
        ("Pas de bloc.", "bloc de modèle absent"),
        ("```json\n{pas du json\n```", "JSON illisible"),
        ("```json\n[1]\n```", "un objet est attendu"),
        ('```json\n{"elements":[{"id":"app-a","type":"Node"}]}\n```', "elements.0.nom"),
    ],
)
def test_lire_bloc_refuse(contenu, message):
    with pytest.raises(BlocInvalide) as exc:
        lire_bloc(contenu)
    assert message in str(exc.value)


def modele(**modifs):
    """Le modèle du volet, avec des champs remplacés (copie profonde)."""
    return lire_bloc(f"```json\n{json.dumps({**json.loads(json.dumps(MODELE)), **modifs})}\n```")[1]


def test_valider_accepte_un_volet_qui_cite_un_volet_precedent():
    valider(lire_bloc(VOLET)[1], "app-", {"aff-rediger"})


def element(**champs):
    return {"id": "app-portail", "type": "ApplicationComponent", "nom": "Portail"} | champs


CAS = [
    (
        modele(elements=[element(type="Bidule")]),
        "app-",
        {"aff-rediger"},
        "type d'élément inconnu : Bidule",
    ),
    (
        modele(relations=[{"type": "Utilise", "source": "app-portail", "cible": "aff-rediger"}]),
        "app-",
        {"aff-rediger"},
        "type de relation inconnu : Utilise",
    ),
    (
        modele(elements=[element(id="tec-portail")]),
        "app-",
        {"aff-rediger"},
        "identifiant « tec-portail » : préfixe « app- » attendu",
    ),
    (
        modele(elements=[element(id="app-Portail X")]),
        "app-",
        {"aff-rediger"},
        "identifiant « app-Portail X » : minuscules, chiffres et tirets",
    ),
    (
        modele(elements=[element(), element()]),
        "app-",
        {"aff-rediger"},
        "identifiant en double : app-portail",
    ),
    (
        modele(),
        "app-",
        {"aff-rediger", "app-portail"},
        "identifiant déjà pris par une étape précédente",
    ),
    (modele(), "app-", set(), "relation : identifiant inconnu « aff-rediger »"),
    (
        modele(vues=[{"nom": "Coopération", "elements": ["app-rien"]}]),
        "app-",
        {"aff-rediger"},
        "vue « Coopération » : identifiant inconnu « app-rien »",
    ),
    (modele(vues=[]), "app-", {"aff-rediger"}, "au moins une vue est attendue"),
    (
        modele(vues=[{"nom": "Coopération", "elements": []}]),
        "app-",
        {"aff-rediger"},
        "vue « Coopération » vide",
    ),
    (
        modele(fusions=[{"garder": "app-portail", "retirer": "aff-rediger"}]),
        "app-",
        {"aff-rediger"},
        "fusions réservées à la synthèse",
    ),
]


@pytest.mark.parametrize("m, prefixe, connus, message", CAS, ids=[c[3] for c in CAS])
def test_valider_refuse(m, prefixe, connus, message):
    with pytest.raises(BlocInvalide) as exc:
        valider(m, prefixe, connus)
    assert message in str(exc.value)


def el(ident, nom=None):
    return {"id": ident, "type": "ApplicationComponent", "nom": nom or ident}


def bloc(elements=(), relations=(), vues=(), fusions=()):
    return Modele.model_validate(
        {
            "elements": [el(i) for i in elements],
            "relations": [{"type": "Serving", "source": s, "cible": c} for s, c in relations],
            "vues": [{"nom": n, "elements": list(ids)} for n, ids in vues],
            "fusions": [{"garder": g, "retirer": r} for g, r in fusions],
        }
    )


def test_fusionner_unit_les_blocs_dans_l_ordre():
    a = bloc(["app-b", "app-a"], vues=[("A", ["app-a"])])
    b = bloc(["tec-c"], vues=[("B", ["tec-c"])])
    m = fusionner([a, b], bloc(["ent-d"], vues=[("S", ["ent-d"])]))
    assert [e.id for e in m.elements] == ["app-b", "app-a", "tec-c", "ent-d"]
    assert [v.nom for v in m.vues] == ["A", "B", "S"]
    assert m.fusions == []


def test_fusionner_sans_synthese():
    m = fusionner([bloc(["app-a"], vues=[("A", ["app-a"])])], None)
    assert [e.id for e in m.elements] == ["app-a"]


def test_fusion_remplace_partout():
    a = bloc(["app-x", "app-y"], vues=[("V", ["app-x", "app-y"])])
    b = bloc(["tec-n"], relations=[("tec-n", "app-x")])
    m = fusionner([a, b], bloc(fusions=[("app-y", "app-x")]))
    assert [e.id for e in m.elements] == ["app-y", "tec-n"]
    assert [(r.source, r.cible) for r in m.relations] == [("tec-n", "app-y")]
    assert m.vues[0].elements == ["app-y"]
    assert m.fusions == []


def test_fusion_retire_relation_devenue_boucle_ou_doublon():
    a = bloc(
        ["app-x", "app-y", "tec-n"],
        relations=[("app-x", "app-y"), ("tec-n", "app-x"), ("tec-n", "app-y")],
        vues=[("V", ["tec-n"])],
    )
    m = fusionner([a], bloc(fusions=[("app-y", "app-x")]))
    assert [(r.source, r.cible) for r in m.relations] == [("tec-n", "app-y")]


def test_fusion_retire_une_vue_videe():
    a = bloc(["app-x"], vues=[("Pleine", ["app-x"]), ("Vide", [])])
    m = fusionner([a], None)
    assert [v.nom for v in m.vues] == ["Pleine"]


@pytest.mark.parametrize(
    "fusions, message",
    [
        ([("app-y", "app-inconnu")], "fusion : identifiant inconnu « app-inconnu »"),
        ([("app-y", "app-y")], "fusion : « app-y » ne peut pas se remplacer lui-même"),
        ([("app-y", "app-x"), ("app-z", "app-y")], "fusion : « app-y » est gardé et retiré"),
        ([("app-y", "app-x"), ("app-z", "app-x")], "fusion : « app-x » retiré deux fois"),
    ],
)
def test_valider_synthese_refuse(fusions, message):
    m = bloc(fusions=fusions, vues=[("S", ["app-y"])])
    with pytest.raises(BlocInvalide) as exc:
        valider_synthese(m, {"app-x", "app-y", "app-z"})
    assert message in str(exc.value)


def test_valider_synthese_refuse_un_ajout_mal_prefixe():
    m = bloc(["app-nouveau"], vues=[("S", ["app-nouveau"])])
    with pytest.raises(BlocInvalide) as exc:
        valider_synthese(m, set())
    assert "préfixe « ent- » attendu" in str(exc.value)


def test_valider_synthese_refuse_sans_vue():
    with pytest.raises(BlocInvalide) as exc:
        valider_synthese(bloc(["ent-a"]), set())
    assert "au moins une vue est attendue" in str(exc.value)


def test_valider_synthese_refuse_une_relation_inconnue():
    m = bloc(["ent-a"], relations=[("ent-a", "app-rien")], vues=[("S", ["ent-a"])])
    with pytest.raises(BlocInvalide) as exc:
        valider_synthese(m, set())
    assert "relation : identifiant inconnu « app-rien »" in str(exc.value)


def test_valider_synthese_accepte():
    m = bloc(
        ["ent-a"],
        relations=[("ent-a", "app-x")],
        vues=[("S", ["ent-a", "app-x"])],
        fusions=[("app-y", "app-x")],
    )
    valider_synthese(m, {"app-x", "app-y"})


def test_catalogues_markdown_nomme_le_volet_d_origine():
    m = Modele.model_validate(
        {
            "elements": [
                {"id": "app-portail", "type": "ApplicationComponent", "nom": "Portail"},
                {"id": "zzz-a", "type": "Node", "nom": "A|B"},
            ],
            "relations": [
                {"type": "Serving", "source": "app-portail", "cible": "zzz-a", "nom": "sert"}
            ],
            "vues": [{"nom": "Coop", "point_de_vue": "Cooperation", "elements": ["app-portail"]}],
        }
    )
    md = catalogues_markdown(m, {"app-": "applicatif"})
    assert "| app-portail | ApplicationComponent | Portail | applicatif |" in md
    assert "| zzz-a | Node | A\\|B |  |" in md
    assert "| app-portail | Serving | zzz-a | sert |" in md
    assert "| Coop | Cooperation | 1 |" in md


NS = {
    "a": "http://www.opengroup.org/xsd/archimate/3.0/",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
# Les XSD sont rangés dans le dépôt : `uri_mapper` redirige l'import réseau de xml.xsd vers la
# copie locale et `allow="local"` interdit tout accès réseau, la validation se fait hors ligne.
XSD = Path(__file__).parent / "xsd"
SCHEMA = xmlschema.XMLSchema(
    XSD / "archimate3_Diagram.xsd",
    uri_mapper={"http://www.w3.org/2001/xml.xsd": (XSD / "xml.xsd").as_uri()},
    allow="local",
)

MODELE_COMPLET = Modele(
    elements=[
        Element(id="mot-acteur", type="BusinessActor", nom="Équipe", description="Qui agit"),
        Element(id="mot-processus", type="BusinessProcess", nom="Rédiger"),
        Element(id="app-portail", type="ApplicationComponent", nom="Portail"),
        Element(id="app-donnees", type="DataObject", nom="Dossier"),
        Element(id="tec-noeud", type="Node", nom="Serveur"),
        Element(id="phy-usine", type="Facility", nom="Datacenter"),
        Element(id="str-ressource", type="Resource", nom="Budget"),
        Element(id="imp-projet", type="WorkPackage", nom="Lot 1"),
        Element(id="mot-exigence", type="Requirement", nom="Disponibilité"),
        Element(id="mot-bien", type="Value", nom="Confiance"),
    ],
    relations=[
        Relation(type="Assignment", source="mot-acteur", cible="mot-processus"),
        Relation(type="Serving", source="app-portail", cible="mot-processus", nom="sert"),
        Relation(type="Access", source="app-portail", cible="app-donnees"),
        Relation(type="Influence", source="mot-exigence", cible="mot-bien"),
        Relation(type="Realization", source="tec-noeud", cible="app-portail"),
    ],
    vues=[
        Vue(
            nom="Coopération",
            point_de_vue="Application Cooperation",
            elements=["mot-acteur", "mot-processus", "app-portail", "app-donnees"],
        ),
        Vue(nom="Technique", elements=["tec-noeud", "phy-usine", "app-portail"]),
    ],
)


def _racine(modele: Modele, nom: str = "Projet P") -> ET.Element:
    return ET.fromstring(xml_echange(modele, nom))


def test_xml_valide_contre_le_xsd():
    SCHEMA.validate(io.StringIO(xml_echange(MODELE_COMPLET, "Projet P")))


def test_xsd_rejette_un_document_casse():
    casse = xml_echange(MODELE_COMPLET, "Projet P").replace('relationshipRef="id-rel-1"', "")
    assert not SCHEMA.is_valid(io.StringIO(casse))


def test_xml_echappe_les_caracteres_speciaux():
    nom = 'R&D <cœur> "x"'
    m = Modele(
        elements=[Element(id="app-a", type="ApplicationComponent", nom=nom, description="a & <b>")],
        vues=[Vue(nom="V", elements=["app-a"])],
    )
    texte = xml_echange(m, nom)
    SCHEMA.validate(io.StringIO(texte))
    racine = ET.fromstring(texte)
    assert racine.find("a:name", NS).text == nom
    element = racine.find("a:elements/a:element", NS)
    assert element.find("a:name", NS).text == nom
    assert element.find("a:documentation", NS).text == "a & <b>"


def test_xml_decrit_elements_et_relations():
    racine = _racine(MODELE_COMPLET)
    elements = racine.findall("a:elements/a:element", NS)
    assert [e.get("identifier") for e in elements][:2] == ["id-mot-acteur", "id-mot-processus"]
    assert elements[0].get(XSI_TYPE) == "BusinessActor"
    assert elements[0].find("a:documentation", NS).text == "Qui agit"
    assert elements[1].find("a:documentation", NS) is None
    relations = racine.findall("a:relationships/a:relationship", NS)
    assert [r.get("identifier") for r in relations][:2] == ["id-rel-1", "id-rel-2"]
    assert relations[1].get(XSI_TYPE) == "Serving"
    assert relations[1].get("source") == "id-app-portail"
    assert relations[1].get("target") == "id-mot-processus"
    assert relations[1].find("a:name", NS).text == "sert"
    assert relations[0].find("a:name", NS) is None


def test_xml_une_vue_devient_un_diagramme_en_grille():
    ids = [f"app-e{i}" for i in range(5)]
    m = Modele(
        elements=[Element(id=i, type="ApplicationComponent", nom=i) for i in ids],
        vues=[Vue(nom="Grille", elements=ids)],
    )
    texte = xml_echange(m, "P")
    SCHEMA.validate(io.StringIO(texte))
    vue = ET.fromstring(texte).find("a:views/a:diagrams/a:view", NS)
    assert vue.get("identifier") == "id-vue-1"
    assert vue.get(XSI_TYPE) == "Diagram"
    noeuds = vue.findall("a:node", NS)
    assert len(noeuds) == 5
    assert noeuds[0].get("identifier") == "id-vue-1-n1"
    assert noeuds[0].get("elementRef") == "id-app-e0"
    assert (noeuds[3].get("x"), noeuds[3].get("y")) == ("640", "40")
    assert (noeuds[4].get("x"), noeuds[4].get("y")) == ("40", "140")
    assert (noeuds[4].get("w"), noeuds[4].get("h")) == ("160", "60")


def test_xml_ne_trace_que_les_relations_internes_a_la_vue():
    racine = _racine(MODELE_COMPLET)
    vues = racine.findall("a:views/a:diagrams/a:view", NS)
    # Coopération : relations 1, 2, 3 (Influence et Realization sortent de la vue)
    connexions = vues[0].findall("a:connection", NS)
    assert [c.get("relationshipRef") for c in connexions] == ["id-rel-1", "id-rel-2", "id-rel-3"]
    assert connexions[0].get("identifier") == "id-vue-1-c1"
    assert connexions[0].get("source") == "id-vue-1-n1"
    assert connexions[0].get("target") == "id-vue-1-n2"
    # Technique : seule Realization (tec-noeud -> app-portail)
    assert [c.get("relationshipRef") for c in vues[1].findall("a:connection", NS)] == ["id-rel-5"]


def test_xml_omet_un_point_de_vue_inconnu():
    racine = _racine(MODELE_COMPLET)
    vues = racine.findall("a:views/a:diagrams/a:view", NS)
    assert vues[0].get("viewpoint") == "Application Cooperation"
    assert vues[1].get("viewpoint") is None
    inconnu = MODELE_COMPLET.model_copy(
        update={"vues": [Vue(nom="X", point_de_vue="Inventé", elements=["app-portail"])]}
    )
    vue = _racine(inconnu).find("a:views/a:diagrams/a:view", NS)
    assert vue.get("viewpoint") is None


def test_xml_modele_sans_vue_ni_relation_reste_valide():
    m = Modele(elements=[Element(id="app-a", type="ApplicationComponent", nom="A")])
    texte = xml_echange(m, "P")
    SCHEMA.validate(io.StringIO(texte))
    racine = ET.fromstring(texte)
    assert racine.find("a:relationships", NS) is None
    assert racine.find("a:views", NS) is None
    vide = xml_echange(Modele(), "P")
    SCHEMA.validate(io.StringIO(vide))
