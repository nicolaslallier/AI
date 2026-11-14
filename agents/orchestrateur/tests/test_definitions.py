from pathlib import Path

import pytest

from orchestrateur import definitions


def test_charge_les_agents_du_depot():
    orch, sous_agents = definitions.charger()
    assert orch.nom == "orchestrateur"
    assert set(sous_agents) == set(definitions.SOUS_AGENTS)
    assert "Agent" in (orch.outils or [])
    for d in sous_agents.values():
        assert d.description and d.prompt and d.modele


def test_explorateur_et_relecteur_n_ecrivent_pas():
    _, sous_agents = definitions.charger()
    for nom in ("explorateur", "testeur", "relecteur"):
        assert not {"Edit", "Write"} & set(sous_agents[nom].outils or ["tous"]), nom
    assert sous_agents["explorateur"].outils == ["Read", "Grep", "Glob"]


def test_vers_sdk():
    _, sous_agents = definitions.charger()
    a = sous_agents["codeur"].vers_sdk()
    assert a.model == "claude-opus-5-5"
    assert "Edit" in a.tools
    assert sous_agents["codeur"].vers_sdk(modele="autre").model == "autre"


def ecrire(dossier: Path, nom: str, texte: str) -> Path:
    f = dossier / f"{nom}.md"
    f.write_text(texte)
    return f


def test_outils_absents_veut_dire_tous(tmp_path):
    d = definitions.lire(ecrire(tmp_path, "a", "---\nname: a\ndescription: x\n---\nCorps\n"))
    assert d.outils is None and d.modele is None and d.prompt == "Corps"


@pytest.mark.parametrize(
    "texte, message",
    [
        ("name: a\n", "en-tête"),
        ("---\nname: a\ndescription: x\n", "non fermé"),
        ("---\nname: a\n---\n", "description"),
        ("---\nname: b\ndescription: x\n---\n", "différent"),
        ("---\nname: a\ndescription: x\nsans deux points\n---\n", "invalide"),
    ],
)
def test_entetes_invalides(tmp_path, texte, message):
    with pytest.raises(ValueError, match=message):
        definitions.lire(ecrire(tmp_path, "a", texte))
