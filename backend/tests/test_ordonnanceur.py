import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from asgi_lifespan import LifespanManager
from conftest import commentaire, valeur
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from test_dev import BRANCHE, CATALOGUE, CIBLES, CODE_OK, CONFIG, TESTS_OK, Monde, texte, verdict

from portail.api import create_app
from portail.db import (
    Audit,
    Etape,
    ExecutionDev,
    Pipeline,
    Projet,
    Tache,
    TacheDependance,
    TacheEvenement,
)
from portail.github import ErreurGitHub
from portail.moteur import recuperer_interrompues
from portail.ordonnanceur import Ordonnanceur, choisir, reprendre_interrompues


async def attendre(condition, delai=15):
    async with asyncio.timeout(delai):
        while not await condition():
            await asyncio.sleep(0.02)


async def _projet(s, depot="file:///x", config=CONFIG) -> int:
    p = Projet(nom="p", depot_url=depot, config_execution=config)
    s.add(p)
    await s.flush()
    return p.id


async def _tache(s, projet_id, rang, colonne="prete", verrou=None) -> int:
    t = Tache(
        projet_id=projet_id, titre=f"t{rang}", colonne=colonne, rang=rang, origine="manuel",
        verrou=verrou,
    )  # fmt: skip
    s.add(t)
    await s.flush()
    return t.id


async def _choix(sessions):
    async with sessions() as s:
        t = await choisir(s)
        return t and t.id


async def test_choisir_respecte_rang_dependances_verrou(sessions):
    async with sessions() as s:
        p = await _projet(s)
        t1 = await _tache(s, p, 2000)
        t2 = await _tache(s, p, 1000)
        t3 = await _tache(s, p, 1000, "en_revue")
        s.add(TacheDependance(tache_id=t2, depend_de_id=t3))
        pipeline = Pipeline(projet_id=p, type="spec")
        s.add(pipeline)
        await s.flush()
        await _tache(s, p, 500, verrou=pipeline.id)
        await s.commit()
    assert await _choix(sessions) == t1
    async with sessions() as s:
        (await s.get(Tache, t3)).colonne = "terminee"
        await s.commit()
    assert await _choix(sessions) == t2


async def test_choisir_entre_projets(sessions):
    async with sessions() as s:
        p1, p2 = await _projet(s), await _projet(s)
        await _tache(s, p1, 2000)
        attendu = await _tache(s, p2, 1000)  # même rang qu'en dessous : le plus petit id gagne
        await _tache(s, p1, 1000)
        await s.commit()
    assert await _choix(sessions) == attendu


async def test_projet_sans_config_ignore(sessions):
    async with sessions() as s:
        await _tache(s, await _projet(s, config=None), 100)
        await _tache(s, await _projet(s, depot=None), 100)
        await s.commit()
    assert await _choix(sessions) is None


async def test_deux_choix_concurrents_jamais_la_meme_tache(sessions):
    async with sessions() as s:
        p = await _projet(s)
        await _tache(s, p, 1000)
        await _tache(s, p, 2000)
        await s.commit()
    async with sessions() as s1, sessions() as s2:
        a = await choisir(s1)  # transaction ouverte : la ligne reste verrouillée
        b = await choisir(s2)
        async with sessions() as s3:
            c = await choisir(s3)
        assert (a.id, b.id, c) == (1, 2, None)


# --- ordonnanceur et orchestrateur --------------------------------------


async def _monde(tmp_path, sessions) -> Monde:
    m = Monde(tmp_path, sessions)
    m.reglages.donnees_dir = tmp_path / "donnees"
    await m.creer()
    return m


async def _arreter(m: Monde):
    taches = list(m.orch.taches.values())
    for t in taches:
        t.cancel()
    await asyncio.gather(*taches, return_exceptions=True)


async def _fin(m: Monde):
    await asyncio.gather(*m.orch.taches.values())


