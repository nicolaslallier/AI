from portail.db import Document, Etape, Pipeline, Projet, Tache
from portail.outils_portail import OutilsPortail

TOUS = ["lister_projets", "lire_projet", "lister_pipelines", "lire_pipeline", "lire_kanban"]


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
