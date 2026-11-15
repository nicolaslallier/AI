# ruff: noqa: F811
import pytest

from portail.depots import ErreurDepot
from portail.execution import ConfigExecution
from portail.protections import section_de_test, verifier_commits_code
from tests.test_espace import espace, git, origine  # noqa: F401  (fixtures réutilisées)


@pytest.fixture
def cfg():
    return ConfigExecution(
        image="x",
        chemins_tests=["tests/**"],
        commandes={"installer": "i", "tests": "t", "tests_cibles": "t {fichiers}"},
    )


async def _base(espace, fichiers: dict[str, str]):
    """Commit initial (auteur neutre) avec les fichiers donnés ; renvoie son sha."""
    for chemin, contenu in fichiers.items():
        p = espace.racine / chemin
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenu)
    return await espace.commiter("humain", "h@x.fr", "base")


async def _code(espace, fichiers: dict[str, str | None], auteur="agent-code"):
    for chemin, contenu in fichiers.items():
        p = espace.racine / chemin
        if contenu is None:
            p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(contenu)
    await espace.commiter(auteur, f"{auteur}@portail.local", "c")


async def test_commit_code_touche_un_test(espace, cfg):
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(espace, {"tests/a.py": "a = 2\n", "src/b.py": "b = 2\n"})
    assert await verifier_commits_code(espace, base, cfg) == ["tests/a.py (fichier de tests)"]


async def test_commit_doc_hors_chemins_viole(espace, cfg):
    base = await _base(espace, {"README.md": "a"})
    await _code(espace, {"README.md": "b", "src/a.py": "x", "tests/t.py": "y"}, "agent-doc")
    assert sorted(await verifier_commits_code(espace, base, cfg)) == [
        "src/a.py (hors des chemins de doc)",
        "tests/t.py (hors des chemins de doc)",
    ]


async def test_commit_doc_dans_docs_permis(espace, cfg):
    base = await _base(espace, {"README.md": "a"})
    await _code(espace, {"README.md": "b", "docs/a.md": "x"}, "agent-doc")
    assert await verifier_commits_code(espace, base, cfg) == []


async def test_commit_doc_md_sous_chemin_protege_viole(espace, cfg):
    cfg = cfg.model_copy(update={"chemins_doc": ["**/*.md"]})
    base = await _base(espace, {"README.md": "a"})
    await _code(espace, {"README.md": "b", "tests/notes.md": "x"}, "agent-doc")
    assert await verifier_commits_code(espace, base, cfg) == [
        "tests/notes.md (hors des chemins de doc)"
    ]


async def test_commit_doc_section_de_test_du_manifeste_viole(espace, cfg):
    cfg = cfg.model_copy(update={"chemins_doc": ["**"]})
    await _base(espace, {"pyproject.toml": "[tool.pytest.ini_options]\naddopts = '-q'\n"})
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(
        espace, {"pyproject.toml": "[tool.pytest.ini_options]\naddopts = '-q --lf'\n"}, "agent-doc"
    )
    assert await verifier_commits_code(espace, base, cfg) == [
        "pyproject.toml (section tool.pytest.ini_options)"
    ]


async def test_commit_code_supprime_un_test(espace, cfg):
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(espace, {"tests/a.py": None})
    assert await verifier_commits_code(espace, base, cfg) == ["tests/a.py (fichier de tests)"]


async def test_commit_code_change_tool_pytest(espace, cfg):
    await _base(espace, {"pyproject.toml": "[tool.pytest.ini_options]\naddopts = '-q'\n"})
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(espace, {"pyproject.toml": "[tool.pytest.ini_options]\naddopts = '-q --lf'\n"})
    assert await verifier_commits_code(espace, base, cfg) == [
        "pyproject.toml (section tool.pytest.ini_options)"
    ]


async def test_commit_code_ajoute_une_dependance_permis(espace, cfg):
    await _base(
        espace, {"pyproject.toml": "[project]\nname = 'x'\n[tool.pytest.ini_options]\na = 1\n"}
    )
    base = git(espace.racine, "rev-parse", "HEAD")
    # dépendance ajoutée et mise en forme différente : pas une violation
    await _code(
        espace,
        {
            "pyproject.toml": "[project]\nname = 'x'\ndependencies = ['y']\n\n[tool.pytest.ini_options]\na   = 1\n"
        },
    )
    assert await verifier_commits_code(espace, base, cfg) == []


