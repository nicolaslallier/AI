from datetime import UTC, datetime

from sqlalchemy import event

from portail.agents import OUTILS_LECTURE_PORTAIL
from portail.db import (
    Document,
    Etape,
    ExecutionDev,
    Pipeline,
    Projet,
    Proposition,
    Tache,
    TacheEvenement,
)
from portail.outils_portail import OutilsPortail, activite_depuis

TOUS = list(OUTILS_LECTURE_PORTAIL)


async def _projet(sessions, nom="EA"):
    async with sessions() as s:
        p = Projet(nom=nom)
        s.add(p)
        await s.commit()
        return p.id


def test_schemas_filtres_par_noms(sessions):
    schemas = OutilsPortail(sessions, ["lister_projets"]).schemas()
    assert [x["function"]["name"] for x in schemas] == ["lister_projets"]


async def test_lister_projets(sessions):
    a, b = await _projet(sessions, "EA"), await _projet(sessions, "Glee")
    texte, mal = await OutilsPortail(sessions, TOUS).executer("lister_projets", "{}")
    assert not mal
    assert f"#{a} EA" in texte and f"#{b} Glee" in texte


async def test_lire_projet_avec_spec_courante(sessions):
    pid = await _projet(sessions)
    async with sessions() as s:
        pl = Pipeline(projet_id=pid, type="spec")
        s.add(pl)
        await s.flush()
        e = Etape(pipeline_id=pl.id, ordre=1, agent="redacteur", erreur="boum")
        s.add(e)
        await s.flush()
        s.add(
            Document(
                projet_id=pid, pipeline_id=pl.id, etape_id=e.id, type="spec",
                contenu="Contenu de la spec", etat="validee",
            )
        )  # fmt: skip
        await s.commit()
        plid = pl.id
    o = OutilsPortail(sessions, TOUS)
    texte, _ = await o.executer("lire_projet", f'{{"projet_id": {pid}}}')
    assert "Contenu de la spec" in texte
    texte, _ = await o.executer("lire_pipeline", f'{{"pipeline_id": {plid}}}')
    assert "1. redacteur" in texte and "boum" in texte
    texte, _ = await o.executer("lister_pipelines", f'{{"projet_id": {pid}}}')
    assert f"#{plid}" in texte


async def test_lire_kanban_par_colonne(sessions):
    pid = await _projet(sessions)
    async with sessions() as s:
        s.add(Tache(projet_id=pid, titre="Faire X", colonne="prete", rang=1, origine="manuel"))
        await s.commit()
    texte, _ = await OutilsPortail(sessions, TOUS).executer(
        "lire_kanban", f'{{"projet_id": {pid}}}'
    )
    assert "## prete\n#1 Faire X" in texte


async def test_id_inconnu_n_est_pas_mal_forme(sessions):
    r = await OutilsPortail(sessions, TOUS).executer("lire_projet", '{"projet_id": 999}')
    assert r == ("erreur : projet 999 introuvable", False)


async def test_arguments_invalides_mal_formes(sessions):
    o = OutilsPortail(sessions, TOUS)
    assert (await o.executer("lire_projet", "pas du json"))[1] is True
    assert (await o.executer("lire_projet", "{}"))[1] is True
    assert (await o.executer("lire_projet", '{"projet_id": "1"}'))[1] is True
    assert await o.executer("nimporte", "{}") == ("erreur : outil inconnu : nimporte", True)


async def test_sortie_bornee(sessions):
    async with sessions() as s:
        s.add_all(Projet(nom=f"projet numéro {i} " + "x" * 20) for i in range(500))
        await s.commit()
    texte, _ = await OutilsPortail(sessions, TOUS).executer("lister_projets", "{}")
    assert len(texte) <= 8000 + 20 and texte.endswith("(tronqué)")


async def test_ids_hors_bornes_mal_formes(sessions):
    o = OutilsPortail(sessions, TOUS)
    for arg in ("99999999999", "-1", "0"):
        assert (await o.executer("lire_projet", f'{{"projet_id": {arg}}}'))[1] is True
        assert (await o.executer("lire_pipeline", f'{{"pipeline_id": {arg}}}'))[1] is True
        assert (await o.executer("lister_pipelines", f'{{"projet_id": {arg}}}'))[1] is True