async def test_paralleles_max_respecte(tmp_path, sessions):
    m = await _monde(tmp_path, sessions)
    async with sessions() as s:
        s.add(Tache(projet_id=1, titre="autre", colonne="prete", rang=2000, origine="manuel"))
        await s.commit()
    m.llm.reponses = [asyncio.Event()]
    ordo = Ordonnanceur(sessions, m.orch, 1)
    try:
        await ordo.tour()
        await ordo.tour()
        assert list(m.orch.taches) == [1]
        async with sessions() as s:
            colonnes = (await s.scalars(select(Tache.colonne).order_by(Tache.id))).all()
        assert colonnes == ["en_cours", "prete"]
    finally:
        await _arreter(m)


async def test_demarrage_impossible_bloque_et_passe_a_la_suivante(tmp_path, sessions):
    blocages = valeur("portail_blocages_total", cause="demarrage", phase="aucune")
    m = await _monde(tmp_path, sessions)
    async with sessions() as s:
        p2 = await _projet(s, depot=f"file://{m.origine}")
        t2 = await _tache(s, p2, 2000)
        await s.commit()
    appels = []

    async def branche_defaut(depot):
        appels.append(depot)
        if len(appels) == 1:  # T1, de plus petit rang : l'App n'est pas installée
            raise ErreurGitHub("App non installée", 404)
        return "main"

    m.github.branche_defaut = branche_defaut
    m.llm.reponses = [asyncio.Event()]
    ordo = Ordonnanceur(sessions, m.orch, 1)
    try:
        await ordo.tour()
        assert len(m.orch.taches) == 1
        async with sessions() as s:
            t1, t2 = await s.get(Tache, 1), await s.get(Tache, t2)
        assert (t1.colonne, t1.verrou) == ("bloquee", None)
        assert t1.resume_blocage == "démarrage impossible : App non installée"
        assert t2.colonne == "en_cours" and t2.verrou is not None
        assert valeur("portail_blocages_total", cause="demarrage", phase="aucune") == blocages + 1
        async with sessions() as s:
            types = (
                await s.scalars(select(TacheEvenement.type).where(TacheEvenement.tache_id == 1))
            ).all()
        assert types == ["deplacement"]
        (envoi,) = m.notifieur.envoyes
        assert envoi["titre"] == f"Portail — tâche T{t1.id}"
        assert envoi["message"] == "Bloquée"
        assert "App non installée" not in envoi["titre"] + envoi["message"]
        assert envoi["lien"] == f"https://portail.x/projets/{t1.projet_id}/kanban"
    finally:
        await _arreter(m)


async def test_notifieur_en_erreur_ne_casse_pas_le_blocage(tmp_path, sessions):
    m = await _monde(tmp_path, sessions)

    async def refuse(depot):
        raise ErreurGitHub("App non installée", 404)

    async def explose(*a, **k):
        raise RuntimeError("secret")

    m.github.branche_defaut = refuse
    m.orch.notifier = explose
    await Ordonnanceur(sessions, m.orch, 1).tour()
    async with sessions() as s:
        assert (await s.get(Tache, 1)).colonne == "bloquee"


@pytest.mark.parametrize(
    "erreur",
    [
        ErreurGitHub("GitHub injoignable", None),
        ErreurGitHub("GitHub 502", 502),
        ErreurGitHub("GitHub 429", 429),
        OperationalError("select", {}, Exception("base indisponible")),
    ],
)
async def test_erreur_transitoire_ne_bloque_pas(tmp_path, sessions, erreur):
    m = await _monde(tmp_path, sessions)
    async with sessions() as s:
        t2 = await _tache(s, 1, 2000)
        await s.commit()
    if isinstance(erreur, ErreurGitHub):
        m.github.erreur = erreur
    else:

        async def demarrer(*_):
            raise erreur

        m.orch.demarrer = demarrer
    ordo = Ordonnanceur(sessions, m.orch, 1)
    await ordo.tour()
    assert m.orch.taches == {}
    async with sessions() as s:
        t1, t2 = await s.get(Tache, 1), await s.get(Tache, t2)
    assert (t1.colonne, t1.verrou, t2.colonne) == ("prete", None, "prete")
    assert t1.resume_blocage is None


