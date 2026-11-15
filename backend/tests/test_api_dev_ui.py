from datetime import UTC, datetime

from portail.db import CommandeLancee, CommentairePris, Etape, ExecutionDev, Pipeline, Tache


async def _projet(client):
    return (await client.post("/api/projets", json={"nom": "P"})).json()["id"]


async def test_detail_pipeline_dev_execution_et_commandes(client, sessions):
    pid = await _projet(client)
    async with sessions() as s:
        t = Tache(projet_id=pid, titre="t", colonne="en_cours", rang=1000, origine="manuel")
        p = Pipeline(projet_id=pid, type="spec")
        s.add_all([t, p])
        await s.flush()
        e = Etape(pipeline_id=p.id, ordre=1, agent="spec", etat="en_attente")
        s.add_all([e, ExecutionDev(
            pipeline_id=p.id, tache_id=t.id, n=1, branche="portail/tache-1-t", espace="e",
            base="main", base_sha="x", phase="code", renvois=1,
            pr_url="https://github.com/o/r/pull/7",
        )])  # fmt: skip
        await s.flush()
        s.add(CommandeLancee(pipeline_id=p.id, etape_id=e.id, nom="tests", code=1, sortie="boum"))
        await s.commit()
        pipeline_id = p.id
    d = (await client.get(f"/api/pipelines/{pipeline_id}")).json()
    assert d["execution"] == {
        "branche": "portail/tache-1-t", "phase": "code", "renvois": 1, "mode": "normal",
        "pr_url": "https://github.com/o/r/pull/7",
    }  # fmt: skip
    (c,) = d["commandes"]
    assert (c["nom"], c["code"], c["delai_depasse"], c["sortie"]) == ("tests", 1, False, "boum")
    assert c["etape_id"] == d["etapes"][0]["id"] and c["debut"] and c["fin"]


async def test_detail_pipeline_sans_execution(client):
    pid = await _projet(client)
    r = await client.post("/api/pipelines", json={"projet_id": pid, "type": "spec"})
    d = (await client.get(f"/api/pipelines/{r.json()['id']}")).json()
    assert (d["execution"], d["commandes"]) == (None, [])


async def test_tachevue_pr_url_resume_et_config(client, sessions):
    pid = await _projet(client)
    k = (await client.get(f"/api/projets/{pid}/kanban")).json()
    assert k["config_execution"] is False
    async with sessions() as s:
        t = Tache(
            projet_id=pid, titre="t", colonne="bloquee", rang=1000, origine="manuel",
            resume_blocage="raison",
        )  # fmt: skip
        p1, p2 = Pipeline(projet_id=pid, type="dev"), Pipeline(projet_id=pid, type="dev")
        s.add_all([t, p1, p2])
        await s.flush()
        for n, p in ((1, p1), (2, p2)):
            s.add(ExecutionDev(
                pipeline_id=p.id, tache_id=t.id, n=n, branche="b", espace="e", base="m",
                base_sha="x", phase="fini", pr_url=f"https://github.com/o/r/pull/{n}",
            ))  # fmt: skip
        await s.commit()
    yaml = (
        "image: i\nchemins_tests: [t/**]\n"
        "commandes: {installer: i, tests: t, tests_cibles: 'p {fichiers}'}\n"
    )
    await client.put(f"/api/projets/{pid}/execution", json={"yaml": yaml})
    k = (await client.get(f"/api/projets/{pid}/kanban")).json()
    (v,) = k["taches"]
    assert (v["pr_url"], v["resume_blocage"]) == ("https://github.com/o/r/pull/2", "raison")
    assert k["config_execution"] is True


async def test_detail_pipeline_reprise_commentaires(client, sessions):
    pid = await _projet(client)
    async with sessions() as s:
        t = Tache(projet_id=pid, titre="t", colonne="en_cours", rang=1000, origine="manuel")
        p = Pipeline(projet_id=pid, type="dev")
        s.add_all([t, p])
        await s.flush()
        ex = ExecutionDev(
            pipeline_id=p.id, tache_id=t.id, n=2, branche="b", espace="e", base="m",
            base_sha="x", phase="code", mode="reprise",
        )  # fmt: skip
        s.add(ex)
        await s.flush()
        premier = {
            "type": "ligne", "texte": "premier", "chemin": "src/a.py", "ligne": 12,
            "tri": "code", "consigne": "corriger",
            "repondu_le": datetime(2026, 1, 3, tzinfo=UTC),
        }  # fmt: skip
        for gid, jour, kw in (
            (2, 2, {"type": "conversation", "texte": "plus tard"}),
            (1, 1, premier),
        ):
            s.add(CommentairePris(
                tache_id=t.id, execution_id=ex.id, github_id=gid, auteur="nico",
                url=f"https://github.com/o/r/pull/1#c{gid}",
                cree_le=datetime(2026, 1, jour, tzinfo=UTC), **kw,
            ))  # fmt: skip
        await s.commit()
        pipeline_id = p.id
    d = (await client.get(f"/api/pipelines/{pipeline_id}")).json()
    assert d["execution"]["mode"] == "reprise"
    a, b = d["commentaires"]
    assert (a["texte"], a["type"], a["chemin"], a["ligne"], a["tri"], a["consigne"]) == (
        "premier", "ligne", "src/a.py", 12, "code", "corriger",
    )  # fmt: skip
    assert a["repondu_le"] and a["auteur"] == "nico" and a["url"].endswith("#c1") and a["id"]
    assert (b["texte"], b["tri"], b["repondu_le"]) == ("plus tard", None, None)


async def test_tache_vue_reprise(client, sessions):
    pid = await _projet(client)
    async with sessions() as s:
        t = Tache(projet_id=pid, titre="t", colonne="en_cours", rang=1000, origine="manuel")
        p = Pipeline(projet_id=pid, type="dev")
        s.add_all([t, p])
        await s.flush()
        s.add(ExecutionDev(
            pipeline_id=p.id, tache_id=t.id, n=2, branche="b", espace="e", base="m",
            base_sha="x", phase="code", mode="reprise",
        ))  # fmt: skip
        await s.commit()
        tid = t.id

    async def reprise():
        k = (await client.get(f"/api/projets/{pid}/kanban")).json()
        return next(x for x in k["taches"] if x["id"] == tid)["reprise"]

    assert await reprise() is True
    async with sessions() as s:
        (await s.get(Tache, tid)).colonne = "en_revue"
        await s.commit()
    assert await reprise() is False
