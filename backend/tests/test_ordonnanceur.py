import asyncio

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_dev import BRANCHE, CATALOGUE, CIBLES, CODE_OK, CONFIG, TESTS_OK, Monde, texte, verdict

from portail.api import create_app
from portail.db import Etape, ExecutionDev, Pipeline, Projet, Tache, TacheDependance
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
