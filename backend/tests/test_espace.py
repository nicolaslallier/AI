import base64
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from portail.depots import ErreurDepot
from portail.espace import Espace
from portail.execution import correspond


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return r.stdout.strip()


@pytest.fixture
def origine(tmp_path):
    """Dépôt nu, alimenté depuis un clone de travail."""
    nu = tmp_path / "origine.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(nu))
    travail = tmp_path / "amont"
    git(tmp_path, "clone", str(nu), str(travail))
    (travail / "src").mkdir()
    (travail / "tests").mkdir()
    (travail / "src" / "b.py").write_text("b = 1\n")
    (travail / "tests" / "a.py").write_text("a = 1\n")
    git(travail, "add", "-A")
    git(travail, "commit", "-m", "initial")
    git(travail, "push", "origin", "main")
    return nu


def url(o: Path) -> str:
    return f"file://{o}"


@pytest.fixture
async def espace(tmp_path, origine):
    e = Espace(tmp_path / "espaces" / "tache-1-1")
    await e.cloner(url(origine), "", "main", "portail/tache-1-x")
    return e


async def test_cloner_branche_et_exclusions(tmp_path, origine):
    e = Espace(tmp_path / "espaces" / "tache-1-1")
    e.racine.mkdir(parents=True)
    (e.racine / "reste").write_text("ancien")
    sha = await e.cloner(url(origine), "", "main", "portail/tache-1-x")
    assert sha == git(origine, "rev-parse", "main")
    assert not (e.racine / "reste").exists()
    assert git(e.racine, "branch", "--show-current") == "portail/tache-1-x"
    (e.racine / "node_modules").mkdir()
    (e.racine / "node_modules" / "x").write_text("x")
    assert await e.changements() == []
    (e.racine / "nouveau.txt").write_text("n")
    assert await e.changements() == ["nouveau.txt"]


async def test_restaurer_garde_les_tests(espace):
    r = espace.racine
    (r / "tests" / "a.py").write_text("a = 2\n")
    (r / "src" / "b.py").write_text("b = 2\n")
    (r / "src" / "c.py").write_text("c = 1\n")
    annules = await espace.restaurer(lambda p: correspond(p, ["tests/**"]))
    assert sorted(annules) == ["src/b.py", "src/c.py"]
    assert (r / "tests" / "a.py").read_text() == "a = 2\n"
    assert (r / "src" / "b.py").read_text() == "b = 1\n"
    assert not (r / "src" / "c.py").exists()
    assert await espace.changements() == ["tests/a.py"]


async def test_restaurer_ne_suit_pas_les_liens(espace, tmp_path):
    cible = tmp_path / "dehors.txt"
    cible.write_text("intact")
    (espace.racine / "lien").symlink_to(cible)
    (espace.racine / "src" / "b.py").unlink()
    annules = await espace.restaurer(lambda p: False)
    assert sorted(annules) == ["lien", "src/b.py"]
    assert not (espace.racine / "lien").is_symlink()
    assert cible.read_text() == "intact"
    assert (espace.racine / "src" / "b.py").read_text() == "b = 1\n"


async def test_restaurer_chemin_avec_joker(espace):
    joker = espace.racine / "src" / "*.py"
    joker.write_text("j = 1\n")
    await espace.commiter("agent-code", "agent-code@portail.local", "joker")
    joker.write_text("j = 2\n")
    (espace.racine / "src" / "b.py").write_text("b = 2\n")
    assert await espace.restaurer(lambda p: p != "src/*.py") == ["src/*.py"]
    assert joker.read_text() == "j = 1\n"
    assert (espace.racine / "src" / "b.py").read_text() == "b = 2\n"


async def test_remettre_a_zero_garde_les_ignores(espace):
    r = espace.racine
    (r / "src" / "b.py").write_text("b = 3\n")
    (r / "src" / "d.py").write_text("d")
    (r / "node_modules").mkdir()
    (r / "node_modules" / "x").write_text("x")
    await espace.remettre_a_zero()
    assert await espace.changements() == []
    assert (r / "src" / "b.py").read_text() == "b = 1\n"
    assert (r / "node_modules" / "x").exists()


