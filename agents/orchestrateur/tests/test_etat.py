import json

import pytest

from orchestrateur.etat import Etat, outils


@pytest.fixture
def etat(depot_git):
    return Etat(id="t1", demande="Faire X", depot=str(depot_git), branche="orchestrateur/t1", branche_depart="main")


def test_sauver_puis_charger(etat, depot_git):
    etat.definir_plan([{"titre": "A"}, {"titre": "B", "agent": "explorateur"}])
    etat.maj_tache(1, "en_cours")
    chemin = etat.sauver()
    assert chemin == depot_git / ".git" / "orchestrateur" / "t1.json"
    relu = Etat.charger(depot_git, "t1")
    assert relu.taches[0].statut == "en_cours" and relu.taches[0].essais == 1
    assert relu.taches[1].agent == "explorateur"
    assert json.loads(chemin.read_text())["demande"] == "Faire X"
    assert not chemin.with_suffix(".tmp").exists()


def test_etat_hors_arbre_de_travail(etat, depot_git):
    import subprocess

    etat.sauver()
    assert subprocess.run(["git", "-C", str(depot_git), "status", "--porcelain"], capture_output=True, text=True).stdout == ""


def test_essais_comptes(etat):
    etat.definir_plan([{"titre": "A"}])
    for _ in range(3):
        etat.maj_tache(1, "en_cours")
        etat.maj_tache(1, "echec", "tests en échec")
    assert etat.taches[0].essais == 3
    assert "[echec]" in etat.resume() and "tests en échec" in etat.resume()


@pytest.mark.parametrize(
    "taches, message",
    [([], "au moins"), ([{"titre": " "}], "vide"), ([{"titre": "x"}] * 13, "12")],
)
def test_plan_refuse(etat, taches, message):
    with pytest.raises(ValueError, match=message):
        etat.definir_plan(taches)


def test_maj_refusee(etat):
    with pytest.raises(ValueError, match="inconnue"):
        etat.maj_tache(1, "faite")
    etat.definir_plan([{"titre": "A"}])
    with pytest.raises(ValueError, match="statut inconnu"):
        etat.maj_tache(1, "fini")


def outil(etat, nom):
    return next(t for t in outils(etat) if t.name == nom)


async def test_outils_mcp(etat):
    r = await outil(etat, "plan_definir").handler({"taches": [{"titre": "A"}, {"titre": "B"}]})
    assert "is_error" not in r and "1. [a_faire] A" in r["content"][0]["text"]
    r = await outil(etat, "tache_maj").handler({"id": 2, "statut": "faite", "resultat": "ok"})
    assert "2. [faite] B" in r["content"][0]["text"]
    r = await outil(etat, "etat_lire").handler({})
    assert "[faite] B" in r["content"][0]["text"]


async def test_outils_mcp_erreurs_rendues_au_modele(etat):
    r = await outil(etat, "tache_maj").handler({"id": 9, "statut": "faite"})
    assert r["is_error"] is True and "inconnue" in r["content"][0]["text"]
    r = await outil(etat, "plan_definir").handler({})
    assert r["is_error"] is True


def test_annotations_lecture_seule(etat):
    assert "Lecture seule" in outil(etat, "etat_lire").description
    assert "rien dans le dépôt" in outil(etat, "tache_maj").description