async def test_package_json_script_test(espace, cfg):
    await _base(
        espace,
        {"web/package.json": '{"scripts": {"test": "jest", "build": "tsc"}, "jest": {"a": 1}}'},
    )
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(
        espace,
        {"web/package.json": '{"scripts": {"test": "true", "build": "vite"}, "jest": {"a": 1}}'},
    )
    assert await verifier_commits_code(espace, base, cfg) == ["web/package.json (section scripts)"]


async def test_cargo_dev_dependencies(espace, cfg):
    await _base(espace, {"Cargo.toml": "[dev-dependencies]\nrstest = '1'\n"})
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(espace, {"Cargo.toml": "[dev-dependencies]\nrstest = '1'\nmockall = '1'\n"})
    assert await verifier_commits_code(espace, base, cfg) == [
        "Cargo.toml (section dev-dependencies)"
    ]


async def test_setup_cfg_tool_pytest(espace, cfg):
    await _base(espace, {"lib/setup.cfg": "[tool:pytest]\naddopts = -q\n[metadata]\nname = x\n"})
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(
        espace, {"lib/setup.cfg": "[tool:pytest]\naddopts = -q -k nothing\n[metadata]\nname = x\n"}
    )
    assert await verifier_commits_code(espace, base, cfg) == ["lib/setup.cfg (section tool:pytest)"]


async def test_setup_cfg_entry_points(espace, cfg):
    await _base(espace, {"setup.cfg": "[metadata]\nname = x\n"})
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(
        espace,
        {"setup.cfg": "[metadata]\nname = x\n[options.entry_points]\npytest11 =\n    p = x.p\n"},
    )
    assert await verifier_commits_code(espace, base, cfg) == [
        "setup.cfg (section options.entry_points)"
    ]


async def test_manifeste_ajoute_avec_sections_de_tests(espace, cfg):
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(espace, {"pyproject.toml": "[tool.pytest.ini_options]\na = 1\n"})
    assert await verifier_commits_code(espace, base, cfg) == [
        "pyproject.toml (section tool.pytest.ini_options)"
    ]


async def test_manifeste_supprime_avec_sections_de_tests(espace, cfg):
    await _base(espace, {"Cargo.toml": "[dev-dependencies]\nrstest = '1'\n"})
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(espace, {"Cargo.toml": None})
    assert await verifier_commits_code(espace, base, cfg) == [
        "Cargo.toml (section dev-dependencies)"
    ]


async def test_manifeste_illisible(espace, cfg):
    await _base(espace, {"package.json": "{}"})
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(espace, {"package.json": "{pas du json"})
    assert await verifier_commits_code(espace, base, cfg) == ["package.json (illisible)"]


async def test_commit_d_un_autre_auteur_ignore(espace, cfg):
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(espace, {"tests/a.py": "a = 2\n"}, auteur="agent-tests")
    assert await verifier_commits_code(espace, base, cfg) == []


async def _viol(espace, cfg, avant: dict[str, str], apres: dict[str, str]):
    await _base(espace, avant)
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(espace, apres)
    return await verifier_commits_code(espace, base, cfg)


async def test_scripts_indirection(espace, cfg):
    avant = '{"scripts": {"test": "npm run t", "t": "jest"}}'
    apres = '{"scripts": {"test": "npm run t", "t": "true"}}'
    assert await _viol(espace, cfg, {"package.json": avant}, {"package.json": apres}) == [
        "package.json (section scripts)"
    ]


async def test_package_json_mocha(espace, cfg):
    assert await _viol(
        espace,
        cfg,
        {"package.json": '{"mocha": {"a": 1}}'},
        {"package.json": '{"mocha": {"a": 2}}'},
    ) == ["package.json (section mocha)"]


async def test_pytest11_entry_point(espace, cfg):
    avant = "[project]\nname = 'x'\n"
    apres = avant + "[project.entry-points.pytest11]\nx = 'evil'\n"
    assert await _viol(espace, cfg, {"pyproject.toml": avant}, {"pyproject.toml": apres}) == [
        "pyproject.toml (section project.entry-points)"
    ]


