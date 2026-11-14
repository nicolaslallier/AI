import pytest

from portail.execution import (
    ConfigExecution,
    commande,
    correspond,
    dossiers_lecture_seule,
    lire_config,
)
from portail.moteur import Refus

BASE = """
image: ghcr.io/nicolaslallier/ai-execution:latest
chemins_tests: ["backend/tests/**", "frontend/**/*.spec.ts"]
commandes:
  installer: uv sync
  tests: uv run pytest
  tests_cibles: uv run pytest {fichiers}
services:
  - nom: postgres
    image: pgvector/pgvector:pg16
    env: {POSTGRES_PASSWORD: test}
"""


def test_config_valide():
    cfg = lire_config(BASE)
    assert cfg.services[0].nom == "postgres"
    assert "pytest.ini" in cfg.protege and "backend/tests/**" in cfg.protege


def test_commandes_obligatoires_422():
    with pytest.raises(Refus) as e:
        lire_config(BASE.replace("  tests_cibles: uv run pytest {fichiers}\n", ""))
    assert e.value.code == 422 and "tests_cibles" in e.value.message


def test_gabarit_sans_fichiers_422():
    with pytest.raises(Refus) as e:
        lire_config(BASE.replace("{fichiers}", ""))
    assert e.value.code == 422


@pytest.mark.parametrize("texte", ["- a", ": : :", "image: x"])
def test_yaml_invalide_422(texte):
    with pytest.raises(Refus) as e:
        lire_config(texte)
    assert e.value.code == 422


def test_commande_quote_les_fichiers():
    cfg = lire_config(BASE)
    assert commande(cfg, "tests_cibles", ["a b.py"]) == "uv run pytest 'a b.py'"
    assert commande(cfg, "tests") == "uv run pytest"
    with pytest.raises(KeyError):
        commande(cfg, "inconnue")


@pytest.mark.parametrize(
    "motif, chemin, attendu",
    [
        ("tests/**", "tests/a/b.py", True),
        ("tests/**", "src/tests.py", False),
        ("**/conftest.py", "conftest.py", True),
        ("**/conftest.py", "a/conftest.py", True),
        ("**/conftest.py", "a/b/conftest.py", True),
        ("frontend/**/*.spec.ts", "frontend/src/x.spec.ts", True),
        ("frontend/**/*.spec.ts", "frontend/x.spec.ts", True),
        ("jest.config.*", "jest.config.js", True),
        ("jest.config.*", "a/jest.config.js", False),
        ("*.py", "a/b.py", False),
        ("a?.py", "a/.py", False),
        ("a?.py", "ab.py", True),
        ("Tests/**", "tests/a.py", False),
        ("a.b", "axb", False),
        ("tests/**", "tests/a\nb.py", True),
        ("**/conftest.py", "x\ny/conftest.py", True),
        ("*.py", "a\nb.py", True),
    ],
)
def test_correspond(motif, chemin, attendu):
    assert correspond(chemin, [motif]) is attendu


def test_correspond_aucun_motif():
    assert correspond("a", []) is False


def test_dossiers_lecture_seule(tmp_path):
    cfg = lire_config(BASE)
    assert dossiers_lecture_seule(cfg, tmp_path) == []
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    assert dossiers_lecture_seule(cfg, tmp_path) == ["backend/tests"]


def test_dossiers_lecture_seule_liens(tmp_path):
    cfg = lire_config(BASE)
    racine = tmp_path / "r"
    (racine / "backend").mkdir(parents=True)
    (tmp_path / "ailleurs").mkdir()
    (racine / "backend" / "tests").symlink_to(tmp_path / "ailleurs")
    assert dossiers_lecture_seule(cfg, racine) == []

    # composante intermédiaire en lien vers un vrai dossier contenant tests/
    autre = tmp_path / "autre"
    (autre / "backend" / "tests").mkdir(parents=True)
    (autre / "reel").mkdir()
    (autre / "reel" / "tests").mkdir()
    (autre / "backend2").mkdir()
    cfg2 = lire_config(BASE.replace("backend/tests/**", "reel/tests/**"))
    (autre / "reel").rename(autre / "reel_vrai")
    (autre / "reel").symlink_to(autre / "reel_vrai")
    assert dossiers_lecture_seule(cfg2, autre) == []

    lien = tmp_path / "lien"
    lien.symlink_to(autre)
    assert dossiers_lecture_seule(cfg, lien) == []


def test_dossiers_lecture_seule_composante_lien(tmp_path):
    cfg = lire_config(BASE)
    (tmp_path / "x" / "tests").mkdir(parents=True)
    (tmp_path / "backend").symlink_to(tmp_path / "x")
    assert dossiers_lecture_seule(cfg, tmp_path) == []


async def test_put_execution_api(client):
    pid = (await client.post("/api/projets", json={"nom": "P"})).json()["id"]
    assert (await client.get(f"/api/projets/{pid}")).json()["config_execution"] is None
    r = await client.put(f"/api/projets/{pid}/execution", json={"yaml": BASE})
    assert r.status_code == 200
    assert (await client.get(f"/api/projets/{pid}")).json()["config_execution"] == BASE
    r = await client.put(f"/api/projets/{pid}/execution", json={"yaml": "image: x"})
    assert r.status_code == 422
    assert (await client.get(f"/api/projets/{pid}")).json()["config_execution"] == BASE
    r = await client.put(f"/api/projets/{pid}/execution", json={"yaml": ""})
    assert r.status_code == 200
    assert (await client.get(f"/api/projets/{pid}")).json()["config_execution"] is None
    assert (await client.put("/api/projets/999/execution", json={"yaml": ""})).status_code == 404


def test_type():
    assert isinstance(lire_config(BASE), ConfigExecution)


@pytest.mark.parametrize(
    "remplacement",
    [
        ('chemins_tests: ["backend/tests/**", "frontend/**/*.spec.ts"]', "chemins_tests: []"),
        ("nom: postgres", "nom: Bad_Nom"),
        ("services:\n", "services:\n  - {nom: postgres, image: x}\n"),
    ],
)
def test_config_invalide_422(remplacement):
    with pytest.raises(Refus) as e:
        lire_config(BASE.replace(*remplacement))
    assert e.value.code == 422


def test_chemins_tests_vide_en_francais():
    with pytest.raises(Refus) as e:
        lire_config(BASE.replace('["backend/tests/**", "frontend/**/*.spec.ts"]', "[]"))
    assert "au moins un chemin" in e.value.message


@pytest.mark.parametrize(
    "chemin",
    ["tox.ini", "a/tox.ini", ".pytest.ini", "a/.pytest.ini", "front/jest.config.ts",
     "front/vitest.config.ts", "vitest.workspace.ts", "front/vitest.workspace.js"],
)  # fmt: skip
def test_config_tests_par_defaut_protegee(chemin):
    from portail.execution import correspond

    assert correspond(chemin, lire_config(BASE).protege)
