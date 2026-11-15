import asyncio
import itertools
import json
import logging
import subprocess
from pathlib import Path

import httpx
import pytest
from conftest import URL, FauxGitHub, FauxLanceur, FauxLLM, FauxNotifieur
from sqlalchemy import select

from portail.agents import Agent, Catalogue
from portail.config import Reglages
from portail.db import CommandeLancee, Etape, ExecutionDev, Message, Pipeline, Projet, Tache
from portail.dev import Orchestrateur
from portail.github import ErreurGitHub
from portail.moteur import Refus, creer_pipeline
from portail.notifications import Notifieur

CONFIG = """
image: img
chemins_tests: ["tests/**"]
commandes:
  installer: "installer"
  tests: "pytest"
  tests_cibles: "pytest {fichiers}"
"""
CIBLES = "pytest tests/test_x.py"
BRANCHE = "portail/tache-1-ajouter-l-equipe"


def git(cwd, *args: str) -> str:
    r = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )  # fmt: skip
    return r.stdout.strip()


def _agent(nom, role, outils, produit="travail"):
    return Agent(
        nom=nom, description=nom, modele="m", prompt_systeme=f"Tu es {nom}.",
        contexte_max=32768, produit=produit, role=role, outils=outils, tours_max=10,
    )  # fmt: skip


TOUS = ["lister", "lire", "chercher", "ecrire", "supprimer", "lancer"]
CATALOGUE = Catalogue(
    agents={
        "tests": _agent("tests", "tests", TOUS),
        "code": _agent("code", "code", TOUS),
        "revue": _agent("revue", "revue", ["lister", "lire", "chercher"], "verdict"),
    },
    pipelines={"dev": ["tests", "code", "revue"]},
)

LECTURE = ["lister", "lire", "chercher"]
CATALOGUE_D = Catalogue(
    agents={
        **CATALOGUE.agents,
        "challenger": _agent("challenger", "revue", LECTURE, "verdict").model_copy(
            update={"modele_si_meme": "autre"}
        ),
        "securite": _agent("securite", "revue", [*LECTURE, "lancer"], "verdict"),
        "doc": _agent("doc", "doc", [*LECTURE, "ecrire", "supprimer"]),
    },
    pipelines={"dev": ["tests", "code", "revue", "challenger", "securite", "doc"]},
)

_ids = itertools.count()


def appel(outil, **args):
    return {
        "content": None,
        "tool_calls": [
            {
                "id": f"a{next(_ids)}",
                "type": "function",
                "function": {"name": outil, "arguments": json.dumps(args)},
            }
        ],
    }


def texte(t):
    return {"content": t}


def verdict(decision, *remarques):
    return texte(json.dumps({"decision": decision, "remarques": list(remarques)}))


TESTS_OK = [appel("ecrire", chemin="tests/test_x.py", contenu="def test_x(): ..."), texte("ok")]
CODE_OK = [appel("ecrire", chemin="src/x.py", contenu="x = 1\n"), texte("fait")]


# revue, challenger, sécurité : ok ; doc : rien à changer
CONTROLES_OK = [verdict("ok"), verdict("ok"), verdict("ok"), texte("rien")]


class Monde:
    def __init__(self, tmp_path, sessions):
        nu = tmp_path / "origine.git"
        git(tmp_path, "init", "--bare", "-b", "main", str(nu))
        amont = tmp_path / "amont"
        git(tmp_path, "clone", str(nu), str(amont))
        (amont / "src").mkdir()
        (amont / "tests").mkdir()
        (amont / "src" / "a.py").write_text("a = 1\n")
        (amont / "tests" / "test_a.py").write_text("def test_a(): ...\n")
        (amont / "conftest.py").write_text("# racine\n")
        git(amont, "add", "-A")
        git(amont, "commit", "-m", "initial")
        git(amont, "push", "origin", "main")
        self.origine = nu
        self.sessions = sessions
        self.reglages = Reglages(
            database_url=URL, espaces_dir=tmp_path / "espaces", url_publique="https://portail.x"
        )
        self.llm = FauxLLM()
        self.lanceur = FauxLanceur(tmp_path / "espaces")
        self.github = FauxGitHub()
        self.notifieur = FauxNotifieur()
        self.orch = Orchestrateur(
            sessions, CATALOGUE, self.llm, self.lanceur, self.github, self.reglages,
            depot_de=lambda url: "nicolas/projet", notifieur=self.notifieur,
        )  # fmt: skip

    async def creer(self) -> int:
        async with self.sessions() as s:
            p = Projet(nom="p", depot_url=f"file://{self.origine}", config_execution=CONFIG)
            s.add(p)
            await s.flush()
            t = Tache(
                projet_id=p.id, titre="Ajouter l'équipe", description="Une équipe.",
                criteres=["x vaut 1"], fichiers=["src/x.py"], colonne="prete", rang=1000,
                origine="manuel",
            )  # fmt: skip
            s.add(t)
            await s.commit()
            return t.id

    async def lancer(self, tache_id: int = 1) -> int:
        async with self.sessions() as s:
            t = await s.get(Tache, tache_id)
            p = await self.orch.demarrer(s, t)
            await s.commit()
        await self.orch.executer(p.id)
        return p.id

    async def etat(self, pipeline_id: int):
        async with self.sessions() as s:
            ex = await s.scalar(select(ExecutionDev).where(ExecutionDev.pipeline_id == pipeline_id))
            return ex, await s.get(Tache, ex.tache_id), await s.get(Pipeline, pipeline_id)

    def auteurs(self, branche=BRANCHE) -> list[str]:
        return git(self.origine, "log", "--format=%ae", f"main..{branche}").split()

    def branches(self) -> str:
        return git(self.origine, "branch", "--list")


@pytest.fixture
async def monde(tmp_path, sessions):
    m = Monde(tmp_path, sessions)
    await m.creer()
    return m


