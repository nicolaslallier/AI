import json

import pytest

from portail.archimate import (
    BlocInvalide,
    Modele,
    catalogues_markdown,
    fusionner,
    lire_bloc,
    valider,
    valider_synthese,
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
