import pytest

from portail.agents import Catalogue, charger_catalogue
from portail.schema_pipelines import DEBUT, FIN, RACINE, mermaid, remplacer
from tests.conftest import _agent


def catalogue(pipelines, *agents):
    return Catalogue(agents={n: _agent(n) for n in agents}, pipelines=pipelines)


def test_fleches_entre_etapes_qui_se_suivent():
    sortie = mermaid(catalogue({"x": ["a", "b", "c"]}, "a", "b", "c"))
    assert "g0_a --> g0_b" in sortie
    assert "g0_b --> g0_c" in sortie
    assert "g0_a --> g0_c" not in sortie
    assert 'subgraph g0["x"]' in sortie


def test_hors_pipeline_sans_fleche():
    sortie = mermaid(catalogue({"x": ["a"]}, "a", "d"))
    assert 'subgraph g1["hors pipeline"]' in sortie
    assert 'g1_d["d"]' in sortie
    assert not [ligne for ligne in sortie.splitlines() if "-->" in ligne and "g1_d" in ligne]


def test_agent_dans_deux_pipelines_deux_noeuds():
    sortie = mermaid(catalogue({"x": ["a"], "y": ["a"]}, "a"))
    assert 'g0_a["a"]' in sortie
    assert 'g1_a["a"]' in sortie


def test_remplacer_entre_les_marqueurs():
    t = f"avant\n{DEBUT}\nvieux\n{FIN}\naprès\n"
    r = remplacer(t, "neuf")
    assert r == f"avant\n{DEBUT}\nneuf\n{FIN}\naprès\n"
    assert remplacer(r, "neuf") == r


def test_remplacer_sans_marqueurs_refuse():
    with pytest.raises(ValueError):
        remplacer("rien", "x")
    with pytest.raises(ValueError):
        remplacer(f"{DEBUT} sans fin", "x")


def test_readme_a_jour():
    readme = (RACINE / "README.md").read_text(encoding="utf-8")
    attendu = remplacer(readme, mermaid(charger_catalogue(RACINE / "agents.yaml")))
    assert attendu == readme, (
        "README périmé : lancer `cd backend && uv run python -m portail.schema_pipelines`"
    )