async def test_parcours_complet_ouvre_une_pr(monde):
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok", "propre")]
    pid = await monde.lancer()
    ex, tache, pipeline = await monde.etat(pid)
    assert monde.auteurs() == ["agent-code@portail.local", "agent-tests@portail.local"]
    sujets = git(monde.origine, "log", "--format=%s", f"main..{BRANCHE}").splitlines()
    assert sujets == ["feat: Ajouter l'équipe", "test: Ajouter l'équipe"]
    pr = monde.github.prs[1]
    assert (pr["titre"], pr["branche"], pr["base"]) == ("Ajouter l'équipe", BRANCHE, "main")
    assert f"/projets/{tache.projet_id}/kanban" in pr["corps"]
    assert f"/pipelines/{pid}" in pr["corps"]
    assert "x vaut 1" in pr["corps"] and "propre" in pr["corps"]
    assert "Remarques non résolues" not in pr["corps"]
    assert (tache.colonne, tache.verrou) == ("en_revue", pid)
    assert pipeline.etat == "terminee"
    assert (ex.phase, ex.pr_numero, ex.pr_url) == ("fini", 1, pr["url"])
    assert ex.fichiers_tests == ["tests/test_x.py"]
    async with monde.sessions() as s:
        noms = (await s.scalars(select(CommandeLancee.nom).order_by(CommandeLancee.id))).all()
        etapes = (await s.scalars(select(Etape).order_by(Etape.ordre))).all()
    assert noms == ["installer", "tests_cibles", "installer", "tests_cibles", "tests"]
    assert [(e.agent, e.action) for e in etapes] == [
        ("portail", "preparation"), ("tests", None), ("portail", "rouge"), ("code", None),
        ("portail", "verification"), ("revue", None), ("portail", "pr"),
    ]  # fmt: skip
    assert all(e.etat == "terminee" for e in etapes)
    assert {"route": "nettoyer", "espace": "tache-1-1"} in monde.lanceur.appels


async def test_identifiants_d_un_agent_dev(monde):
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok", "propre")]
    pid = await monde.lancer()
    _ex, tache, _pipeline = await monde.etat(pid)
    par_agent = {}
    for a in monde.llm.appels:
        c = a["contexte"]
        par_agent.setdefault(c["agent"], c)
    tests, code = par_agent["tests"], par_agent["code"]
    assert (tests["pipeline"], tests["tache"]) == (pid, tache.id)
    assert tests["etape"] and tests["mission"] and code["mission"] != tests["mission"]
    assert code["etape"] != tests["etape"]


async def test_aucun_test_ecrit_bloque(monde):
    monde.lanceur.codes = {"pytest ": [5]}
    monde.llm.reponses = [appel("lancer", nom="tests_cibles"), texte("rien")]
    pid = await monde.lancer()
    _ex, tache, pipeline = await monde.etat(pid)
    assert tache.colonne == "bloquee" and tache.verrou is None
    assert tache.resume_blocage.startswith("aucun test écrit")
    assert pipeline.etat == "echouee"
    assert not (monde.reglages.espaces_dir / "tache-1-1").exists()
    assert BRANCHE not in monde.branches()


async def test_tests_qui_touche_src_est_annule(monde):
    def effet(d: Path):
        (d / "src" / "x.py").write_text("triche = 1\n")

    monde.lanceur.effets = {CIBLES: effet}
    monde.lanceur.codes = {CIBLES: [1, 1]}
    monde.llm.reponses = [
        appel("ecrire", chemin="tests/test_x.py", contenu="def test_x(): ..."),
        appel("lancer", nom="tests_cibles"),
        texte("ok"),
        *CODE_OK,
        verdict("ok"),
    ]
    await monde.lancer()
    sha = git(monde.origine, "log", "--format=%H", "--author=agent-tests", BRANCHE)
    fichiers = git(monde.origine, "show", "--name-only", "--format=", sha).split()
    assert fichiers == ["tests/test_x.py"]
    async with monde.sessions() as s:
        notes = (await s.scalars(select(Message.contenu).where(Message.role == "system"))).all()
    assert any("src/x.py" in n for n in notes)


async def test_rouge_qui_passe_renvoie_une_fois_puis_bloque(monde):
    monde.llm.reponses = [
        *TESTS_OK,
        appel("ecrire", chemin="tests/test_y.py", contenu="def test_y(): ..."),
        texte("ok"),
    ]
    pid = await monde.lancer()
    _ex, tache, _pipeline = await monde.etat(pid)
    assert tache.colonne == "bloquee"
    assert tache.resume_blocage.startswith("les tests passent déjà")
    deuxieme = monde.llm.appels[2]["messages"]
    assert any("passent déjà" in (m["content"] or "") for m in deuxieme)