async def _etat_du_suivi(sessions):
    """Une étape en attente, une proposition ouverte, une tâche en revue, une tâche bloquée."""
    pid = await _projet(sessions)
    async with sessions() as s:
        pl = Pipeline(projet_id=pid, type="spec")
        s.add(pl)
        await s.flush()
        e = Etape(pipeline_id=pl.id, ordre=1, agent="redacteur", etat="en_attente")
        revue = Tache(projet_id=pid, titre="À relire", colonne="en_revue", rang=1, origine="manuel")
        bloquee = Tache(
            projet_id=pid, titre="Coincée", colonne="bloquee", rang=1, origine="manuel",
            resume_blocage="les tests rouges persistent " + "x" * 600,
        )  # fmt: skip
        s.add_all([e, revue, bloquee])
        await s.flush()
        s.add(Proposition(pipeline_id=pl.id, etape_id=e.id, projet_id=pid, sorte="nouvelle"))
        dev = Pipeline(projet_id=pid, type="dev")
        s.add(dev)
        await s.flush()
        s.add_all(
            [
                ExecutionDev(
                    pipeline_id=pl.id, tache_id=revue.id, n=1, branche="b", espace="e", base="main",
                    base_sha="0", phase="fini", pr_url="https://git.example/pr/ancienne",
                ),
                ExecutionDev(
                    pipeline_id=dev.id, tache_id=revue.id, n=2, branche="b", espace="e",
                    base="main", base_sha="0", phase="fini", pr_url="https://git.example/pr/7",
                ),
            ]
        )  # fmt: skip
        await s.commit()
    return pid


async def test_en_attente_de_nicolas(sessions):
    await _etat_du_suivi(sessions)
    texte, mal = await OutilsPortail(sessions, TOUS).executer("en_attente_de_nicolas", "{}")
    assert not mal
    assert "redacteur" in texte  # étape en attente
    assert "proposition" in texte  # proposition ouverte
    assert "À relire" in texte and "https://git.example/pr/7" in texte
    assert "pr/ancienne" not in texte  # la dernière exécution seulement
    assert "Coincée" in texte and "les tests rouges persistent" in texte
    assert "x" * 600 not in texte  # résumé de blocage tronqué
    assert "20" in texte  # datés


async def test_en_attente_de_nicolas_vide(sessions):
    texte, _ = await OutilsPortail(sessions, TOUS).executer("en_attente_de_nicolas", "{}")
    assert texte == "rien n'attend Nicolas"


async def test_activite_depuis(sessions):
    pid = await _projet(sessions)
    ancien, recent = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 5, tzinfo=UTC)
    async with sessions() as s:
        s.add_all(
            [
                TacheEvenement(
                    projet_id=pid, tache_id=1, type="creation", auteur="nicolas", cree_le=ancien
                ),
                TacheEvenement(
                    projet_id=pid, tache_id=2, type="deplacement", auteur="nicolas", cree_le=recent
                ),
                Pipeline(projet_id=pid, type="spec", etat="termine", maj_le=recent),
            ]
        )
        await s.commit()
    async with sessions() as s:
        lignes = await activite_depuis(s, datetime(2026, 1, 3, tzinfo=UTC))
    assert len(lignes) == 2 and all(l.startswith("2026-01-05T00:00:00") for l in lignes)
    assert any("deplacement" in l for l in lignes) and any("spec" in l for l in lignes)
    texte, mal = await OutilsPortail(sessions, TOUS).executer(
        "activite", '{"depuis": "2026-01-03T00:00:00+00:00"}'
    )
    assert not mal and texte.count("\n") == 1
    assert (await OutilsPortail(sessions, TOUS).executer("activite", '{"depuis": "hier"}'))[1]


async def test_pipelines_dates(sessions):
    pid = await _projet(sessions)
    async with sessions() as s:
        pl = Pipeline(projet_id=pid, type="spec")
        s.add(pl)
        await s.commit()
        plid = pl.id
    o = OutilsPortail(sessions, TOUS)
    assert "mis à jour 20" in (await o.executer("lister_pipelines", "{}"))[0]
    assert "mis à jour 20" in (await o.executer("lire_pipeline", f'{{"pipeline_id": {plid}}}'))[0]


async def test_outils_pm_lecture_seule(sessions):
    await _etat_du_suivi(sessions)
    ecritures = []

    def surveiller(conn, cur, statement, *_):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            ecritures.append(statement)

    moteur = sessions.kw["bind"].sync_engine
    event.listen(moteur, "before_cursor_execute", surveiller)
    try:
        o = OutilsPortail(sessions, list(OUTILS_LECTURE_PORTAIL))
        args = {
            "lire_projet": '{"projet_id": 1}',
            "lire_kanban": '{"projet_id": 1}',
            "lire_pipeline": '{"pipeline_id": 1}',
            "activite": '{"depuis": "2020-01-01T00:00:00+00:00"}',
        }
        for nom in OUTILS_LECTURE_PORTAIL:
            texte, mal = await o.executer(nom, args.get(nom, "{}"))
            assert not mal, (nom, texte)
    finally:
        event.remove(moteur, "before_cursor_execute", surveiller)
    assert ecritures == []