async def test_commit_auteur_et_commits(espace, origine):
    base = git(origine, "rev-parse", "main")
    (espace.racine / "tests" / "t.py").write_text("t\n")
    sha1 = await espace.commiter("agent-tests", "agent-tests@portail.local", "tests")
    (espace.racine / "src" / "b.py").write_text("b = 2\n")
    (espace.racine / "src" / "e.py").write_text("e\n")
    sha2 = await espace.commiter("agent-code", "agent-code@portail.local", "code")
    assert git(espace.racine, "log", "-1", "--format=%an %ae %cn %ce", sha2) == (
        "agent-code agent-code@portail.local agent-code agent-code@portail.local"
    )
    assert await espace.commits(base) == [
        (sha1, "agent-tests@portail.local", ["tests/t.py"]),
        (sha2, "agent-code@portail.local", ["src/b.py", "src/e.py"]),
    ]
    assert await espace.fichier_a(sha1, "src/b.py") == "b = 1\n"
    assert await espace.fichier_a(sha2, "src/b.py") == "b = 2\n"
    assert await espace.fichier_a(base, "tests/t.py") is None
    d = await espace.diff(base)
    assert "+b = 2" in d and "tests/t.py" in d


async def test_refs_comme_options_refusees(espace):
    with pytest.raises(ErreurDepot):
        await espace.commits("--output=/tmp/x")
    with pytest.raises(ErreurDepot):
        await espace.fichier_a("-p", "x")
    with pytest.raises(ErreurDepot):
        await espace.diff("--output=/tmp/x")
    with pytest.raises(ErreurDepot):
        await espace.pousser("", "--force")


async def test_commit_sans_changement_none(espace):
    assert await espace.commiter("agent-code", "agent-code@portail.local", "rien") is None


async def test_hook_jamais_execute(espace, tmp_path):
    temoin_hook = tmp_path / "hook-temoin"
    temoin_fsm = tmp_path / "fsmonitor-temoin"
    hook = espace.racine / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch {temoin_hook}\n")
    hook.chmod(0o755)
    fsm = tmp_path / "fsmonitor.sh"
    fsm.write_text(f"#!/bin/sh\ntouch {temoin_fsm}\n")
    fsm.chmod(0o755)
    with (espace.racine / ".git" / "config").open("a") as f:
        f.write(f"[core]\n\tfsmonitor = {fsm}\n\thooksPath = .git/hooks\n")
    (espace.racine / "src" / "b.py").write_text("b = 2\n")
    assert await espace.changements() == ["src/b.py"]
    assert await espace.commiter("agent-code", "agent-code@portail.local", "code")
    assert not temoin_hook.exists()
    assert not temoin_fsm.exists()


async def test_pousser_sans_force(espace, origine, tmp_path):
    (espace.racine / "src" / "b.py").write_text("b = 2\n")
    await espace.commiter("agent-code", "agent-code@portail.local", "code")
    await espace.pousser("", "portail/tache-1-x")
    assert git(origine, "rev-parse", "portail/tache-1-x") == git(espace.racine, "rev-parse", "HEAD")
    autre = tmp_path / "autre"
    git(tmp_path, "clone", "-b", "portail/tache-1-x", str(origine), str(autre))
    (autre / "z.txt").write_text("z")
    git(autre, "add", "-A")
    git(autre, "commit", "-m", "avance")
    git(autre, "push", "origin", "portail/tache-1-x")
    avance = git(origine, "rev-parse", "portail/tache-1-x")
    (espace.racine / "src" / "b.py").write_text("b = 3\n")
    await espace.commiter("agent-code", "agent-code@portail.local", "code 2")
    with pytest.raises(ErreurDepot):
        await espace.pousser("", "portail/tache-1-x")
    assert git(origine, "rev-parse", "portail/tache-1-x") == avance


