import asyncio
import json

import pytest
from asgi_lifespan import LifespanManager
from conftest import commentaire
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from test_dev import (
    BRANCHE,
    CATALOGUE,
    CATALOGUE_D,
    CIBLES,
    CODE_OK,
    CONFIG_D,
    CONTROLES_OK,
    TESTS_OK,
    Monde,
    _agent,
    appel,
    appels_de,
    etapes_apres,
    git,
    texte,
    verdict,
)

from portail.agents import Catalogue
from portail.api import create_app
from portail.db import CommentairePris, Etape, ExecutionDev, Pipeline, Projet, Tache
from portail.dev import MANIFESTE_A_NICOLAS, Orchestrateur, lire_tri
from portail.github import ErreurGitHub

CATALOGUE_REPRISE = Catalogue(
    agents={
        **CATALOGUE.agents,
        "tri": _agent("tri", "revue", ["lister", "lire", "chercher"], "verdict"),
    },
    pipelines=CATALOGUE.pipelines,
)
PYPROJECT = '[project]\nname = "x"\n\n[tool.pytest.ini_options]\naddopts = "-q"\n'


def tri(*classements) -> dict:
    return texte(
        json.dumps(
            {"commentaires": [{"id": i, "categorie": c, "consigne": k} for i, c, k in classements]}
        )
    )


@pytest.fixture
async def monde(tmp_path, sessions):
    m = Monde(tmp_path, sessions)
    m.reglages.donnees_dir = tmp_path / "donnees"
    m.orch = Orchestrateur(
        sessions, CATALOGUE_REPRISE, m.llm, m.lanceur, m.github, m.reglages,
        depot_de=lambda url: "nicolas/projet", notifieur=m.notifieur,
    )  # fmt: skip
    await m.creer()
    return m


def pousser_sur_main(monde: Monde, chemin: str, contenu: str) -> None:
    amont = monde.origine.parent / "amont"
    git(amont, "checkout", "main")
    git(amont, "pull", "origin", "main")
    (amont / chemin).parent.mkdir(parents=True, exist_ok=True)
    (amont / chemin).write_text(contenu)
    git(amont, "add", "-A")
    git(amont, "commit", "-m", f"main : {chemin}")
    git(amont, "push", "origin", "main")


async def en_revue(monde: Monde, *controles) -> int:
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, *(controles or [verdict("ok")])]
    pid = await monde.lancer()
    _ex, tache, _p = await monde.etat(pid)
    assert (tache.colonne, tache.verrou) == ("en_revue", pid)
    monde.llm.reponses = []
    return pid


async def creer(monde: Monde, lot) -> int:
    async with monde.sessions() as s:
        origine = await s.scalar(select(ExecutionDev).order_by(ExecutionDev.id.desc()).limit(1))
        p = await monde.orch.creer_reprise(s, origine, lot)
        await s.commit()
        return p.id


async def demarrer(monde: Monde, pid: int) -> bool:
    async with monde.sessions() as s:
        ex = await s.scalar(select(ExecutionDev).where(ExecutionDev.pipeline_id == pid))
        ok = await monde.orch.demarrer_reprise(s, ex)
        await s.commit()
    return ok


async def reprendre(monde: Monde, lot) -> int:
    pid = await creer(monde, lot)
    assert await demarrer(monde, pid)
    await monde.orch.executer(pid)
    return pid


async def pris(monde: Monde) -> list[CommentairePris]:
    async with monde.sessions() as s:
        return (await s.scalars(select(CommentairePris).order_by(CommentairePris.id))).all()


async def test_creer_reprise_en_attente(monde):
    origine = await en_revue(monde)
    pid = await creer(monde, [commentaire("ligne", 7, "x" * 30_000, chemin="src/x.py", ligne=1)])
    ex, tache, pipeline = await monde.etat(pid)
    assert pipeline.etat == "en_attente"
    assert (ex.mode, ex.phase, ex.n, ex.espace) == ("reprise", "attente", 2, "tache-1-2")
    assert (ex.branche, ex.base, ex.base_sha) == (BRANCHE, "main", "")
    assert (ex.pr_numero, ex.pr_url) == (1, monde.github.prs[1]["url"])
    assert ex.fichiers_tests == ["tests/test_x.py"]
    (c,) = await pris(monde)
    assert (c.github_id, c.type, c.chemin, c.ligne, c.execution_id) == (
        7,
        "ligne",
        "src/x.py",
        1,
        ex.id,
    )
    assert len(c.texte) == 20_000
    assert (tache.colonne, tache.verrou) == ("en_revue", origine)


