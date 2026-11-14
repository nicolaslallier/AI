import json

from portail.execution import ConfigExecution
from portail.outils import OutilsEspace, empreinte

CFG = ConfigExecution(
    image="img",
    chemins_tests=["tests/**"],
    commandes={"installer": "uv sync", "tests": "pytest", "tests_cibles": "pytest {fichiers}"},
)


def _outils(racine, role, lances=None):
    async def lancer(nom):
        if lances is not None:
            lances.append(nom)
        return f"code 0\n{nom} ok"

    return OutilsEspace(racine, role, CFG, lancer)


def _noms(outils):
    return [s["function"]["name"] for s in outils.schemas()]


def test_schemas_par_role(tmp_path):
    assert _noms(_outils(tmp_path, "revue")) == ["lister", "lire", "chercher"]
    for role in ("tests", "code"):
        o = _outils(tmp_path, role)
        assert _noms(o) == ["lister", "lire", "chercher", "ecrire", "supprimer", "lancer"]
        lancer = next(s for s in o.schemas() if s["function"]["name"] == "lancer")
        enum = lancer["function"]["parameters"]["properties"]["nom"]["enum"]
        assert enum == ["tests", "tests_cibles"]


async def test_role_code_refuse_tests(tmp_path):
    o = _outils(tmp_path, "code")
    res = await o.executer("ecrire", json.dumps({"chemin": "tests/test_a.py", "contenu": "x"}))
    assert res == ("erreur : écriture interdite pour le rôle code", False)
    assert not (tmp_path / "tests").exists()
    res = await o.executer("ecrire", json.dumps({"chemin": "conftest.py", "contenu": "x"}))
    assert res[0] == "erreur : écriture interdite pour le rôle code"
    assert await o.executer("ecrire", json.dumps({"chemin": "src/a.py", "contenu": "x"})) == (
        "écrit : src/a.py",
        False,
    )
    assert (tmp_path / "src/a.py").read_text() == "x"


async def test_role_tests_refuse_src(tmp_path):
    o = _outils(tmp_path, "tests")
    res = await o.executer("ecrire", json.dumps({"chemin": "src/a.py", "contenu": "x"}))
    assert res == ("erreur : écriture interdite pour le rôle tests", False)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("x")
    assert (await o.executer("supprimer", '{"chemin": "src/a.py"}'))[0].startswith("erreur")
    assert (tmp_path / "src/a.py").exists()


async def test_role_tests_ecrit_conftest(tmp_path):
    o = _outils(tmp_path, "tests")
    assert (await o.executer("ecrire", '{"chemin": "conftest.py", "contenu": "c"}'))[0] == (
        "écrit : conftest.py"
    )
    assert (await o.executer("ecrire", '{"chemin": "tests/u/test_a.py", "contenu": "t"}'))[0] == (
        "écrit : tests/u/test_a.py"
    )
    assert (tmp_path / "tests/u/test_a.py").read_text() == "t"
    assert (await o.executer("supprimer", '{"chemin": "tests/u/test_a.py"}'))[0] == (
        "supprimé : tests/u/test_a.py"
    )
    assert not (tmp_path / "tests/u/test_a.py").exists()
    assert (await o.executer("supprimer", '{"chemin": "tests"}'))[0].startswith("erreur")


async def test_lien_vers_tests_refuse_pour_code(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "raccourci").symlink_to("tests")
    o = _outils(tmp_path, "code")
    res = await o.executer("ecrire", '{"chemin": "raccourci/test_x.py", "contenu": "x"}')
    assert res == ("erreur : écriture interdite pour le rôle code", False)
    assert not (tmp_path / "tests/test_x.py").exists()