async def test_verification_rouge_bloque_avec_sortie(monde):
    monde.lanceur.codes = {CIBLES: [1], "pytest": [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK]
    pid = await monde.lancer()
    _ex, tache, pipeline = await monde.etat(pid)
    assert tache.colonne == "bloquee"
    assert "sortie de pytest" in tache.resume_blocage
    assert pipeline.etat == "echouee"
    assert monde.github.prs == {}


async def test_verification_efface_les_ignores_et_reinstalle(monde):
    vus = []

    def piege(d: Path):  # une commande de l'agent de code écrit dans .venv/ (ignoré)
        (d / ".venv").mkdir(exist_ok=True)
        (d / ".venv" / "sitecustomize.py").write_text("import os\n")

    def constat(d: Path):
        vus.append((d / ".venv").exists())

    def suite(d: Path):  # 1re fois (après le rouge) : l'agent de code ; ensuite : la vérification
        (constat if len(vus) > 1 else piege)(d)

    monde.lanceur.effets = {"pytest": suite, CIBLES: constat}
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [
        *TESTS_OK, appel("lancer", nom="tests"), texte("fait"), verdict("ok"),
    ]  # fmt: skip
    pid = await monde.lancer()
    _ex, tache, _pipeline = await monde.etat(pid)
    assert tache.colonne == "en_revue"
    assert vus == [False, False, False]  # rouge, puis tests_cibles et tests de la vérification
    async with monde.sessions() as s:
        etape = await s.scalar(select(Etape.id).where(Etape.action == "verification"))
        noms = (
            await s.scalars(
                select(CommandeLancee.nom)
                .where(CommandeLancee.etape_id == etape)
                .order_by(CommandeLancee.id)
            )
        ).all()
    assert noms == ["installer", "tests_cibles", "tests"]


async def test_installation_echouee_en_verification_bloque(monde):
    # le blocage n'arrive qu'après `renvois_max` renvois au code
    monde.lanceur.codes = {CIBLES: [1], "installer": [0, 1, 1, 1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, texte("rien"), texte("rien")]
    pid = await monde.lancer()
    ex, tache, _pipeline = await monde.etat(pid)
    assert ex.renvois == 2
    assert tache.resume_blocage.startswith("installation échouée")


async def test_installation_echouee_renvoie_au_code(monde):
    monde.lanceur.codes = {CIBLES: [1], "installer": [0, 1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, texte("paquet retiré"), verdict("ok")]
    pid = await monde.lancer()
    ex, _tache, pipeline = await monde.etat(pid)
    assert (pipeline.etat, ex.renvois) == ("terminee", 1)
    code2 = monde.llm.appels[4]["messages"]
    assert any("paquet inventé" in (m["content"] or "") for m in code2)


@pytest.mark.parametrize(
    ("code", "raison"),
    [(3, "commande de tests invalide"), (4, "commande de tests invalide"), (5, "aucun test écrit")],
)
async def test_rouge_code_reserve_bloque(monde, code, raison):
    monde.lanceur.codes = {CIBLES: [code]}
    monde.llm.reponses = [*TESTS_OK]
    pid = await monde.lancer()
    _ex, tache, _pipeline = await monde.etat(pid)
    assert tache.colonne == "bloquee"
    assert tache.resume_blocage.startswith(raison)


@pytest.mark.parametrize("code", [1, 2, 101])
async def test_rouge_echec_vaut_rouge(monde, code):
    # pytest 1 (échecs) et 2 (erreur de collection : module absent), cargo 101, vitest 1
    monde.lanceur.codes = {CIBLES: [code]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok")]
    pid = await monde.lancer()
    _ex, tache, _pipeline = await monde.etat(pid)
    assert tache.colonne == "en_revue"


async def test_reprise_arrete_l_ancien_conteneur_puis_reinstalle(monde):
    monde.llm.reponses = [asyncio.Event()]
    async with monde.sessions() as s:
        pid = (await monde.orch.demarrer(s, await s.get(Tache, 1))).id
        await s.commit()
    tache = asyncio.create_task(monde.orch.executer(pid))
    async with asyncio.timeout(15):
        while len(monde.llm.appels) < 1:
            await asyncio.sleep(0.02)
    tache.cancel()  # arrêt brutal du portail pendant la phase `tests`
    await asyncio.wait([tache])
    espace = monde.reglages.espaces_dir / "tache-1-1"
    (espace / ".venv").mkdir()
    (espace / ".venv" / "sitecustomize.py").write_text("piege")
    monde.lanceur.appels.clear()
    monde.llm.reponses = [texte("rien")]
    await monde.orch.executer(pid)  # reprise : aucun test écrit, bloquée
    routes = [(a["route"], a.get("commande")) for a in monde.lanceur.appels]
    assert routes[:2] == [("arreter", None), ("lancer", "installer")]
    _ex, tache, _pipeline = await monde.etat(pid)
    assert tache.resume_blocage.startswith("aucun test écrit")


async def test_pr_reverifie_la_protection_avant_de_pousser(monde, monkeypatch):
    from portail import dev

    vraie, appels = dev.verifier_commits_code, []

    async def verifier(espace, base, cfg):
        appels.append(1)
        return await vraie(espace, base, cfg) if len(appels) == 1 else ["tests/test_x.py"]

    monkeypatch.setattr(dev, "verifier_commits_code", verifier)
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok")]
    pid = await monde.lancer()
    _ex, tache, _pipeline = await monde.etat(pid)
    assert tache.resume_blocage.startswith("protection des tests : tests/test_x.py")
    assert BRANCHE not in monde.branches()
    assert monde.github.prs == {}


async def test_glob_protege_restaure_pour_code(monde):
    def effet(d: Path):
        (d / "conftest.py").write_text("# triche\n")
        (d / "src" / "conftest.py").write_text("# triche\n")

    monde.lanceur.effets = {"pytest": effet}
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [
        *TESTS_OK,
        appel("lancer", nom="tests"),
        *CODE_OK,
        verdict("ok"),
    ]
    pid = await monde.lancer()
    _ex, _tache, pipeline = await monde.etat(pid)
    assert pipeline.etat == "terminee"
    racine = monde.reglages.espaces_dir / "tache-1-1"
    assert (racine / "conftest.py").read_text() == "# racine\n"
    assert not (racine / "src" / "conftest.py").exists()
    async with monde.sessions() as s:
        sorties = (
            await s.scalars(select(Message.contenu).where(Message.outil == "lancer(tests)"))
        ).all()
    assert "[fichiers de tests restaurés : conftest.py, src/conftest.py]" in sorties[0]
    ro = [a["lecture_seule"] for a in monde.lanceur.appels if a.get("commande") == "pytest"]
    assert ro and all(r == ["tests"] for r in ro)


def triche(d: Path):
    """Commit fabriqué de l'agent de code qui touche un test (impossible en vrai : .git en RO)."""
    (d / "tests" / "test_z.py").write_text("triche\n")
    git(d, "add", "tests/test_z.py")
    subprocess.run(
        ["git", "-c", "user.name=agent-code", "-c", "user.email=agent-code@portail.local",
         "commit", "-qm", "triche"],
        cwd=d, check=True,
    )  # fmt: skip


async def test_violation_protection_bloque_sans_push(monde):
    # commit fabriqué pendant le travail de l'agent de code ; la suite échoue en plus :
    # la protection est vérifiée avant les commandes de la vérification
    monde.lanceur.effets = {"pytest": triche}
    monde.lanceur.codes = {CIBLES: [1], "pytest": [0, 1]}
    monde.llm.reponses = [*TESTS_OK, appel("lancer", nom="tests"), texte("fait")]
    pid = await monde.lancer()
    _ex, tache, _pipeline = await monde.etat(pid)
    assert tache.colonne == "bloquee"
    assert tache.resume_blocage.startswith("protection des tests : tests/test_z.py")
    assert BRANCHE not in monde.branches()


async def test_verification_rouge_avec_violation_ne_pousse_pas(monde):
    # la violation naît pendant `tests` de la vérification, qui échoue : blocage
    # « vérification échouée », et bloquer ne pousse pas pour autant
    monde.lanceur.effets = {"pytest": triche}
    monde.lanceur.codes = {CIBLES: [1], "pytest": [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK]
    pid = await monde.lancer()
    _ex, tache, _pipeline = await monde.etat(pid)
    assert tache.resume_blocage.startswith("vérification échouée (tests)")
    assert "branche poussée" not in tache.resume_blocage
    assert BRANCHE not in monde.branches()


async def test_titre_de_tache_absent_des_journaux(monde, caplog):
    # la branche porte le slug du titre (en minuscules) : elle ne doit jamais être journalisée
    async with monde.sessions() as s:
        (await s.get(Tache, 1)).titre = "MarqueurTitre"
        await s.commit()
    monde.lanceur.effets = {"pytest": triche}
    monde.lanceur.codes = {CIBLES: [1], "pytest": [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK]
    with caplog.at_level(logging.DEBUG):
        await monde.lancer()
    assert "non poussée" in caplog.text  # le chemin concerné a bien été pris
    assert "marqueurtitre" not in caplog.text.lower()


async def test_duree_max_apres_violation_ne_pousse_pas(monde):
    monde.reglages.duree_max_tache_s = 3
    monde.lanceur.effets = {"pytest": triche}
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [*TESTS_OK, appel("lancer", nom="tests"), asyncio.Event()]
    pid = await monde.lancer()
    _ex, tache, _pipeline = await monde.etat(pid)
    assert tache.resume_blocage.startswith("durée maximale dépassée")
    assert BRANCHE not in monde.branches()


async def test_bloquer_sans_deplacement_possible_leve_le_verrou(monde, monkeypatch):
    from portail import dev

    vrai = dev.deplacer_tache

    async def panne(s, t, colonne, *a):
        if colonne == "bloquee":
            raise RuntimeError("panne")
        return await vrai(s, t, colonne, *a)

    monkeypatch.setattr(dev, "deplacer_tache", panne)
    monde.github.protegee = set()
    pid = await monde.lancer()
    _ex, tache, pipeline = await monde.etat(pid)
    assert (tache.colonne, tache.verrou) == ("bloquee", None)
    assert tache.resume_blocage == "branche par défaut non protégée"
    assert pipeline.etat == "echouee"


async def test_bloquer_sans_execution_ne_leve_pas(monde):
    async with monde.sessions() as s:
        p = Pipeline(projet_id=1, type="dev", etat="en_cours")
        s.add(p)
        await s.commit()
    await monde.orch.bloquer(p.id, "x")
    await monde.orch.bloquer(999, "x")
    async with monde.sessions() as s:
        assert (await s.get(Pipeline, p.id)).etat == "echouee"


async def test_revue_renvoie_au_code_puis_ok(monde):
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [
        *TESTS_OK,
        *CODE_OK,
        verdict("renvoyer_code", "renommer x"),
        appel("ecrire", chemin="src/x.py", contenu="x = 2\n"),
        texte("corrigé"),
        verdict("ok"),
    ]
    pid = await monde.lancer()
    ex, _tache, pipeline = await monde.etat(pid)
    assert ex.renvois == 1
    assert pipeline.etat == "terminee" and monde.github.prs
    async with monde.sessions() as s:
        etapes = (await s.scalars(select(Etape).order_by(Etape.ordre))).all()
    agents = [e.action or e.agent for e in etapes]
    assert agents.count("rouge") == 1
    assert agents[agents.index("revue") + 1] == "code"
    code2 = monde.llm.appels[5]["messages"]
    assert any("renommer x" in (m["content"] or "") for m in code2)
    assert monde.auteurs() == [
        "agent-code@portail.local", "agent-code@portail.local", "agent-tests@portail.local"
    ]  # fmt: skip


async def test_renvoi_aux_tests_rouge_sur_les_seuls_fichiers_du_renvoi(monde):
    monde.lanceur.codes = {CIBLES: [1], "pytest tests/test_y.py": [1]}
    monde.llm.reponses = [
        *TESTS_OK,
        *CODE_OK,
        verdict("renvoyer_tests", "tester y"),
        appel("ecrire", chemin="tests/test_y.py", contenu="def test_y(): ..."),
        texte("ajouté"),
        texte("fait"),
        verdict("ok"),
    ]
    pid = await monde.lancer()
    ex, _tache, pipeline = await monde.etat(pid)
    assert pipeline.etat == "terminee"
    assert ex.fichiers_tests == ["tests/test_x.py", "tests/test_y.py"]
    assert ex.fichiers_rouge == []
    async with monde.sessions() as s:
        actions = (await s.scalars(select(Etape.action).order_by(Etape.ordre))).all()
        rouges = (
            await s.scalars(
                select(CommandeLancee.nom)
                .join(Etape, Etape.id == CommandeLancee.etape_id)
                .where(Etape.action == "rouge")
            )
        ).all()
    assert actions.count("rouge") == 2 and rouges == ["tests_cibles", "tests_cibles"]
    lances = [
        a["commande"] for a in monde.lanceur.appels if a.get("commande", "").startswith("pytest ")
    ]
    # rouge, vérification, rouge du renvoi (test_y seul), vérification
    assert lances == [
        CIBLES, CIBLES, "pytest tests/test_y.py", "pytest tests/test_x.py tests/test_y.py"
    ]  # fmt: skip
    code2 = monde.llm.appels[-2]["messages"]  # l'agent de code après le rouge du renvoi
    assert any("tester y" in (m["content"] or "") for m in code2)


async def test_trois_renvois_ouvre_quand_meme_avec_remarques(monde):
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [
        *TESTS_OK,
        *CODE_OK,
        verdict("renvoyer_code", "a"),
        texte("rien"),
        verdict("renvoyer_code", "b"),
        texte("rien"),
        verdict("renvoyer_code", "c toujours faux"),
    ]
    pid = await monde.lancer()
    ex, _tache, pipeline = await monde.etat(pid)
    assert ex.renvois == 2
    assert pipeline.etat == "terminee"
    corps = monde.github.prs[1]["corps"]
    assert "Remarques non résolues" in corps and "c toujours faux" in corps


async def test_verdict_illisible_devient_note(monde):
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, texte("bof"), texte("toujours pas du JSON")]
    pid = await monde.lancer()
    ex, _tache, pipeline = await monde.etat(pid)
    assert pipeline.etat == "terminee"
    assert monde.llm.appels[-1]["response_format"]["type"] == "json_schema"
    assert ex.notes == [{"agent": "revue", "texte": "verdict illisible de revue"}]
    corps = monde.github.prs[1]["corps"]
    assert "## Notes des contrôles" in corps and "verdict illisible de revue" in corps
    assert "Remarques non résolues" not in corps


async def test_branche_non_protegee_bloque(monde):
    monde.github.protegee = set()
    pid = await monde.lancer()
    _ex, tache, pipeline = await monde.etat(pid)
    assert tache.resume_blocage.startswith("branche par défaut non protégée")
    assert tache.colonne == "bloquee" and pipeline.etat == "echouee"
    assert monde.llm.appels == []


async def test_delai_depasse_en_verification_bloque(monde):
    monde.lanceur.codes = {CIBLES: [1]}
    monde.lanceur.delais = {"pytest"}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK]
    pid = await monde.lancer()
    _ex, tache, _pipeline = await monde.etat(pid)
    assert tache.colonne == "bloquee"
    assert "délai dépassé" in tache.resume_blocage
    async with monde.sessions() as s:
        c = await s.scalar(select(CommandeLancee).where(CommandeLancee.nom == "tests"))
    assert c.delai_depasse and c.code is None


async def test_duree_max_tache(monde):
    monde.reglages.duree_max_tache_s = 0.1
    monde.llm.reponses = [asyncio.Event()]
    pid = await monde.lancer()
    _ex, tache, pipeline = await monde.etat(pid)
    assert tache.resume_blocage.startswith("durée maximale dépassée")
    assert pipeline.etat == "echouee"
    async with monde.sessions() as s:
        erreurs = (await s.scalars(select(Etape.erreur).where(Etape.etat == "echouee"))).all()
    assert erreurs == ["durée maximale dépassée"]


async def test_blocage_pousse_la_branche_sans_pr(monde):
    monde.lanceur.codes = {CIBLES: [1], "pytest": [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK]
    pid = await monde.lancer()
    _ex, tache, _pipeline = await monde.etat(pid)
    assert monde.auteurs() == ["agent-code@portail.local", "agent-tests@portail.local"]
    assert monde.github.prs == {}
    assert f"branche poussée : {BRANCHE}" in tache.resume_blocage
    assert {"route": "nettoyer", "espace": "tache-1-1"} in monde.lanceur.appels


async def test_relance_ferme_l_ancienne_pr(monde):
    monde.lanceur.codes = {CIBLES: [1, 0, 1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok")] * 2
    await monde.lancer()
    async with monde.sessions() as s:
        t = await s.get(Tache, 1)
        t.verrou, t.colonne = None, "prete"
        await s.commit()
    pid = await monde.lancer()
    ex, _tache, _pipeline = await monde.etat(pid)
    assert (ex.n, ex.branche, ex.espace) == (2, BRANCHE + "-2", "tache-1-2")
    assert monde.github.etats == {1: "fermee", 2: "ouverte"}
    assert monde.github.commentaires == [(1, f"Remplacée par {monde.github.prs[2]['url']}")]


async def test_erreur_github_bloque(monde):
    monde.lanceur.codes = {CIBLES: [1]}

    async def casse(*a):
        raise ErreurGitHub("GitHub 500")

    monde.github.creer_pr = casse
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok")]
    pid = await monde.lancer()
    _ex, tache, pipeline = await monde.etat(pid)
    assert tache.resume_blocage.startswith("GitHub 500")
    assert tache.verrou is None and pipeline.etat == "echouee"


async def test_creer_pipeline_refuse_dev(sessions):
    async with sessions() as s:
        with pytest.raises(Refus) as e:
            await creer_pipeline(s, CATALOGUE, 1, "dev")
    assert e.value.code == 422


async def test_pr_ouverte_notifie(monde):
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok", "propre")]
    await monde.lancer()
    (envoi,) = monde.notifieur.envoyes
    assert envoi["titre"] == "Portail — tâche T1" and envoi["message"] == "PR ouverte"
    assert envoi["lien"] == monde.github.prs[1]["url"]


async def test_blocage_notifie_sans_raison(monde):
    monde.lanceur.codes = {CIBLES: [1], "pytest": [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK]
    await monde.lancer()
    (envoi,) = monde.notifieur.envoyes
    assert envoi["titre"] == "Portail — tâche T1" and envoi["message"] == "Bloquée"
    assert envoi["lien"] == "https://portail.x/projets/1/kanban"


async def test_notification_sans_contenu(monde):
    async with monde.sessions() as s:
        (await s.get(Tache, 1)).titre = "MARQUEUR"
        await s.commit()
    monde.lanceur.codes = {CIBLES: [1], "pytest": [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK]
    await monde.lancer()
    (envoi,) = monde.notifieur.envoyes
    assert "MARQUEUR" not in envoi["titre"] + envoi["message"]
    assert envoi["message"] == "Bloquée"


async def test_corps_pr_liens_absolus(monde):
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok", "propre")]
    await monde.lancer()
    assert "https://portail.x/projets/1/kanban" in monde.github.prs[1]["corps"]


async def test_corps_pr_sans_url_publique(monde):
    monde.reglages.url_publique = ""
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok", "propre")]
    await monde.lancer()
    assert "/projets/" not in monde.github.prs[1]["corps"]


async def test_ntfy_en_panne_n_arrete_rien(monde):
    def panne(requete):
        raise httpx.ConnectError("non")

    monde.orch._notifieur = Notifieur("http://ntfy", "portail", "sec", httpx.MockTransport(panne))
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok", "propre")]
    await monde.lancer()
    assert 1 in monde.github.prs


CONFIG_D = CONFIG + '  securite: "audit"\n'


@pytest.fixture
async def monde_d(tmp_path, sessions):
    m = Monde(tmp_path, sessions)
    m.orch = Orchestrateur(
        sessions, CATALOGUE_D, m.llm, m.lanceur, m.github, m.reglages,
        depot_de=lambda url: "nicolas/projet", notifieur=m.notifieur,
    )  # fmt: skip
    await m.creer()
    async with sessions() as s:
        (await s.get(Projet, 1)).config_execution = CONFIG_D
        await s.commit()
    m.lanceur.codes = {CIBLES: [1]}
    return m


async def etapes_apres(monde, agent: str, action: str | None = None) -> list[str]:
    """Agents (ou actions du portail) des étapes après la première `agent`/`action`."""
    async with monde.sessions() as s:
        etapes = (await s.scalars(select(Etape).order_by(Etape.id))).all()  # tous pipelines
    noms = [e.action or e.agent for e in etapes]
    return noms[noms.index(action or agent) + 1 :]


def appels_de(monde, agent: str) -> list[dict]:
    return [
        a for a in monde.llm.appels if a["messages"][0]["content"].startswith(f"Tu es {agent}.")
    ]


async def test_tous_les_controles_tournent_dans_l_ordre(monde_d):
    amont = monde_d.origine.parent / "amont"
    (amont / "AGENTS.md").write_text("Toujours des docstrings.\n")
    git(amont, "add", "-A")
    git(amont, "commit", "-m", "règles")
    git(amont, "push", "origin", "main")
    monde_d.llm.reponses = [*TESTS_OK, *CODE_OK, *CONTROLES_OK]
    pid = await monde_d.lancer()
    _ex, _tache, pipeline = await monde_d.etat(pid)
    assert pipeline.etat == "terminee"
    assert await etapes_apres(monde_d, "verification") == [
        "revue", "faits", "challenger", "securite", "doc", "pr"
    ]  # fmt: skip
    (challenger,) = appels_de(monde_d, "challenger")
    annexes = "\n".join(m["content"] or "" for m in challenger["messages"])
    assert "Toujours des docstrings." in annexes and "Diff de la tâche" in annexes
    (revue,) = appels_de(monde_d, "revue")
    assert "Toujours des docstrings." not in "\n".join(
        m["content"] or "" for m in revue["messages"]
    )


async def test_renvoi_du_challenger_reprend_tout(monde_d):
    monde_d.llm.reponses = [
        *TESTS_OK, *CODE_OK,
        verdict("ok"), verdict("renvoyer_code", "cas limite"),
        texte("corrigé"),
        *CONTROLES_OK,
    ]  # fmt: skip
    pid = await monde_d.lancer()
    ex, _tache, pipeline = await monde_d.etat(pid)
    assert pipeline.etat == "terminee" and ex.renvois == 1
    assert await etapes_apres(monde_d, "challenger") == [
        "code", "verification", "revue", "faits", "challenger", "securite", "doc", "pr"
    ]  # fmt: skip
    code2 = appels_de(monde_d, "code")[-1]["messages"]
    assert any("cas limite" in (m["content"] or "") for m in code2)


async def test_compteur_partage(monde_d):
    monde_d.llm.reponses = [
        *TESTS_OK, *CODE_OK,
        verdict("renvoyer_code", "a"),
        texte("rien"),
        verdict("ok"), verdict("ok"), verdict("renvoyer_code", "b"),
        texte("rien"),
        verdict("ok"), verdict("renvoyer_code", "c toujours faux"), verdict("ok"), texte("rien"),
    ]  # fmt: skip
    pid = await monde_d.lancer()
    ex, _tache, pipeline = await monde_d.etat(pid)
    assert pipeline.etat == "terminee" and ex.renvois == 2
    assert ex.remarques == ["challenger : c toujours faux"]
    noms = await etapes_apres(monde_d, "securite")  # après le renvoi de la sécurité
    assert noms[-5:] == ["faits", "challenger", "securite", "doc", "pr"]
    corps = monde_d.github.prs[1]["corps"]
    assert "Remarques non résolues" in corps and "c toujours faux" in corps


async def test_modele_du_challenger(monde_d):
    monde_d.llm.reponses = [*TESTS_OK, *CODE_OK, *CONTROLES_OK]
    await monde_d.lancer()
    assert {a["modele"] for a in appels_de(monde_d, "code")} == {"m"}
    assert [a["modele"] for a in appels_de(monde_d, "challenger")] == ["autre"]
    assert [a["modele"] for a in appels_de(monde_d, "revue")] == ["m"]


async def test_modele_du_challenger_garde_pour_la_relance(monde_d):
    monde_d.llm.reponses = [
        *TESTS_OK, *CODE_OK, verdict("ok"), texte("bof"), texte("pas du JSON"), verdict("ok"),
        texte("rien"),
    ]  # fmt: skip
    pid = await monde_d.lancer()
    ex, _tache, _pipeline = await monde_d.etat(pid)
    assert [a["modele"] for a in appels_de(monde_d, "challenger")] == ["autre", "autre"]
    assert ex.notes == [{"agent": "challenger", "texte": "verdict illisible de challenger"}]


async def test_securite_lance_en_lecture_seule(monde_d):
    monde_d.llm.reponses = [
        *TESTS_OK, *CODE_OK,
        verdict("ok"), verdict("ok"),
        appel("lancer", nom="securite"), verdict("ok"),
        texte("rien"),
    ]  # fmt: skip
    pid = await monde_d.lancer()
    _ex, _tache, pipeline = await monde_d.etat(pid)
    assert pipeline.etat == "terminee"
    (audit,) = [a for a in monde_d.lanceur.appels if a.get("commande") == "audit"]
    assert audit["tout_lecture_seule"] is True
    autres = [a for a in monde_d.lanceur.appels if a["route"] == "lancer" and a is not audit]
    assert not any(a["tout_lecture_seule"] for a in autres)


@pytest.mark.parametrize("ecrit", [True, False])
async def test_doc_commit_seulement_si_changement(monde_d, ecrit):
    doc = [appel("ecrire", chemin="README.md", contenu="# Équipe\n")] if ecrit else []
    monde_d.llm.reponses = [
        *TESTS_OK, *CODE_OK, verdict("ok"), verdict("ok"), verdict("ok"), *doc, texte("fait"),
    ]  # fmt: skip
    pid = await monde_d.lancer()
    _ex, _tache, pipeline = await monde_d.etat(pid)
    assert pipeline.etat == "terminee"
    sujets = git(monde_d.origine, "log", "--format=%s", f"main..{BRANCHE}").splitlines()
    if ecrit:
        assert monde_d.auteurs()[0] == "agent-doc@portail.local"
        assert sujets[0] == "docs: Ajouter l'équipe"
    else:
        assert "agent-doc@portail.local" not in monde_d.auteurs()


async def test_doc_hors_chemins_restaure(monde_d):
    vrai = monde_d.llm.completer
    espace = monde_d.reglages.espaces_dir / "tache-1-1"

    async def completer(modele, messages, *a, **k):
        if messages[0]["content"].startswith("Tu es doc."):  # écrit hors des outils
            (espace / "src" / "a.py").write_text("triche = 1\n")
            (espace / "notes.txt").write_text("triche\n")
        return await vrai(modele, messages, *a, **k)

    monde_d.llm.completer = completer
    monde_d.llm.reponses = [
        *TESTS_OK, *CODE_OK, verdict("ok"), verdict("ok"), verdict("ok"),
        appel("ecrire", chemin="docs/equipe.md", contenu="# Équipe\n"), texte("fait"),
    ]  # fmt: skip
    pid = await monde_d.lancer()
    _ex, _tache, pipeline = await monde_d.etat(pid)
    assert pipeline.etat == "terminee"
    sha = git(monde_d.origine, "log", "-1", "--format=%H", "--author=agent-doc", BRANCHE)
    assert git(monde_d.origine, "show", "--name-only", "--format=", sha).split() == [
        "docs/equipe.md"
    ]
    assert git(monde_d.origine, "show", f"{BRANCHE}:src/a.py") == "a = 1"
    async with monde_d.sessions() as s:
        notes = (await s.scalars(select(Message.contenu).where(Message.role == "system"))).all()
    assert any("src/a.py" in n and "notes.txt" in n for n in notes)


async def test_relance_en_controles_reprend_au_bon_index(monde_d):
    monde_d.llm.reponses = [
        *TESTS_OK, *CODE_OK,
        verdict("renvoyer_code", "a"), texte("rien"),
        verdict("ok"), asyncio.Event(),  # arrêt pendant le challenger
    ]  # fmt: skip
    async with monde_d.sessions() as s:
        pid = (await monde_d.orch.demarrer(s, await s.get(Tache, 1))).id
        await s.commit()
    tache = asyncio.create_task(monde_d.orch.executer(pid))
    async with asyncio.timeout(15):
        while len(appels_de(monde_d, "challenger")) < 1:
            await asyncio.sleep(0.02)
    tache.cancel()  # arrêt brutal du portail pendant le 2e contrôle
    await asyncio.wait([tache])
    ex, _tache, _pipeline = await monde_d.etat(pid)
    assert (ex.phase, ex.controle_courant, ex.renvois) == ("controles", 1, 1)
    monde_d.llm.reponses = [verdict("ok"), verdict("ok"), texte("rien")]
    await monde_d.orch.executer(pid)
    ex, _tache, pipeline = await monde_d.etat(pid)
    assert pipeline.etat == "terminee" and ex.renvois == 1
    assert await etapes_apres(monde_d, "portail", "reprise") == [
        "faits", "challenger", "securite", "doc", "pr"
    ]  # fmt: skip
    assert len(appels_de(monde_d, "revue")) == 2  # rien de rejoué


async def test_renvoi_aux_tests_deja_verts_aboutit(monde):
    monde.lanceur.codes = {CIBLES: [1]}  # le nouveau test passe : le code gère déjà le cas
    monde.llm.reponses = [
        *TESTS_OK,
        *CODE_OK,
        verdict("renvoyer_tests", "tester le cas y"),
        appel("ecrire", chemin="tests/test_y.py", contenu="def test_y(): ..."),
        texte("ajouté"),
        verdict("ok"),
    ]
    pid = await monde.lancer()
    ex, tache, pipeline = await monde.etat(pid)
    assert (pipeline.etat, tache.colonne) == ("terminee", "en_revue") and monde.github.prs
    assert (ex.renvois, ex.fichiers_rouge) == (1, [])
    assert await etapes_apres(monde, "revue") == ["tests", "rouge", "verification", "revue", "pr"]


async def test_regles_du_challenger_lues_a_la_base(monde_d):
    amont = monde_d.origine.parent / "amont"
    (amont / "AGENTS.md").write_text("Règle de base.\n")
    git(amont, "add", "-A")
    git(amont, "commit", "-m", "règles")
    git(amont, "push", "origin", "main")
    monde_d.llm.reponses = [
        *TESTS_OK,
        appel("ecrire", chemin="AGENTS.md", contenu="Règle de l'auteur.\n"),
        *CODE_OK,
        *CONTROLES_OK,
    ]
    await monde_d.lancer()
    (challenger,) = appels_de(monde_d, "challenger")
    annexes = "\n".join(m["content"] or "" for m in challenger["messages"])
    assert "Règles du dépôt (AGENTS.md) :\n\nRègle de base." in annexes
    assert "Règles du dépôt (AGENTS.md) :\n\nRègle de l'auteur." not in annexes


def verdict_note(decision, note):
    return texte(json.dumps({"decision": decision, "remarques": ["r"], "notes": [note]}))


async def test_notes_d_un_controle_rejoue_dedoublonnees(monde):
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [
        *TESTS_OK,
        *CODE_OK,
        verdict_note("renvoyer_code", "nommage"),
        texte("corrigé"),
        verdict_note("ok", "nommage"),
    ]
    pid = await monde.lancer()
    ex, _tache, _pipeline = await monde.etat(pid)
    assert ex.notes == [{"agent": "revue", "texte": "nommage"}]
    assert monde.github.prs[1]["corps"].count("nommage") == 1


CONFIG_LINT = CONFIG_D + '  lint: "lint"\n'


async def monde_lint(monde_d, codes_lint):
    async with monde_d.sessions() as s:
        (await s.get(Projet, 1)).config_execution = CONFIG_LINT
        await s.commit()
    monde_d.lanceur.codes["lint"] = codes_lint
    return monde_d


def lints(monde):
    return [a for a in monde.lanceur.appels if a.get("commande") == "lint"]


async def test_lint_dette_existante_note_seulement(monde_d):
    await monde_lint(monde_d, [1, 1])  # échoue déjà sur la base
    monde_d.llm.reponses = [*TESTS_OK, *CODE_OK, *CONTROLES_OK]
    pid = await monde_d.lancer()
    ex, _tache, pipeline = await monde_d.etat(pid)
    assert (pipeline.etat, ex.renvois, ex.lint_base_ok) == ("terminee", 0, False)
    assert [n["agent"] for n in ex.notes] == ["faits"] and "dette existante" in ex.notes[0]["texte"]
    assert len(lints(monde_d)) == 2 and all(a["tout_lecture_seule"] for a in lints(monde_d))
    (challenger,) = appels_de(monde_d, "challenger")
    assert "dette existante" in "\n".join(m["content"] or "" for m in challenger["messages"])


async def test_lint_nouveau_bloque(monde_d):
    await monde_lint(monde_d, [0, 1])  # propre sur la base, cassé par la tâche
    monde_d.llm.reponses = [
        *TESTS_OK, *CODE_OK, verdict("ok"),
        texte("lint corrigé"),
        *CONTROLES_OK,
    ]  # fmt: skip
    pid = await monde_d.lancer()
    ex, _tache, pipeline = await monde_d.etat(pid)
    assert (pipeline.etat, ex.renvois, ex.lint_base_ok) == ("terminee", 1, True)
    assert ex.notes == [] and len(appels_de(monde_d, "challenger")) == 1
    code2 = appels_de(monde_d, "code")[-1]["messages"]
    assert any("passait sur la base" in (m["content"] or "") for m in code2)


async def test_faits_bloquants_renvoient_avant_le_challenger(monde_d):
    monde_d.llm.reponses = [
        *TESTS_OK,
        appel("ecrire", chemin="src/x.py", contenu="from x.faux import y\n"), texte("fait"),
        verdict("ok"),
        appel("ecrire", chemin="src/x.py", contenu="x = 1\n"), texte("corrigé"),
        *CONTROLES_OK,
    ]  # fmt: skip
    pid = await monde_d.lancer()
    ex, _tache, pipeline = await monde_d.etat(pid)
    assert (pipeline.etat, ex.renvois) == ("terminee", 1)
    assert await etapes_apres(monde_d, "revue") == [
        "faits", "code", "verification", "revue", "faits", "challenger", "securite", "doc", "pr"
    ]  # fmt: skip
    (challenger,) = appels_de(monde_d, "challenger")
    assert "Faits vérifiés par le portail" in "\n".join(
        m["content"] or "" for m in challenger["messages"]
    )
    code2 = appels_de(monde_d, "code")[-1]["messages"]
    assert any("import x.faux introuvable" in (m["content"] or "") for m in code2)


async def test_affirmation_prouvee_par_la_verification_ne_renvoie_pas(monde_d):
    # la phase `verification` vient de faire passer les tests : l'affirmation est vraie
    monde_d.llm.reponses = [
        *TESTS_OK,
        appel("ecrire", chemin="src/x.py", contenu="x = 1\n"), texte("Fait, les tests passent."),
        *CONTROLES_OK,
    ]  # fmt: skip
    pid = await monde_d.lancer()
    ex, _tache, pipeline = await monde_d.etat(pid)
    assert (pipeline.etat, ex.renvois) == ("terminee", 0)