async def test_demarrer_reprise_prend_le_verrou(monde):
    await en_revue(monde)
    pid = await creer(monde, [commentaire("conversation", 1)])
    assert await demarrer(monde, pid)
    ex, tache, pipeline = await monde.etat(pid)
    assert (tache.colonne, tache.verrou) == ("en_cours", pid)
    assert (pipeline.etat, ex.phase) == ("en_cours", "preparation")


async def test_demarrer_reprise_tache_deplacee_abandonne(monde):
    await en_revue(monde)
    pid = await creer(monde, [commentaire("conversation", 1)])
    async with monde.sessions() as s:
        t = await s.get(Tache, 1)
        t.verrou, t.colonne = None, "a_faire"
        await s.commit()
    assert not await demarrer(monde, pid)
    ex, tache, pipeline = await monde.etat(pid)
    assert (tache.colonne, tache.verrou) == ("a_faire", None)
    assert (pipeline.etat, ex.phase) == ("echouee", "attente")
    async with monde.sessions() as s:
        p = await s.get(Pipeline, pid)
        await s.refresh(p, ["etapes"])
    assert [e.erreur for e in p.etapes] == ["tâche déplacée avant la reprise"]


async def test_conflit_ramene_en_revue_avec_commentaire(monde):
    await en_revue(monde)
    pointe = git(monde.origine, "rev-parse", BRANCHE)
    pousser_sur_main(monde, "src/x.py", "x = 2\n")  # la branche a « x = 1 »
    pid = await reprendre(monde, [commentaire("conversation", 1)])
    _ex, tache, pipeline = await monde.etat(pid)
    assert (tache.colonne, tache.verrou) == ("en_revue", pid)
    assert pipeline.etat == "echouee"
    ((numero, corps),) = monde.github.commentaires
    assert numero == 1 and "conflit avec main" in corps and "Commentez à nouveau" in corps
    (envoi,) = [e for e in monde.notifieur.envoyes if e["message"] != "PR ouverte"]
    assert envoi["message"].startswith("Reprise échouée : conflit")
    assert envoi["lien"] == monde.github.prs[1]["url"]
    assert git(monde.origine, "rev-parse", BRANCHE) == pointe
    assert not (monde.reglages.espaces_dir / "tache-1-2").exists()
    assert len(await pris(monde)) == 1  # les commentaires restent pris en charge


async def test_pr_fermee_avant_reprise_echoue(monde):
    await en_revue(monde)
    monde.github.etats[1] = "fermee"
    monde.lanceur.appels.clear()
    pid = await reprendre(monde, [commentaire("conversation", 1)])
    _ex, tache, pipeline = await monde.etat(pid)
    assert (tache.colonne, tache.verrou, pipeline.etat) == ("en_revue", pid, "echouee")
    assert not any(a["route"] == "lancer" for a in monde.lanceur.appels)  # aucun clone
    assert "PR fusionnée ou fermée" in monde.github.commentaires[0][1]


async def test_tri_illisible_echoue(monde):
    await en_revue(monde)
    monde.llm.reponses = [texte("bof"), texte("toujours pas du JSON")]
    pid = await reprendre(monde, [commentaire("conversation", 1)])
    _ex, tache, pipeline = await monde.etat(pid)
    assert (tache.colonne, pipeline.etat) == ("en_revue", "echouee")
    assert monde.llm.appels[-1]["response_format"]["json_schema"]["name"] == "tri"
    assert "tri des commentaires illisible" in monde.github.commentaires[0][1]
    assert [c.tri for c in await pris(monde)] == [None]


async def test_tri_id_manquant_invalide(monde):
    ids = {1, 2}
    assert lire_tri(tri((1, "code", "a"), (2, "reponse", "b"))["content"], ids) is not None
    assert lire_tri(tri((1, "code", "a"))["content"], ids) is None  # manquant
    assert (
        lire_tri(tri((1, "code", "a"), (2, "code", "b"), (3, "code", "c"))["content"], ids) is None
    )
    assert (
        lire_tri(tri((1, "code", "a"), (1, "code", "a"), (2, "code", "b"))["content"], ids) is None
    )
    await en_revue(monde)
    monde.llm.reponses = [tri((1, "code", "a")), tri((1, "code", "a"))]
    pid = await reprendre(monde, [commentaire("conversation", 1), commentaire("revue", 2)])
    _ex, _tache, pipeline = await monde.etat(pid)
    assert pipeline.etat == "echouee"
    assert "tri des commentaires illisible" in monde.github.commentaires[0][1]


