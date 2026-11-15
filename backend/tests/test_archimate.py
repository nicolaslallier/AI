import json

import pytest

from portail.archimate import BlocInvalide, lire_bloc, valider

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
