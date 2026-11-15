import pytest

from portail.db import CommandeLancee, Etape, Message, Pipeline, Projet
from portail.execution import lire_config
from portail.faits import (
    references_ajoutees,
    verifier_affirmations,
    verifier_faits,
    verifier_references,
)

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
        verifier_affirmations(
            "Les tests passent.", [cmd("tests", 1), cmd("tests", 0)], "code", set(CFG.commandes)
        )
        == []
    )


def test_affirmation_sans_preuve_bloque():
    (fait,) = verifier_affirmations(
        "Le lint passe et tout va bien", [cmd("tests", 0)], "code", {"tests", "lint"}
    )
    assert (fait.type, fait.role, fait.bloquant) == ("affirmation", "code", True)
    assert fait.texte == "affirmation « lint passe » sans commande qui la prouve"


def test_affirmation_sans_commande_declaree_ignoree():
    texte = "Le lint passe et le build est ok."
    assert verifier_affirmations(texte, [], "code", set(CFG.commandes)) == []


@pytest.mark.parametrize("code_lint", [0, 1])
async def test_lint_du_portail_tranche_l_affirmation_lint(sessions, tmp_path, code_lint):
    cfg = lire_config(
        "image: img\nchemins_tests: ['tests/**']\n"
        "commandes: {installer: i, tests: t, tests_cibles: 't {fichiers}', lint: l}\n"
    )
    async with sessions() as s:
        projet = Projet(nom="p")
        s.add(projet)
        await s.flush()
        pipeline = Pipeline(projet_id=projet.id, type="dev")
        s.add(pipeline)
        await s.flush()
        etape = Etape(pipeline_id=pipeline.id, ordre=0, agent="code")
        s.add(etape)
        await s.flush()
        s.add(Message(etape_id=etape.id, role="assistant", contenu="Fait, le lint passe."))
        await s.commit()
    lint = cmd("lint", code_lint)
    lint.sortie = "E501"
    faits = await verifier_faits(sessions, pipeline.id, tmp_path, cfg, "", lint, True)
    assert [f.type for f in faits] == ([] if code_lint == 0 else ["lint"])


@pytest.mark.parametrize("lint_base_ok", [False, None])
async def test_lint_en_echec_sur_dette_n_absout_pas_l_affirmation(sessions, tmp_path, lint_base_ok):
    cfg = lire_config(
        "image: img\nchemins_tests: ['tests/**']\n"
        "commandes: {installer: i, tests: t, tests_cibles: 't {fichiers}', lint: l}\n"
    )
    async with sessions() as s:
        projet = Projet(nom="p")
        s.add(projet)
        await s.flush()
        pipeline = Pipeline(projet_id=projet.id, type="dev")
        s.add(pipeline)
        await s.flush()
        etape = Etape(pipeline_id=pipeline.id, ordre=0, agent="code")
        s.add(etape)
        await s.flush()
        s.add(Message(etape_id=etape.id, role="assistant", contenu="Fait, le lint passe."))
        await s.commit()
    lint = cmd("lint", 1)
    lint.sortie = "E501"
    faits = await verifier_faits(sessions, pipeline.id, tmp_path, cfg, "", lint, lint_base_ok)
    assert sorted((f.type, f.bloquant) for f in faits) == [("affirmation", True), ("lint", False)]


def test_affirmation_dont_la_derniere_commande_echoue_bloque():
    faits = verifier_affirmations(
        "All tests pass", [cmd("tests", 0), cmd("tests_cibles", 1)], "tests", set(CFG.commandes)
    )
    assert len(faits) == 1 and faits[0].role == "tests"


@pytest.mark.parametrize(
    "texte",
    [
        "les tests ne passent pas encore",
        "tests don't pass yet",
        "je ne peux pas dire : tests pass",
        "it's not true that all tests pass",
        "je n'ai pas vu que les tests passent",
    ],
)
def test_negation_ignoree(texte):
    assert verifier_affirmations(texte, [], "code", set(CFG.commandes)) == []


def test_dossier_homonyme_d_un_paquet_tiers_non_verifie(tmp_path):
    (tmp_path / "alembic" / "versions").mkdir(parents=True)
    (tmp_path / "alembic" / "env.py").write_text("")
    refs = [("backend/a.py", "python", "alembic.config")]
    assert verifier_references(tmp_path, refs, CFG) == []


def test_python_local_trouve_dans_une_autre_base(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("")
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    (tmp_path / "backend" / "tests" / "__init__.py").write_text("")
    (tmp_path / "backend" / "tests" / "helpers.py").write_text("")
    refs = [("backend/tests/a.py", "python", "tests.helpers")]
    assert verifier_references(tmp_path, refs, CFG) == []


def test_import_ts_resolutions_js_et_index(tmp_path):
    web = tmp_path / "web"
    (web / "lib").mkdir(parents=True)
    (web / "comp").mkdir()
    (web / "A.jsx").write_text("")
    (web / "lib" / "index.js").write_text("")
    (web / "comp" / "index.tsx").write_text("")
    (web / "a.ts").write_text("")
    (web / "m.mjs").write_text("")
    (web / "t.txt").write_text("")
    cibles = ("./A", "./lib", "./comp", "./a.js", "./m", "./t.txt?raw")
    assert verifier_references(tmp_path, [("web/b.ts", "ts", c) for c in cibles], CFG) == []


def test_import_ts_hors_de_l_espace_ignore(tmp_path):
    racine = tmp_path / "espace"
    (racine / "web").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("")
    refs = [
        ("web/a.ts", "ts", "../../absent"),
        ("web/a.ts", "ts", "../../secret.txt"),
        ("../x/a.ts", "ts", "./absent"),
    ]
    assert verifier_references(racine, refs, CFG) == []