async def test_reprise_liberee_reveille_l_ordonnanceur(tmp_path, sessions):
    m = await _monde(tmp_path, sessions)
    m.llm.reponses = [texte("rien")]  # aucun test écrit : la reprise finit vite
    async with sessions() as s:
        await m.orch.demarrer(s, await s.get(Tache, 1))
        await s.commit()
    ordo = Ordonnanceur(sessions, m.orch, 1)
    await reprendre_interrompues(sessions, m.orch, ordo.lancer)
    assert not ordo._reveil.is_set()
    await _fin(m)
    await asyncio.sleep(0)  # les rappels de fin passent à l'itération suivante
    assert ordo._reveil.is_set()


async def test_relance_branche_n(tmp_path, sessions):
    m = await _monde(tmp_path, sessions)
    m.llm.reponses = [texte("rien"), texte("rien")]  # aucun test écrit : bloquée
    ordo = Ordonnanceur(sessions, m.orch, 1)
    await ordo.tour()
    await _fin(m)
    async with sessions() as s:
        t = await s.get(Tache, 1)
        assert t.colonne == "bloquee"
        t.colonne = "prete"
        await s.commit()
    await ordo.tour()
    await _fin(m)
    async with sessions() as s:
        exs = (await s.scalars(select(ExecutionDev).order_by(ExecutionDev.id))).all()
    assert [(e.n, e.branche, e.espace) for e in exs] == [
        (1, BRANCHE, "tache-1-1"),
        (2, BRANCHE + "-2", "tache-1-2"),
    ]


def _app(m: Monde):
    return create_app(reglages=m.reglages, llm=m.llm, catalogue=CATALOGUE, orchestrateur=m.orch)


async def _colonne(sessions, tache_id=1):
    async with sessions() as s:
        return await s.scalar(select(Tache.colonne).where(Tache.id == tache_id))


async def test_annuler_dev(tmp_path, sessions):
    m = await _monde(tmp_path, sessions)
    bloque = asyncio.Event()
    m.llm.reponses = [bloque]
    app = _app(m)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        await attendre(lambda: _vrai(len(m.llm.appels) == 1))  # lancée par l'ordonnanceur
        espace = m.reglages.espaces_dir / "tache-1-1"
        assert espace.is_dir()
        r = await c.post("/api/taches/1/annuler")
        assert r.status_code == 200
        assert (r.json()["colonne"], r.json()["verrou"]) == ("a_faire", None)
    assert not espace.exists()
    assert {"route": "arreter", "espace": "tache-1-1"} in m.lanceur.appels
    assert {"route": "nettoyer", "espace": "tache-1-1"} in m.lanceur.appels
    async with sessions() as s:
        pipeline = await s.get(Pipeline, 1)
        etapes = (await s.scalars(select(Etape).order_by(Etape.ordre))).all()
    assert pipeline.etat == "echouee"
    assert (etapes[-1].agent, etapes[-1].etat, etapes[-1].erreur) == ("tests", "echouee", "annulé")


async def test_annuler_dev_par_la_route_pipeline_libere_la_tache(tmp_path, sessions):
    m = await _monde(tmp_path, sessions)
    m.llm.reponses = [asyncio.Event()]
    app = _app(m)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        await attendre(lambda: _vrai(len(m.llm.appels) == 1))
        r = await c.post("/api/pipelines/1/annuler")
        assert (r.status_code, r.json()["etat"]) == (200, "echouee")
        async with sessions() as s:
            t = await s.get(Tache, 1)
        assert (t.colonne, t.verrou) == ("a_faire", None)
    assert not (m.reglages.espaces_dir / "tache-1-1").exists()


async def _vrai(v):
    return v


async def test_relance_ferme_l_ancienne_pr(tmp_path, sessions):
    m = await _monde(tmp_path, sessions)
    m.lanceur.codes = {CIBLES: [1, 0, 1]}  # rouge, vérification, rouge
    m.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok")] * 2
    app = _app(m)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        await attendre(lambda: _egal(_colonne(sessions), "en_revue"))
        r = await c.post("/api/taches/1/annuler")  # pipeline terminé : nettoyage seul
        assert r.json()["colonne"] == "a_faire"
        assert not (m.reglages.espaces_dir / "tache-1-1").exists()
        assert m.github.etats == {1: "ouverte"}
        await c.post("/api/taches/1/deplacer", json={"colonne": "prete"})  # réveille
        await attendre(lambda: _egal(_colonne(sessions), "en_revue"))
    async with sessions() as s:
        etats = (await s.scalars(select(Pipeline.etat).order_by(Pipeline.id))).all()
    assert etats == ["terminee", "terminee"]
    assert m.github.prs[2]["branche"] == BRANCHE + "-2"
    assert m.github.etats == {1: "fermee", 2: "ouverte"}
    assert m.github.commentaires == [(1, f"Remplacée par {m.github.prs[2]['url']}")]


