import pytest

from orchestrateur import depot
from tests.conftest import git


def test_racine(depot_git):
    (depot_git / "sous").mkdir()
    assert depot.racine(depot_git / "sous") == depot_git


def test_racine_hors_depot(tmp_path):
    with pytest.raises(depot.ErreurDepot, match="pas un dépôt"):
        depot.racine(tmp_path)


def test_preparer_branche(depot_git):
    assert depot.preparer_branche(depot_git, "orchestrateur/x") == "main"
    assert depot.branche_courante(depot_git) == "orchestrateur/x"
    assert depot.commits_depuis(depot_git, "main") == []
    (depot_git / "a.txt").write_text("a")
    git(depot_git, "add", "a.txt")
    git(depot_git, "commit", "-q", "-m", "ajoute a")
    assert len(depot.commits_depuis(depot_git, "main")) == 1


def test_refuse_arbre_modifie(depot_git):
    (depot_git / "README.md").write_text("modifié")
    with pytest.raises(depot.ErreurDepot, match="non committées"):
        depot.preparer_branche(depot_git, "orchestrateur/x")
    assert depot.branche_courante(depot_git) == "main"


def test_refuse_head_detachee(depot_git):
    git(depot_git, "checkout", "-q", "--detach")
    with pytest.raises(depot.ErreurDepot, match="détachée"):
        depot.preparer_branche(depot_git, "orchestrateur/x")