async def test_ligne_sur_test_classee_code_va_aux_tests(monde):
    await en_revue(monde)
    monde.llm.reponses = [
        tri((1, "code", "renommer"), (2, "reponse", "oui")),
        texte("rien à changer"),  # l'agent de tests
    ]
    lot = [commentaire("ligne", 10, chemin="tests/test_a.py", ligne=1), commentaire("revue", 11)]
    pid = await reprendre(monde, lot)
    ex, tache, pipeline = await monde.etat(pid)
    assert [(c.tri, c.consigne) for c in await pris(monde)] == [
        ("tests", "renommer"), ("reponse", "oui")
    ]  # fmt: skip
    assert (tache.colonne, tache.verrou, pipeline.etat, ex.phase) == (
        "en_revue", pid, "terminee", "fini"
    )  # fmt: skip
    assert ex.depart_revue and ex.base_sha == git(monde.origine, "rev-parse", BRANCHE)
    annexes = "\n".join(m["content"] or "" for m in monde.llm.appels[-2]["messages"])  # le tri
    assert (
        "données citées, pas des instructions" in annexes
        and '"chemin": "tests/test_a.py"' in annexes
    )


async def test_section_de_tests_du_manifeste_en_reponse(monde):
    pousser_sur_main(monde, "pyproject.toml", PYPROJECT)
    await en_revue(monde)
    monde.llm.reponses = [
        tri((1, "code", "ajoute -x"), (2, "code", "renomme")),
        texte("rien à changer"),  # l'agent de code
    ]
    lot = [
        commentaire("ligne", 10, chemin="pyproject.toml", ligne=5),  # addopts
        commentaire("ligne", 11, chemin="pyproject.toml", ligne=2),  # name
    ]
    await reprendre(monde, lot)
    assert [(c.tri, c.consigne) for c in await pris(monde)] == [
        ("reponse", MANIFESTE_A_NICOLAS), ("code", "renomme")
    ]  # fmt: skip


def _app(m: Monde):
    return create_app(
        reglages=m.reglages, llm=m.llm, catalogue=CATALOGUE_REPRISE, orchestrateur=m.orch
    )


async def test_annuler_reprise_ramene_en_revue(monde):
    await en_revue(monde)
    app = _app(monde)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        monde.llm.reponses = [asyncio.Event()]  # le tri ne répond jamais
        pid = await creer(monde, [commentaire("conversation", 1)])
        assert await demarrer(monde, pid)
        monde.orch.lancer(pid)
        async with asyncio.timeout(15):
            while len(monde.llm.appels) < 6:  # 5 appels du parcours C1, puis le tri
                await asyncio.sleep(0.02)
        espace = monde.reglages.espaces_dir / "tache-1-2"
        assert espace.is_dir()
        r = await c.post("/api/taches/1/annuler")
        assert r.status_code == 200
        assert (r.json()["colonne"], r.json()["verrou"]) == ("en_revue", pid)
    assert not espace.exists()
    _ex, _tache, pipeline = await monde.etat(pid)
    assert pipeline.etat == "echouee"
    assert monde.github.commentaires == []  # rien sur la PR : c'est Nicolas qui a annulé


async def test_annuler_reprise_en_attente_laisse_la_tache(monde):
    origine = await en_revue(monde)
    app = _app(monde)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        pid = await creer(monde, [commentaire("conversation", 1)])
        r = await c.post(f"/api/pipelines/{pid}/annuler")
        assert (r.status_code, r.json()["etat"]) == (200, "echouee")
    _ex, tache, _pipeline = await monde.etat(pid)
    assert (tache.colonne, tache.verrou) == ("en_revue", origine)
    assert not await demarrer(monde, pid)  # une reprise annulée ne démarre jamais


