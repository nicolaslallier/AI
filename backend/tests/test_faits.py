import pytest

from portail.db import CommandeLancee
from portail.execution import lire_config
from portail.faits import references_ajoutees, verifier_affirmations, verifier_references

CFG = lire_config(
    """
image: img
chemins_tests: ["tests/**"]
commandes: {installer: i, tests: t, tests_cibles: "t {fichiers}"}
"""
)


def diff_de(fichier, *lignes):
    return (
        f"diff --git a/{fichier} b/{fichier}\n--- a/{fichier}\n+++ b/{fichier}\n@@ -1 +1 @@\n"
        + ("\n".join(lignes) + "\n")
    )


def cmd(nom, code):
    return CommandeLancee(nom=nom, code=code)


def test_references_lignes_ajoutees_seulement():
    d = diff_de(
        "src/x.py", "-import inexistant", " import contexte", "+import os", "+from .a import b"
    )
    assert references_ajoutees(d) == [("src/x.py", "python", "os"), ("src/x.py", "python", ".a")]
    ts = diff_de("web/a.ts", "-import x from './vieux'", "+import y from './neuf'")
    assert references_ajoutees(ts) == [("web/a.ts", "ts", "./neuf")]
    assert references_ajoutees(diff_de("web/a.ts", "+import z from 'vue'")) == []


def test_import_local_inexistant_bloque(tmp_path):
    (tmp_path / "portail").mkdir()
    (tmp_path / "portail" / "__init__.py").write_text("")
    (tmp_path / "portail" / "dev.py").write_text("")
    refs = [("tests/t.py", "python", "portail.dev"), ("tests/t.py", "python", "portail.faux")]
    (fait,) = verifier_references(tmp_path, refs, CFG)
    assert (fait.type, fait.role, fait.bloquant) == ("reference", "tests", True)
    assert fait.texte.startswith("import portail.faux introuvable")
    (fait,) = verifier_references(tmp_path, [("src/x.py", "python", "portail.faux")], CFG)
    assert fait.role == "code"


def test_import_tiers_ignore(tmp_path):
    (tmp_path / "portail").mkdir()
    assert verifier_references(tmp_path, [("a.py", "python", "numpy.linalg")], CFG) == []


def test_import_ts_relatif_resolu_avec_extensions(tmp_path):
    (tmp_path / "web" / "lib").mkdir(parents=True)
    (tmp_path / "web" / "b.vue").write_text("")
    (tmp_path / "web" / "lib" / "index.ts").write_text("")
    refs = [("web/a.ts", "ts", c) for c in ("./b.vue", "./lib", "./absent")]
    (fait,) = verifier_references(tmp_path, refs, CFG)
    assert "./absent" in fait.texte


def test_affirmation_prouvee():
    assert (
        verifier_affirmations("Les tests passent.", [cmd("tests", 1), cmd("tests", 0)], "code")
        == []
    )


def test_affirmation_sans_preuve_bloque():
    (fait,) = verifier_affirmations("Le lint passe et tout va bien", [cmd("tests", 0)], "code")
    assert (fait.type, fait.role, fait.bloquant) == ("affirmation", "code", True)
    assert fait.texte == "affirmation « lint passe » sans commande qui la prouve"


def test_affirmation_dont_la_derniere_commande_echoue_bloque():
    faits = verifier_affirmations(
        "All tests pass", [cmd("tests", 0), cmd("tests_cibles", 1)], "tests"
    )
    assert len(faits) == 1 and faits[0].role == "tests"


@pytest.mark.parametrize(
    "texte",
    ["les tests ne passent pas encore", "tests don't pass yet", "je ne peux pas dire : tests pass"],
)
def test_negation_ignoree(texte):
    assert verifier_affirmations(texte, [], "code") == []
