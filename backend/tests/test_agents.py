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
    assert "spec" in charger_catalogue(racine / "agents.yaml").pipelines


def test_pipelines_mauvaise_forme(tmp_path):
    with pytest.raises(CatalogueInvalide) as exc:
        charger_catalogue(ecrire(tmp_path, VALIDE.replace("spec: [spec]", 'spec: "spec"')))
    assert "pipelines" in str(exc.value) and "?" not in str(exc.value)


def test_nom_dans_agent_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide, match="spec"):
        charger_catalogue(
            ecrire(tmp_path, VALIDE.replace("    modele: m", "    nom: x\n    modele: m"))
        )