async def test_lien_fichier_vers_tests_refuse_pour_code(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_a.py").write_text("t")
    (tmp_path / "a.py").symlink_to("tests/test_a.py")
    o = _outils(tmp_path, "code")
    res = await o.executer("ecrire", '{"chemin": "a.py", "contenu": "x"}')
    assert res[0] == "erreur : écriture interdite pour le rôle code"
    assert (tmp_path / "tests/test_a.py").read_text() == "t"


async def test_lien_hors_espace_refuse(tmp_path):
    dehors = tmp_path / "dehors"
    dehors.mkdir()
    espace = tmp_path / "espace"
    espace.mkdir()
    (espace / "x").symlink_to(dehors)
    o = _outils(espace, "code")
    res = await o.executer("ecrire", '{"chemin": "x/a", "contenu": "x"}')
    assert res[0] == "erreur : chemin interdit"
    assert not (dehors / "a").exists()


async def test_ecrire_refuse_secrets_git_et_trop_long(tmp_path):
    o = _outils(tmp_path, "code")
    assert (await o.executer("ecrire", '{"chemin": ".env", "contenu": "x"}'))[0] == (
        "erreur : fichier secret refusé"
    )
    assert (await o.executer("ecrire", '{"chemin": ".git/config", "contenu": "x"}'))[0] == (
        "erreur : chemin interdit"
    )
    gros = json.dumps({"chemin": "a.py", "contenu": "x" * 200_001})
    assert (await o.executer("ecrire", gros))[0].startswith("erreur")
    assert not (tmp_path / "a.py").exists()


async def test_dossiers_d_artefacts_refuses(tmp_path):
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "x.pth").write_text("ancien")
    (tmp_path / "lien").symlink_to(tmp_path / "node_modules", target_is_directory=True)
    (tmp_path / "node_modules").mkdir()
    for role in ("code", "tests"):
        o = _outils(tmp_path, role)
        for chemin, dossier in [
            (".venv/lib/sitecustomize.py", ".venv"),
            ("src/__pycache__/a.pyc", "__pycache__"),
            ("tests/.pytest_cache/x", ".pytest_cache"),
            ("lien/a.js", "node_modules"),
            (".VENV/b.pth", ".VENV"),
        ]:
            args = json.dumps({"chemin": chemin, "contenu": "x"})
            assert (await o.executer("ecrire", args))[
                0
            ] == f"erreur : écriture interdite dans {dossier}"
        res = await o.executer("supprimer", '{"chemin": ".venv/lib/x.pth"}')
        assert res[0] == "erreur : écriture interdite dans .venv"
    assert not (tmp_path / ".venv" / "lib" / "sitecustomize.py").exists()
    assert (tmp_path / ".venv" / "lib" / "x.pth").exists()


async def test_revue_ne_peut_pas_ecrire(tmp_path):
    o = _outils(tmp_path, "revue")
    res = await o.executer("ecrire", '{"chemin": "a.py", "contenu": "x"}')
    assert res[1] is True and not (tmp_path / "a.py").exists()


async def test_lancer_delegue(tmp_path):
    lances = []
    o = _outils(tmp_path, "code", lances)
    assert await o.executer("lancer", '{"nom": "tests"}') == ("code 0\ntests ok", False)
    assert lances == ["tests"]
    res = await o.executer("lancer", '{"nom": "installer"}')
    assert res[0].startswith("erreur") and lances == ["tests"]


def test_empreinte_ignore_les_liens(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_a.py").write_text("a")
    (tmp_path / "ailleurs").mkdir()
    (tmp_path / "ailleurs/b.py").write_text("b")
    (tmp_path / "tests/lien.py").symlink_to("../ailleurs/b.py")
    (tmp_path / "tests/dossier").symlink_to("../ailleurs")
    (tmp_path / "tests/__pycache__").mkdir()
    (tmp_path / "tests/__pycache__/x.pyc").write_text("c")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/tests").mkdir()
    e = empreinte(tmp_path, ["tests/**", ".git/**"])
    assert list(e) == ["tests/test_a.py"]
    assert len(e["tests/test_a.py"]) == 64
    (tmp_path / "tests/test_a.py").write_text("a2")
    assert empreinte(tmp_path, ["tests/**"]) != e


async def test_lien_physique_vers_tests_refuse(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_a.py").write_text("t")
    (tmp_path / "a.py").hardlink_to(tmp_path / "tests/test_a.py")
    o = _outils(tmp_path, "code")
    res = await o.executer("ecrire", '{"chemin": "a.py", "contenu": "x"}')
    assert res[0].startswith("erreur")
    assert (tmp_path / "tests/test_a.py").read_text() == "t"


async def test_boucle_de_liens_refusee(tmp_path):
    (tmp_path / "boucle").symlink_to("boucle")
    o = _outils(tmp_path, "code")
    for nom, args in [
        ("lire", {"chemin": "boucle/x"}),
        ("lister", {"chemin": "boucle/x"}),
        ("ecrire", {"chemin": "boucle/x", "contenu": "x"}),
        ("supprimer", {"chemin": "boucle/x"}),
    ]:
        res, _ = await o.executer(nom, json.dumps(args))
        assert res.startswith("erreur : "), (nom, res)
    assert (await o.executer("supprimer", '{"chemin": "boucle"}'))[0] == "supprimé : boucle"


async def test_supprimer_un_lien_supprime_le_lien(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/a.py").write_text("t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/lien").symlink_to("../tests/a.py")
    res = await _outils(tmp_path, "tests").executer("supprimer", '{"chemin": "src/lien"}')
    assert res[0] == "erreur : écriture interdite pour le rôle tests"
    assert (tmp_path / "src/lien").is_symlink()
    res = await _outils(tmp_path, "code").executer("supprimer", '{"chemin": "src/lien"}')
    assert res[0] == "supprimé : src/lien"
    assert not (tmp_path / "src/lien").is_symlink()
    assert (tmp_path / "tests/a.py").read_text() == "t"


async def test_erreur_os_sans_chemin_absolu(tmp_path):
    (tmp_path / "f").write_text("x")
    o = _outils(tmp_path, "code")
    res, _ = await o.executer("ecrire", '{"chemin": "f/a.py", "contenu": "x"}')
    assert res.startswith("erreur : ") and str(tmp_path) not in res