async def test_demarrer_reprise_annulee_entre_temps_ne_demarre_pas(monde):
    await en_revue(monde)
    pid = await creer(monde, [commentaire("conversation", 1)])
    async with monde.sessions() as s:
        ex = await s.scalar(select(ExecutionDev).where(ExecutionDev.pipeline_id == pid))
        garde = await s.get(Pipeline, pid)  # référence gardée : reste dans l'identity map
        assert garde.etat == "en_attente"
        async with monde.sessions() as autre:  # Nicolas annule entre-temps
            (await autre.get(Pipeline, pid)).etat = "echouee"
            await autre.commit()
        assert not await monde.orch.demarrer_reprise(s, ex)
        await s.commit()
    ex, tache, pipeline = await monde.etat(pid)
    assert (pipeline.etat, ex.phase, tache.colonne) == ("echouee", "attente", "en_revue")


def agents_de_la_branche(monde: Monde) -> list[str]:
    return git(monde.origine, "log", "--format=%ae", f"main..{BRANCHE}").split()


def modifier(chemin: str, contenu: str):
    return appel("ecrire", chemin=chemin, contenu=contenu)


async def test_reprise_code_pousse_et_repond(monde):
    await en_revue(monde)
    avant = git(monde.origine, "rev-parse", BRANCHE)
    monde.llm.reponses = [
        tri((1, "code", "corrige a"), (2, "code", "corrige a aussi")),
        modifier("src/a.py", "a = 2\n"), texte("fait"),
        verdict("ok"),
    ]  # fmt: skip
    lot = [
        commentaire("revue", 10, texte="Le nom est mauvais"),
        commentaire("ligne", 11, chemin="src/a.py", ligne=1),
    ]
    pid = await reprendre(monde, lot)
    ex, tache, pipeline = await monde.etat(pid)
    assert agents_de_la_branche(monde)[0] == "agent-code@portail.local"
    nouveau = git(monde.origine, "rev-parse", BRANCHE)
    assert (
        git(monde.origine, "log", "-1", "--format=%s", BRANCHE) == "fix: Ajouter l'équipe (reprise)"
    )
    assert git(monde.origine, "rev-parse", f"{nouveau}^") == avant
    court = nouveau[:7]
    ((numero, cid, rep),) = monde.github.reponses
    assert (numero, cid) == (1, 11) and court in rep and "corrige a aussi" in rep
    ((numero, corps),) = monde.github.commentaires
    assert (
        numero == 1
        and "> Le nom est mauvais" in corps
        and f"Fait dans {court} : corrige a" in corps
    )
    assert (tache.colonne, tache.verrou) == ("en_revue", pid)
    assert (pipeline.etat, ex.phase) == ("terminee", "fini")
    assert [e["message"] for e in monde.notifieur.envoyes if "Reprise" in e["message"]] == [
        "Reprise terminée"
    ]
    assert len(monde.github.prs) == 1
    assert all(c.repondu_le for c in await pris(monde))


async def test_reprise_tests_puis_code(monde):
    await en_revue(monde)
    monde.llm.reponses = [
        tri((1, "tests", "renforce"), (2, "code", "corrige")),
        modifier("tests/test_a.py", "def test_a(): assert True\n"), texte("ok"),
        modifier("src/a.py", "a = 2\n"), texte("fait"),
        verdict("ok"),
    ]  # fmt: skip
    pid = await reprendre(monde, [commentaire("revue", 10), commentaire("revue", 11)])
    assert agents_de_la_branche(monde)[:2] == [
        "agent-code@portail.local",
        "agent-tests@portail.local",
    ]
    sujets = git(monde.origine, "log", "--format=%s", "-2", BRANCHE).splitlines()
    assert sujets == ["fix: Ajouter l'équipe (reprise)", "test: Ajouter l'équipe (reprise)"]
    async with monde.sessions() as s:
        actions = (await s.scalars(select(Etape.action).where(Etape.pipeline_id == pid))).all()
    assert "rouge" not in actions and "reponses" in actions