@pytest.mark.parametrize(
    "ajout, section",
    [
        ("[project]\nname = 'x'\ndynamic = ['entry-points']\n", "project.dynamic"),
        ("[project]\nname = 'x'\n[tool.setuptools.dynamic]\nreadme = {file = 'p.txt'}\n",
         "tool.setuptools"),
        ("[project]\nname = 'x'\n[build-system]\nrequires = ['evil']\n", "build-system"),
    ],
)  # fmt: skip
async def test_pyproject_build_et_dynamique(espace, cfg, ajout, section):
    avant = "[project]\nname = 'x'\n"
    assert await _viol(espace, cfg, {"pyproject.toml": avant}, {"pyproject.toml": ajout}) == [
        f"pyproject.toml (section {section})"
    ]


async def test_setup_cfg_options(espace, cfg):
    avant = "[metadata]\nname = x\n"
    apres = avant + "[options]\nentry_points = file: ep.cfg\n"
    assert await _viol(espace, cfg, {"setup.cfg": avant}, {"setup.cfg": apres}) == [
        "setup.cfg (section options)"
    ]


async def test_tool_coverage(espace, cfg):
    avant = "[tool.coverage.report]\nfail_under = 90\n"
    apres = "[tool.coverage.report]\nfail_under = 0\n"
    assert await _viol(espace, cfg, {"pyproject.toml": avant}, {"pyproject.toml": apres}) == [
        "pyproject.toml (section tool.coverage.report)"
    ]


async def test_cargo_dev_dependencies_underscore(espace, cfg):
    avant = "[dev-dependencies]\nrstest = '1'\n"
    apres = "[dev_dependencies]\nrstest = '1'\nmockall = '1'\n"
    assert await _viol(espace, cfg, {"Cargo.toml": avant}, {"Cargo.toml": apres}) == [
        "Cargo.toml (section dev-dependencies)",
        "Cargo.toml (section dev_dependencies)",
    ]


async def test_cargo_deux_graphies_change_la_seconde(espace, cfg):
    avant = "[dev-dependencies]\na = '1'\n\n[dev_dependencies]\nb = '1'\n"
    apres = "[dev-dependencies]\na = '1'\n\n[dev_dependencies]\nb = '2'\n"
    assert await _viol(espace, cfg, {"Cargo.toml": avant}, {"Cargo.toml": apres}) == [
        "Cargo.toml (section dev_dependencies)"
    ]


async def test_cargo_target_dev_dependencies_underscore(espace, cfg):
    avant = "[target.'cfg(unix)'.dev-dependencies]\na = '1'\n"
    apres = "[target.'cfg(unix)'.dev_dependencies]\na = '2'\n"
    assert await _viol(espace, cfg, {"Cargo.toml": avant}, {"Cargo.toml": apres}) == [
        "Cargo.toml (section target.cfg(unix).dev-dependencies)",
        "Cargo.toml (section target.cfg(unix).dev_dependencies)",
    ]


async def test_cargo_profile_test(espace, cfg):
    avant = "[profile.test]\nopt-level = 0\n"
    apres = "[profile.test]\nopt-level = 3\n"
    assert await _viol(espace, cfg, {"Cargo.toml": avant}, {"Cargo.toml": apres}) == [
        "Cargo.toml (section profile.test)"
    ]


async def test_erreur_git_propagee(espace, cfg):
    await _base(espace, {"Cargo.toml": "[dev-dependencies]\n"})
    base = git(espace.racine, "rev-parse", "HEAD")
    await _code(espace, {"Cargo.toml": "[dev-dependencies]\na = '1'\n"})
    with pytest.raises(ErreurDepot):
        await verifier_commits_code(espace, "0" * 40, cfg)  # commits() échoue
    with pytest.raises(ErreurDepot):
        await espace.fichier_a("0" * 40, "Cargo.toml")
    assert await espace.fichier_a(base, "absent.toml") is None


PYPROJECT = """[project]
name = "x"
dependencies = ["httpx"]

[tool.pytest.ini_options]
addopts = "-q"
"""
PACKAGE = """{
  "name": "x",
  "scripts": {
    "test": "jest"
  },
  "dependencies": {
    "a": "1"
  }
}
"""
CARGO = """[package]
name = "x"

[dev-dependencies]
proptest = "1"
"""


@pytest.mark.parametrize(
    ("nom", "texte", "ligne", "attendu"),
    [
        ("pyproject.toml", PYPROJECT, 6, True),
        ("pyproject.toml", PYPROJECT, 3, False),
        ("package.json", PACKAGE, 4, True),
        ("package.json", PACKAGE, 7, False),
        ("Cargo.toml", CARGO, 5, True),
    ],
)
def test_section_de_test(nom, texte, ligne, attendu):
    assert section_de_test(nom, texte, ligne) is attendu