async def test_jeton_absent_des_erreurs_et_du_disque(tmp_path, origine):
    b64 = base64.b64encode(b"x-access-token:SECRET123").decode()
    e = Espace(tmp_path / "espaces" / "tache-1-1")
    await e.cloner(url(origine), "SECRET123", "main", "portail/tache-1-x")
    (e.racine / "src" / "b.py").write_text("b = 2\n")
    await e.commiter("agent-code", "agent-code@portail.local", "code")
    await e.pousser("SECRET123", "portail/tache-1-x")
    for dossier, _, fichiers in os.walk(e.racine / ".git"):
        for nom in fichiers:
            contenu = (Path(dossier) / nom).read_bytes()
            assert b"SECRET123" not in contenu and b64.encode() not in contenu
    with pytest.raises(ErreurDepot) as exc:
        await e.cloner("file:///nexiste/SECRET123", "SECRET123", "main", "b")
    assert "SECRET123" not in str(exc.value) and b64 not in str(exc.value)


async def test_supprimer(espace):
    await espace.supprimer()
    assert not espace.racine.exists()


def planter_depot_imbrique(racine: Path, temoin: Path) -> Path:
    """Dépôt imbriqué dont le filtre clean crée un témoin s'il est exécuté."""
    sub = racine / "sub"
    sub.mkdir(exist_ok=True)
    git(sub, "init", "-b", "main")
    (sub / "f.txt").write_text("f\n")
    git(sub, "add", "-A")
    git(sub, "commit", "-m", "sub")
    with (sub / ".git" / "config").open("a") as f:
        f.write(f'[filter "x"]\n\tclean = touch {temoin}; cat\n')
    (sub / ".gitattributes").write_text("* filter=x\n")
    (sub / "f.txt").write_text("g\n")  # même taille : git doit relire (et filtrer)
    return sub


def gitlinks(racine: Path) -> list[str]:
    return [
        ligne for ligne in git(racine, "ls-tree", "-r", "HEAD").splitlines() if "160000" in ligne
    ]


async def test_depot_imbrique_jamais_execute_ni_commite(espace, origine, tmp_path):
    temoin = tmp_path / "filtre-temoin"
    sub = planter_depot_imbrique(espace.racine, temoin)
    (espace.racine / "src" / "b.py").write_text("b = 2\n")
    assert "sub" in await espace.changements()
    with pytest.raises(ErreurDepot, match="dépôt imbriqué refusé : sub"):
        await espace.commiter("agent-code", "agent-code@portail.local", "code")
    await espace.diff(git(origine, "rev-parse", "main"))
    await espace.remettre_a_zero()
    assert not sub.exists()
    assert gitlinks(espace.racine) == []
    assert not temoin.exists()


async def test_sous_module_livre_par_le_depot_jamais_execute(tmp_path, origine):
    temoin = tmp_path / "filtre-temoin"
    amont = tmp_path / "amont"
    sha = git(amont, "rev-parse", "HEAD")
    git(amont, "update-index", "--add", "--cacheinfo", f"160000,{sha},sub")
    git(amont, "commit", "-m", "gitlink")
    git(amont, "push", "origin", "main")
    e = Espace(tmp_path / "espaces" / "tache-1-1")
    base = await e.cloner(url(origine), "", "main", "portail/tache-1-x")
    planter_depot_imbrique(e.racine, temoin)
    (e.racine / "src" / "b.py").write_text("b = 2\n")
    assert "src/b.py" in await e.changements()
    with pytest.raises(ErreurDepot, match="dépôt imbriqué refusé : sub"):
        await e.commiter("agent-code", "agent-code@portail.local", "code")
    await e.diff(base)
    await e.remettre_a_zero()
    assert not temoin.exists()


async def test_environnement_git_herite_ignore(espace, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "intrus@x")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "intrus@x")
    (espace.racine / "src" / "b.py").write_text("b = 2\n")
    sha = await espace.commiter("agent-code", "agent-code@portail.local", "code")
    monkeypatch.delenv("GIT_AUTHOR_EMAIL")
    monkeypatch.delenv("GIT_COMMITTER_EMAIL")
    assert git(espace.racine, "log", "-1", "--format=%ae %ce", sha) == (
        "agent-code@portail.local agent-code@portail.local"
    )