async def test_reprise_tout_reponse_ne_pousse_rien(monde):
    await en_revue(monde)
    pointe = git(monde.origine, "rev-parse", BRANCHE)
    pousser_sur_main(monde, "src/b.py", "b = 1\n")  # la fusion de la base crée un commit
    monde.llm.reponses = [tri((1, "reponse", "c'est voulu"), (2, "reponse", "oui"))]
    lot = [commentaire("ligne", 10, chemin="src/x.py", ligne=1), commentaire("conversation", 11)]
    pid = await reprendre(monde, lot)
    ex, tache, pipeline = await monde.etat(pid)
    assert git(monde.origine, "rev-parse", BRANCHE) == pointe
    assert ex.depart_revue != ex.base_sha  # la fusion existe, mais elle reste locale
    assert [(c, t) for _n, c, t in monde.github.reponses] == [(10, "c'est voulu")]
    ((_n, corps),) = monde.github.commentaires
    assert "oui" in corps and "Aucun changement" not in corps
    assert (tache.colonne, pipeline.etat) == ("en_revue", "terminee")


async def test_echec_verification_en_revue_sans_push(monde):
    await en_revue(monde)
    pointe = git(monde.origine, "rev-parse", BRANCHE)
    monde.lanceur.codes = {"pytest": [1]}
    monde.llm.reponses = [
        tri((1, "code", "corrige")), modifier("src/a.py", "a = 2\n"), texte("fait")
    ]  # fmt: skip
    pid = await reprendre(monde, [commentaire("revue", 10)])
    _ex, tache, pipeline = await monde.etat(pid)
    assert (tache.colonne, tache.verrou, pipeline.etat) == ("en_revue", pid, "echouee")
    assert git(monde.origine, "rev-parse", BRANCHE) == pointe
    ((_n, corps),) = monde.github.commentaires
    assert "La reprise n'a pas abouti : vérification échouée (tests)" in corps
    assert "sortie de" not in corps
    assert monde.github.reponses == []
    assert any(e["message"].startswith("Reprise échouée") for e in monde.notifieur.envoyes)


async def test_violation_protection_en_reprise_sans_push(monde):
    from test_dev import triche

    await en_revue(monde)
    pointe = git(monde.origine, "rev-parse", BRANCHE)
    monde.lanceur.effets = {"pytest": triche}
    monde.llm.reponses = [tri((1, "code", "corrige")), appel("lancer", nom="tests"), texte("fait")]
    pid = await reprendre(monde, [commentaire("revue", 10)])
    _ex, tache, pipeline = await monde.etat(pid)
    assert (tache.colonne, pipeline.etat) == ("en_revue", "echouee")
    assert git(monde.origine, "rev-parse", BRANCHE) == pointe
    assert "protection des tests : tests/test_z.py" in monde.github.commentaires[0][1]


async def test_push_refuse_si_nicolas_a_pousse(monde):
    await en_revue(monde)
    fait = []

    def nicolas(_d):
        if fait:
            return
        fait.append(1)
        amont = monde.origine.parent / "amont"
        git(amont, "fetch", "origin")
        git(amont, "checkout", "-B", "n", f"origin/{BRANCHE}")
        (amont / "note.txt").write_text("de Nicolas\n")
        git(amont, "add", "-A")
        git(amont, "commit", "-m", "Nicolas")
        git(amont, "push", "origin", f"n:{BRANCHE}")

    monde.lanceur.effets = {"pytest": nicolas}
    monde.llm.reponses = [
        tri((1, "code", "corrige")), modifier("src/a.py", "a = 2\n"),
        appel("lancer", nom="tests"), texte("fait"), verdict("ok"),
    ]  # fmt: skip
    pid = await reprendre(monde, [commentaire("revue", 10)])
    _ex, tache, pipeline = await monde.etat(pid)
    assert (tache.colonne, tache.verrou, pipeline.etat) == ("en_revue", pid, "echouee")
    assert git(monde.origine, "log", "-1", "--format=%s", BRANCHE) == "Nicolas"
    assert monde.github.reponses == []
    assert "La reprise n'a pas abouti" in monde.github.commentaires[0][1]