async def _egal(attente, valeur):
    return await attente == valeur


async def test_redemarrage_reprend_une_fois_puis_bloque(tmp_path, sessions):
    interrompues = valeur("portail_blocages_total", cause="interrompue", phase="tests")
    m = await _monde(tmp_path, sessions)
    m.llm.reponses = [asyncio.Event()]
    async with sessions() as s:
        pid = (await m.orch.demarrer(s, await s.get(Tache, 1))).id
        await s.commit()
    await reprendre_interrompues(sessions, m.orch)  # 1re interruption : la phase repart
    await attendre(lambda: _vrai(len(m.llm.appels) == 1))
    tache = m.orch.taches[pid]
    tache.cancel()  # arrêt brutal du portail : l'état en base reste « en cours »
    await asyncio.wait([tache])
    async with sessions() as s:
        assert (await s.get(Pipeline, pid)).etat == "en_cours"
    await reprendre_interrompues(sessions, m.orch)  # 2e interruption : bloquée
    assert m.orch.taches == {}
    ex, t, pipeline = await m.etat(pid)
    assert ex.interruptions == 2
    assert valeur("portail_blocages_total", cause="interrompue", phase="tests") == interrompues + 1
    assert (t.colonne, t.verrou, pipeline.etat) == ("bloquee", None, "echouee")
    assert t.resume_blocage.startswith("interrompue deux fois")
    assert not (m.reglages.espaces_dir / "tache-1-1").exists()
    async with sessions() as s:
        erreurs = (await s.scalars(select(Etape.erreur).order_by(Etape.ordre))).all()
    assert erreurs == [None, "interrompue par un redémarrage"]  # préparation, tests


async def test_recuperer_interrompues_ignore_dev(sessions):
    async with sessions() as s:
        p = await _projet(s)
        dev = Pipeline(projet_id=p, type="dev", etat="en_cours")
        spec = Pipeline(projet_id=p, type="spec", etat="en_cours")
        s.add_all([dev, spec])
        await s.flush()
        s.add_all(
            [
                Etape(pipeline_id=dev.id, ordre=0, agent="tests", etat="en_cours"),
                Etape(pipeline_id=spec.id, ordre=0, agent="spec", etat="en_cours"),
            ]
        )
        await s.flush()
        assert await recuperer_interrompues(s) == 1
        await s.commit()
    async with sessions() as s:
        etats = (await s.execute(select(Pipeline.type, Pipeline.etat).order_by(Pipeline.id))).all()
        etapes = (await s.scalars(select(Etape.etat).order_by(Etape.id))).all()
    assert [tuple(e) for e in etats] == [("dev", "en_cours"), ("spec", "echouee")]
    assert etapes == ["en_cours", "echouee"]


# --- reprises -----------------------------------------------------------


async def _en_revue(sessions, projet_id, rang) -> int:
    """Une tâche *En revue* avec sa PR n° `rang`, verrou tenu par son pipeline fini."""
    async with sessions() as s:
        t = Tache(
            projet_id=projet_id, titre=f"r{rang}", colonne="en_revue", rang=rang, origine="manuel"
        )
        s.add(t)
        pipeline = Pipeline(projet_id=projet_id, type="dev", etat="terminee")
        s.add(pipeline)
        await s.flush()
        t.verrou = pipeline.id
        s.add(
            ExecutionDev(
                pipeline_id=pipeline.id, tache_id=t.id, n=1, branche=f"b{rang}",
                espace=f"e{rang}", base="main", base_sha="x", phase="fini", pr_numero=rang,
            )
        )  # fmt: skip
        await s.commit()
        return t.id


