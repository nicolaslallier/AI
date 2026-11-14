from pathlib import Path

import pytest

from portail.agents import CatalogueInvalide, charger_catalogue

VALIDE = """
agents:
  spec:
    description: d
    modele: m
    contexte_max: 1000
    temperature: 0.3
    prompt_systeme: p
pipelines:
  spec: [spec]
"""


def ecrire(tmp_path: Path, texte: str) -> Path:
    f = tmp_path / "agents.yaml"
    f.write_text(texte)
    return f


def test_charge_catalogue_valide(tmp_path):
    cat = charger_catalogue(ecrire(tmp_path, VALIDE))
    assert cat.agents["spec"].nom == "spec"
    assert cat.pipelines["spec"] == ["spec"]
    assert cat.agents["spec"].temperature == 0.3


def test_champ_manquant_nomme_l_agent(tmp_path):
    with pytest.raises(CatalogueInvalide) as exc:
        charger_catalogue(ecrire(tmp_path, VALIDE.replace("    modele: m\n", "")))
    assert "spec" in str(exc.value) and "modele" in str(exc.value)


def test_pipeline_agent_inconnu(tmp_path):
    with pytest.raises(CatalogueInvalide, match="inconnu"):
        charger_catalogue(ecrire(tmp_path, VALIDE.replace("spec: [spec]", "spec: [inconnu]")))


def test_pipeline_vide_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide):
        charger_catalogue(ecrire(tmp_path, VALIDE.replace("spec: [spec]", "spec: []")))


def test_yaml_illisible(tmp_path):
    with pytest.raises(CatalogueInvalide):
        charger_catalogue(ecrire(tmp_path, "agents: [unclosed\n  : :"))


def test_agents_yaml_du_depot_est_valide():
    racine = Path(__file__).resolve().parents[2]
    cat = charger_catalogue(racine / "agents.yaml")
    assert "spec" in cat.pipelines
    assert cat.pipelines["planification"] == ["plan", "taches"]


def test_pipelines_mauvaise_forme(tmp_path):
    with pytest.raises(CatalogueInvalide) as exc:
        charger_catalogue(ecrire(tmp_path, VALIDE.replace("spec: [spec]", 'spec: "spec"')))
    assert "pipelines" in str(exc.value) and "?" not in str(exc.value)


def test_nom_dans_agent_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide, match="spec"):
        charger_catalogue(
            ecrire(tmp_path, VALIDE.replace("    modele: m", "    nom: x\n    modele: m"))
        )


def test_agent_auto_sans_consigne_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide, match="spec"):
        charger_catalogue(
            ecrire(
                tmp_path,
                VALIDE.replace("    prompt_systeme: p", "    prompt_systeme: p\n    auto: true"),
            )
        )


def test_agent_taches_avec_outils_refuse(tmp_path):
    texte = VALIDE.replace(
        "    prompt_systeme: p", "    prompt_systeme: p\n    produit: taches\n    outils: [lire]"
    )
    with pytest.raises(CatalogueInvalide, match="spec"):
        charger_catalogue(ecrire(tmp_path, texte))


def test_outil_inconnu_refuse(tmp_path):
    texte = VALIDE.replace("    prompt_systeme: p", "    prompt_systeme: p\n    outils: [ecrire]")
    with pytest.raises(CatalogueInvalide, match="ecrire"):
        charger_catalogue(ecrire(tmp_path, texte))


def test_valeurs_par_defaut(tmp_path):
    a = charger_catalogue(ecrire(tmp_path, VALIDE)).agents["spec"]
    assert (a.produit, a.auto, a.outils, a.tours_max) == ("spec", False, [], 20)