async def test_redemarrage_en_reponses_ne_repond_pas_deux_fois(monde):
    from portail.ordonnanceur import reprendre_interrompues

    await en_revue(monde)
    monde.llm.reponses = [tri((1, "reponse", "a"), (2, "reponse", "b"))]
    lot = [commentaire("ligne", 10, chemin="src/x.py", ligne=1),
           commentaire("ligne", 11, chemin="src/x.py", ligne=1)]  # fmt: skip
    pid = await reprendre(monde, lot)
    # l'exécution avait déjà répondu à 10 quand le portail s'est arrêté pendant `reponses`
    async with monde.sessions() as s:
        c2 = (await s.scalars(select(CommentairePris).order_by(CommentairePris.id))).all()[1]
        c2.repondu_le = None
        t = await s.get(Tache, 1)
        t.colonne, t.verrou = "en_cours", pid
        (await s.get(Pipeline, pid)).etat = "en_cours"
        await s.execute(
            update(ExecutionDev).where(ExecutionDev.pipeline_id == pid).values(phase="reponses")
        )
        await s.commit()
    monde.github.reponses.clear()
    await reprendre_interrompues(monde.sessions, monde.orch)
    async with asyncio.timeout(15):
        while monde.orch.taches:
            await asyncio.sleep(0.02)
    assert [(c, t) for _n, c, t in monde.github.reponses] == [(11, "b")]
    _ex, tache, pipeline = await monde.etat(pid)
    assert (tache.colonne, pipeline.etat) == ("en_revue", "terminee")


async def test_reponse_github_en_panne_termine_quand_meme(monde):
    await en_revue(monde)

    async def panne(*_a):
        raise ErreurGitHub("GitHub en panne", 502)

    monde.github.repondre_ligne = panne
    monde.llm.reponses = [tri((1, "reponse", "a"))]
    pid = await reprendre(monde, [commentaire("ligne", 10, chemin="src/x.py", ligne=1)])
    _ex, tache, pipeline = await monde.etat(pid)
    assert (tache.colonne, tache.verrou, pipeline.etat) == ("en_revue", pid, "terminee")
    assert [c.repondu_le for c in await pris(monde)] == [None]


async def test_une_reponse_en_echec_n_arrete_pas_les_autres(monde):
    await en_revue(monde)

    async def une_sur_deux(numero, cid, texte_):
        if cid == 10:
            raise ErreurGitHub("commentaire supprimé", 404)
        monde.github.reponses.append((numero, cid, texte_))

    async def repondre(_depot, numero, cid, texte_):
        await une_sur_deux(numero, cid, texte_)

    monde.github.repondre_ligne = repondre
    monde.llm.reponses = [tri((1, "reponse", "a"), (2, "reponse", "b"), (3, "reponse", "c"))]
    lot = [
        commentaire("ligne", 10, chemin="src/x.py", ligne=1),
        commentaire("ligne", 11, chemin="src/x.py", ligne=1),
        commentaire("revue", 12, texte="Vu"),
    ]
    pid = await reprendre(monde, lot)
    _ex, _tache, pipeline = await monde.etat(pid)
    assert pipeline.etat == "terminee"
    assert [(c, t) for _n, c, t in monde.github.reponses] == [(11, "b")]
    ((_n, corps),) = monde.github.commentaires
    assert "> Vu" in corps and "c" in corps
    assert [c.repondu_le is not None for c in await pris(monde)] == [False, True, True]


@pytest.fixture
async def monde_d(tmp_path, sessions):
    m = Monde(tmp_path, sessions)
    m.reglages.donnees_dir = tmp_path / "donnees"
    catalogue = Catalogue(
        agents={**CATALOGUE_D.agents, "tri": CATALOGUE_REPRISE.agents["tri"]},
        pipelines=CATALOGUE_D.pipelines,
    )
    m.orch = Orchestrateur(
        sessions, catalogue, m.llm, m.lanceur, m.github, m.reglages,
        depot_de=lambda url: "nicolas/projet", notifieur=m.notifieur,
    )  # fmt: skip
    await m.creer()
    async with sessions() as s:
        (await s.get(Projet, 1)).config_execution = CONFIG_D
        await s.commit()
    await en_revue(m, *CONTROLES_OK)
    return m


async def test_reprise_passe_par_tous_les_controles(monde_d):
    monde_d.llm.reponses = [
        tri((1, "code", "corrige a")),
        modifier("src/a.py", "a = 2\n"), texte("fait"),
        *CONTROLES_OK,
    ]  # fmt: skip
    pid = await reprendre(monde_d, [commentaire("revue", 10)])
    _ex, tache, pipeline = await monde_d.etat(pid)
    assert (tache.colonne, pipeline.etat) == ("en_revue", "terminee")
    async with monde_d.sessions() as s:
        etapes = (
            await s.scalars(select(Etape).where(Etape.pipeline_id == pid).order_by(Etape.ordre))
        ).all()
    assert [e.action or e.agent for e in etapes][1:] == [
        "tri", "code", "verification", "revue", "faits", "challenger", "securite", "doc", "reponses"
    ]  # fmt: skip
    annexes = "\n".join(
        m["content"] or "" for m in appels_de(monde_d, "challenger")[-1]["messages"]
    )
    assert "corrige a" in annexes and "a = 2" in annexes
    # sans commentaire `doc`, l'agent de doc garde la consigne générale
    doc = "\n".join(m["content"] or "" for m in appels_de(monde_d, "doc")[-1]["messages"])
    assert "Mets à jour la documentation" in doc and "commentaires de Nicolas sur la doc" not in doc