async def test_diff_tronque_est_signale(espace, origine):
    (espace.racine / "gros.txt").write_text("x\n" * 150_000)
    await espace.commiter("agent-code", "agent-code@portail.local", "gros")
    d = await espace.diff(git(origine, "rev-parse", "main"))
    assert d.endswith("\n[… diff tronqué]")


async def test_pousser_vers_l_url_du_clone_seulement(espace, origine, tmp_path):
    leurre = tmp_path / "leurre.git"
    git(tmp_path, "init", "--bare", str(leurre))
    git(espace.racine, "remote", "set-url", "origin", str(leurre))
    (espace.racine / "src" / "b.py").write_text("b = 2\n")
    await espace.commiter("agent-code", "agent-code@portail.local", "code")
    await espace.pousser("", "portail/tache-1-x")
    assert git(origine, "rev-parse", "portail/tache-1-x") == git(espace.racine, "rev-parse", "HEAD")
    assert git(leurre, "for-each-ref") == ""


async def test_pousser_apres_redemarrage(espace, origine):
    (espace.racine / "src" / "b.py").write_text("b = 2\n")
    await espace.commiter("agent-code", "agent-code@portail.local", "code")
    with pytest.raises(ErreurDepot):
        await Espace(espace.racine).pousser("", "portail/tache-1-x")
    await Espace(espace.racine, url(origine)).pousser("", "portail/tache-1-x")
    assert git(origine, "rev-parse", "portail/tache-1-x") == git(espace.racine, "rev-parse", "HEAD")


def planter_sous_module_au_bon_sha(racine: Path, origine: Path, sha: str, temoin: Path) -> Path:
    """Dépôt imbriqué dont HEAD == le sha du gitlink livré : `add` le croirait sous-module."""
    sub = racine / "sub"
    shutil.rmtree(sub, ignore_errors=True)
    git(racine.parent, "clone", str(origine), str(sub))
    git(sub, "checkout", "-q", sha)
    with (sub / ".git" / "config").open("a") as f:
        f.write(f'[filter "x"]\n\tclean = touch {temoin}; cat\n')
    (sub / ".gitattributes").write_text("* filter=x\n")
    (sub / "src" / "b.py").write_text("b = 9\n")  # même taille : git doit relire (et filtrer)
    return sub


@pytest.mark.parametrize("nettoyage", ["restaurer", "remettre_a_zero"])
async def test_sous_module_peuple_au_sha_livre_refuse(tmp_path, origine, nettoyage):
    temoin = tmp_path / "filtre-temoin"
    amont = tmp_path / "amont"
    sha = git(amont, "rev-parse", "HEAD")
    git(amont, "update-index", "--add", "--cacheinfo", f"160000,{sha},sub")
    git(amont, "commit", "-m", "gitlink")
    git(amont, "push", "origin", "main")
    e = Espace(tmp_path / "espaces" / "tache-1-1")
    await e.cloner(url(origine), "", "main", "portail/tache-1-x")
    sub = planter_sous_module_au_bon_sha(e.racine, origine, sha, temoin)
    (e.racine / "src" / "b.py").write_text("b = 2\n")
    assert "sub" in await e.changements()
    with pytest.raises(ErreurDepot, match="dépôt imbriqué refusé : sub"):
        await e.commiter("agent-code", "agent-code@portail.local", "code")
    assert not temoin.exists()
    if nettoyage == "restaurer":
        assert "sub" in await e.restaurer(lambda p: True)
    else:
        await e.remettre_a_zero()
    assert not os.path.lexists(sub / ".git")
    (e.racine / "src" / "b.py").write_text("b = 3\n")
    assert await e.commiter("agent-code", "agent-code@portail.local", "code")
    assert not temoin.exists()