async def _reprise(m: Monde, tache_id: int, age_min: int = 0) -> int:
    """Une reprise en attente dont le commentaire a `age_min` minutes."""
    async with m.sessions() as s:
        origine = await s.scalar(
            select(ExecutionDev).where(ExecutionDev.tache_id == tache_id).order_by(ExecutionDev.id)
        )
        cree = datetime.now(UTC) - timedelta(minutes=age_min)
        p = await m.orch.creer_reprise(s, origine, [commentaire("revue", tache_id, cree_le=cree)])
        await s.commit()
        return p.id


async def test_reprise_passe_avant_les_taches_pretes(tmp_path, sessions):
    m = await _monde(tmp_path, sessions)  # T1 est Prête
    t2 = await _en_revue(sessions, 1, 2000)
    pid = await _reprise(m, t2)
    m.llm.reponses = [asyncio.Event()]
    try:
        await Ordonnanceur(sessions, m.orch, 1).tour()
        assert list(m.orch.taches) == [pid]
        async with sessions() as s:
            assert (await s.get(Tache, 1)).colonne == "prete"
            assert (await s.get(Tache, t2)).colonne == "en_cours"
    finally:
        await _arreter(m)


async def test_reprise_lancee_inscrit_l_audit(tmp_path, sessions):
    m = await _monde(tmp_path, sessions)
    t2 = await _en_revue(sessions, 1, 2000)
    pid = await _reprise(m, t2)
    m.llm.reponses = [asyncio.Event()]
    try:
        await Ordonnanceur(sessions, m.orch, 1).tour()
        async with sessions() as s:
            lignes = (
                await s.scalars(select(Audit).where(Audit.action == "pipeline.reprendre"))
            ).all()
        assert [(x.auteur, x.objet, x.objet_id) for x in lignes] == [
            ("ordonnanceur", "pipeline", pid)
        ]
    finally:
        await _arreter(m)


async def test_reprises_dans_l_ordre_des_commentaires(tmp_path, sessions):
    m = await _monde(tmp_path, sessions)
    async with sessions() as s:
        (await s.get(Tache, 1)).colonne = "terminee"
        await s.commit()
    ta, tb = await _en_revue(sessions, 1, 2000), await _en_revue(sessions, 1, 3000)
    await _reprise(m, ta, age_min=5)
    pid_b = await _reprise(m, tb, age_min=30)  # commentaire plus ancien, id plus grand
    m.llm.reponses = [asyncio.Event()]
    try:
        await Ordonnanceur(sessions, m.orch, 1).tour()
        assert list(m.orch.taches) == [pid_b]
    finally:
        await _arreter(m)


async def test_reprise_compte_dans_paralleles_max(tmp_path, sessions):
    m = await _monde(tmp_path, sessions)
    ta, tb = await _en_revue(sessions, 1, 2000), await _en_revue(sessions, 1, 3000)
    pid_a = await _reprise(m, ta)
    await _reprise(m, tb)
    m.llm.reponses = [asyncio.Event()]
    ordo = Ordonnanceur(sessions, m.orch, 1)
    try:
        await ordo.tour()
        await ordo.tour()
        assert list(m.orch.taches) == [pid_a]
        async with sessions() as s:
            assert (await s.get(Tache, tb)).colonne == "en_revue"
            assert (await s.get(Tache, 1)).colonne == "prete"
    finally:
        await _arreter(m)


async def test_reprise_en_attente_tache_annulee_abandonnee(tmp_path, sessions):
    m = await _monde(tmp_path, sessions)
    async with sessions() as s:
        (await s.get(Tache, 1)).colonne = "terminee"
        await s.commit()
    ta = await _en_revue(sessions, 1, 2000)
    pid = await _reprise(m, ta)
    async with sessions() as s:  # la route d'annulation : la tâche repart À faire
        t = await s.get(Tache, ta)
        t.colonne, t.verrou = "a_faire", None
        await s.commit()
    await Ordonnanceur(sessions, m.orch, 1).tour()
    assert m.orch.taches == {}
    _ex, tache, pipeline = await m.etat(pid)
    assert (pipeline.etat, tache.colonne) == ("echouee", "a_faire")