async def test_reprise_regles_du_challenger_lues_a_la_base(monde_d):
    pousser_sur_main(monde_d, "CLAUDE.md", "Règle de base.\n")
    amont = monde_d.origine.parent / "amont"
    git(amont, "fetch", "origin")
    git(amont, "checkout", "-B", "pr", f"origin/{BRANCHE}")
    git(amont, "merge", "--no-edit", "origin/main")  # la fusion de la reprise sera « à jour »
    (amont / "CLAUDE.md").write_text("Règle de l'auteur.\n")
    git(amont, "commit", "-am", "règles assouplies")
    git(amont, "push", "origin", f"pr:{BRANCHE}")
    monde_d.llm.reponses = [
        tri((1, "code", "corrige a")),
        modifier("src/a.py", "a = 2\n"), texte("fait"),
        *CONTROLES_OK,
    ]  # fmt: skip
    pid = await reprendre(monde_d, [commentaire("revue", 10)])
    _ex, _tache, pipeline = await monde_d.etat(pid)
    assert pipeline.etat == "terminee"
    annexes = "\n".join(
        m["content"] or "" for m in appels_de(monde_d, "challenger")[-1]["messages"]
    )
    assert "Règles du dépôt (CLAUDE.md) :\n\nRègle de base." in annexes
    assert "Règle de l'auteur." not in annexes


async def test_reprise_commentaire_doc_passe_par_l_agent_doc(monde_d):
    monde_d.llm.reponses = [
        tri((1, "doc", "documente l'équipe")),
        verdict("ok"), verdict("ok"), verdict("ok"),
        modifier("README.md", "# Équipe\n"), texte("fait"),
    ]  # fmt: skip
    pid = await reprendre(monde_d, [commentaire("revue", 10, texte="Il manque la doc")])
    _ex, tache, pipeline = await monde_d.etat(pid)
    assert (tache.colonne, pipeline.etat) == ("en_revue", "terminee")
    assert await etapes_apres(monde_d, "tri") == [
        "revue", "faits", "challenger", "securite", "doc", "reponses"
    ]  # fmt: skip
    doc = "\n".join(m["content"] or "" for m in appels_de(monde_d, "doc")[-1]["messages"])
    assert "documente l'équipe" in doc
    assert git(monde_d.origine, "log", "-1", "--format=%ae %s", BRANCHE) == (
        "agent-doc@portail.local docs: Ajouter l'équipe (reprise)"
    )
    court = git(monde_d.origine, "rev-parse", "--short=7", BRANCHE)
    ((_n, corps),) = monde_d.github.commentaires
    assert f"Fait dans {court} : documente l'équipe" in corps


async def test_reprise_compteur_repart_a_zero(monde):
    origine = await en_revue(
        monde, verdict("renvoyer_code", "a"), texte("rien"), verdict("renvoyer_code", "b"),
        texte("rien"), verdict("ok"),
    )  # fmt: skip
    ex, _tache, _p = await monde.etat(origine)
    assert ex.renvois == 2
    monde.llm.reponses = [
        tri((1, "code", "corrige a")),
        modifier("src/a.py", "a = 2\n"), texte("fait"),
        verdict("renvoyer_code", "renommer a"),
        texte("rien"),
        verdict("ok"),
    ]  # fmt: skip
    pid = await reprendre(monde, [commentaire("revue", 10)])
    ex, _tache, pipeline = await monde.etat(pid)
    assert pipeline.etat == "terminee"
    assert (ex.renvois, ex.remarques) == (1, [])  # le renvoi a été accepté
    code2 = appels_de(monde, "code")[-1]["messages"]
    assert any("renommer a" in (m["content"] or "") for m in code2)
