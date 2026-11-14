import base64
import subprocess
from pathlib import Path

import pytest

from portail.depots import Depots, ErreurDepot


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return r.stdout.strip()


def commit(origine: Path, nom: str, texte: str) -> str:
    (origine / nom).write_text(texte)
    git(origine, "add", nom)
    git(origine, "commit", "-m", nom)
    return git(origine, "rev-parse", "HEAD")


@pytest.fixture
def origine(tmp_path):
    o = tmp_path / "origine"
    o.mkdir()
    git(o, "init", "-b", "main")
    commit(o, "a.txt", "un")
    commit(o, "b.txt", "deux")
    return o


@pytest.fixture
def depots(tmp_path):
    return Depots(tmp_path / "donnees", "")


def url(o: Path) -> str:
    return f"file://{o}"


async def test_preparer_cree_un_arbre_sur_la_branche(origine, depots):
    arbre, sha = await depots.preparer(1, url(origine), "main", 10, None)
    assert (arbre / "b.txt").read_text() == "deux"
    assert sha == git(origine, "rev-parse", "main")


async def test_sha_fige_pour_l_etape(origine, depots):
    _, sha = await depots.preparer(1, url(origine), "main", 10, None)
    commit(origine, "c.txt", "trois")
    arbre, sha2 = await depots.preparer(1, url(origine), "main", 10, None)
    assert sha2 == sha
    assert not (arbre / "c.txt").exists()


async def test_nouvelle_etape_voit_le_nouveau_commit(origine, depots):
    await depots.preparer(1, url(origine), "main", 10, None)
    nouveau = commit(origine, "c.txt", "trois")
    arbre, sha = await depots.preparer(1, url(origine), "main", 11, None)
    assert sha == nouveau
    assert (arbre / "c.txt").exists()


async def test_sha_donne_recree_l_arbre(origine, depots):
    _, ancien = await depots.preparer(1, url(origine), "main", 10, None)
    commit(origine, "c.txt", "trois")
    await depots.liberer(10)
    arbre, sha = await depots.preparer(1, url(origine), "main", 10, ancien)
    assert sha == ancien
    assert not (arbre / "c.txt").exists()


async def test_branche_par_defaut(origine, depots):
    _, sha = await depots.preparer(1, url(origine), None, 10, None)
    assert sha == git(origine, "rev-parse", "main")


async def test_branche_introuvable(origine, depots):
    with pytest.raises(ErreurDepot, match="branche inexistante introuvable dans le dépôt"):
        await depots.preparer(1, url(origine), "inexistante", 10, None)


@pytest.mark.parametrize("b", ["--upload-pack=x", "a..b", "a b", "a\nb"])
async def test_branche_invalide(origine, depots, b):
    with pytest.raises(ErreurDepot, match="introuvable"):
        await depots.preparer(1, url(origine), b, 10, None)


async def test_depot_vide(tmp_path, depots):
    o = tmp_path / "vide"
    o.mkdir()
    git(o, "init", "-b", "main")
    with pytest.raises(ErreurDepot, match="branche main introuvable dans le dépôt"):
        await depots.preparer(1, url(o), None, 10, None)


async def test_sha_invalide(origine, depots):
    with pytest.raises(ErreurDepot):
        await depots.preparer(1, url(origine), "main", 10, "--force")


async def test_depot_injoignable(depots):
    with pytest.raises(ErreurDepot):
        await depots.preparer(1, "file:///nexiste/pas", "main", 10, None)


async def test_jeton_jamais_ecrit(origine, tmp_path):
    d = Depots(tmp_path / "donnees", "SECRET123")
    b64 = base64.b64encode(b"x-access-token:SECRET123").decode()
    await d.preparer(1, url(origine), "main", 10, None)
    for f in (tmp_path / "donnees" / "depots").rglob("*"):
        if f.is_file():
            assert b"SECRET123" not in f.read_bytes()
            assert b64.encode() not in f.read_bytes()
    with pytest.raises(ErreurDepot) as exc:
        await d.preparer(2, "file:///nexiste/pas", "main", 11, None)
    assert "SECRET123" not in str(exc.value)


async def test_nettoyer_garde_seulement_les_etapes_demandees(origine, depots, tmp_path):
    for i in (10, 11, 12):
        await depots.preparer(1, url(origine), "main", i, None)
    await depots.nettoyer({11})
    arbres = tmp_path / "donnees" / "arbres"
    assert sorted(p.name for p in arbres.iterdir()) == ["11"]
    assert "arbres/10" not in git(tmp_path / "donnees" / "depots" / "1.git", "worktree", "list")


async def test_liberer_sans_arbre(depots):
    await depots.liberer(99)


def test_scrub_retire_jeton_et_base64(tmp_path):
    d = Depots(tmp_path, "SECRET123")
    b64 = base64.b64encode(b"x-access-token:SECRET123").decode()
    sortie = d._scrub(f"Authorization: Basic {b64} et SECRET123")
    assert "SECRET123" not in sortie and b64 not in sortie


async def test_clone_echoue_ne_laisse_rien(depots, tmp_path):
    with pytest.raises(ErreurDepot):
        await depots.preparer(1, "file:///nexiste/pas", "main", 10, None)
    assert not (tmp_path / "donnees" / "depots" / "1.git").exists()


async def test_sha_inconnu(origine, depots):
    with pytest.raises(ErreurDepot, match="commit .* introuvable dans le dépôt"):
        await depots.preparer(1, url(origine), "main", 10, "a" * 40)


async def test_clone_interrompu_est_nettoye(depots, tmp_path, monkeypatch):
    async def faux_git(self, *args, **kw):
        clone = Path(args[args.index("--") + 2])
        clone.mkdir(parents=True)
        (clone / "junk").write_text("x")
        raise ErreurDepot("interrompu")

    monkeypatch.setattr(Depots, "_git", faux_git)
    with pytest.raises(ErreurDepot):
        await depots.preparer(1, "file:///x", "main", 10, None)
    assert not (tmp_path / "donnees" / "depots" / "1.git").exists()


async def test_nouvelle_url_lit_le_nouveau_depot(origine, depots, tmp_path):
    await depots.preparer(1, url(origine), None, 10, None)
    autre = tmp_path / "autre"
    autre.mkdir()
    git(autre, "init", "-b", "trunk")
    nouveau = commit(autre, "z.txt", "autre dépôt")
    arbre, sha = await depots.preparer(1, url(autre), None, 11, None)
    assert sha == nouveau
    assert (arbre / "z.txt").exists() and not (arbre / "a.txt").exists()
