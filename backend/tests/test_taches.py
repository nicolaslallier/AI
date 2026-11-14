import asyncio

from sqlalchemy import select

from portail.db import Pipeline, Tache, TacheEvenement
from portail.schemas import DonneesTache
from portail.taches import creer_tache, deplacer_tache


async def _projet(client):
    return (await client.post("/api/projets", json={"nom": "P"})).json()["id"]


async def _tache(client, pid, titre="T", **kw):
    r = await client.post(f"/api/projets/{pid}/taches", json={"titre": titre, **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def _agent(sessions, pid, titre="A"):
    async with sessions() as s:
        t = await creer_tache(
            s, pid, DonneesTache(titre=titre), "agent:plan", origine="agent", protegee=False
        )
        await s.commit()
        return t.id


async def _kanban(client, pid):
    return (await client.get(f"/api/projets/{pid}/kanban")).json()


async def test_creer_tache_manuelle_protegee(client, sessions):
    pid = await _projet(client)
    t = await _tache(client, pid)
    assert (t["protegee"], t["origine"], t["colonne"], t["rang"]) == (
        True,
        "manuel",
        "a_faire",
        1000,
    )
    async with sessions() as s:
        ev = (await s.scalars(select(TacheEvenement))).all()
    assert [(e.type, e.auteur, e.tache_id) for e in ev] == [("creation", "nicolas", t["id"])]


async def test_modifier_contenu_protege_et_versionne(client, sessions):
    pid = await _projet(client)
    tid = await _agent(sessions, pid)
    r = await client.patch(f"/api/taches/{tid}", json={"titre": "  Nouveau "})
    assert r.status_code == 200
    assert (r.json()["titre"], r.json()["protegee"], r.json()["version"]) == ("Nouveau", True, 2)


async def test_deplacer_ne_protege_pas(client, sessions):
    pid = await _projet(client)
    a, b = await _agent(sessions, pid), await _agent(sessions, pid)
    assert (
        await client.post(f"/api/taches/{a}/deplacer", json={"colonne": "prete"})
    ).status_code == 200
    await client.post(f"/api/taches/{b}/deplacer", json={"colonne": "prete", "avant_id": a})
    for t in (await _kanban(client, pid))["taches"]:
        assert (t["protegee"], t["version"]) == (False, 1)


async def test_colonne_inconnue_422(client):
    pid = await _projet(client)
    t = await _tache(client, pid)
    r = await client.post(f"/api/taches/{t['id']}/deplacer", json={"colonne": "nope"})
    assert r.status_code == 422


async def test_rangs_contigus(client):
    pid = await _projet(client)
    ids = [(await _tache(client, pid, f"T{i}"))["id"] for i in range(3)]
    await client.post(
        f"/api/taches/{ids[2]}/deplacer", json={"colonne": "a_faire", "avant_id": ids[0]}
    )
    taches = (await _kanban(client, pid))["taches"]
    assert [(t["id"], t["rang"]) for t in taches] == [
        (ids[2], 1000), (ids[0], 2000), (ids[1], 3000)
    ]  # fmt: skip


async def test_deplacements_concurrents(client, sessions):
    pid = await _projet(client)
    ids = [await _agent(sessions, pid, f"T{i}") for i in range(4)]

    async def bouger(tid):
        async with sessions() as s:
            t = await s.get(Tache, tid)
            await deplacer_tache(s, t, "prete", None, "nicolas")
            await asyncio.sleep(0.1)  # garde le verrou : l'autre doit attendre
            await s.commit()

    await asyncio.gather(*(bouger(i) for i in ids[:2]), bouger(ids[2]))
    taches = (await _kanban(client, pid))["taches"]
    prete = [t for t in taches if t["colonne"] == "prete"]
    assert sorted(t["rang"] for t in prete) == [1000, 2000, 3000]


async def test_cycle_refuse(client):
    pid = await _projet(client)
    a = await _tache(client, pid, "A")
    b = await _tache(client, pid, "B", depend_de=[a["id"]])
    r = await client.patch(f"/api/taches/{a['id']}", json={"depend_de": [b["id"]]})
    assert (r.status_code, r.json()["detail"]) == (422, "cycle de dépendances")
    r = await client.patch(f"/api/taches/{a['id']}", json={"depend_de": [a["id"]]})
    assert r.status_code == 422


async def test_dependance_autre_projet_refusee(client):
    p1, p2 = await _projet(client), await _projet(client)
    autre = await _tache(client, p2)
    r = await client.post(
        f"/api/projets/{p1}/taches", json={"titre": "X", "depend_de": [autre["id"]]}
    )
    assert (r.status_code, r.json()["detail"]) == (422, "dépendance hors projet ou inconnue")
    r = await client.post(f"/api/projets/{p1}/taches", json={"titre": "X", "depend_de": [999]})
    assert r.status_code == 422


async def test_verrou_409(client, sessions):
    pid = await _projet(client)
    t = await _tache(client, pid)
    async with sessions() as s:
        p = Pipeline(projet_id=pid, type="spec")
        s.add(p)
        await s.flush()
        (await s.get(Tache, t["id"])).verrou = p.id
        await s.commit()
    u = f"/api/taches/{t['id']}"
    for r in (
        await client.patch(u, json={"titre": "x"}),
        await client.post(f"{u}/deplacer", json={"colonne": "prete"}),
        await client.delete(u),
    ):
        assert r.status_code == 409
        assert "verrouillée par le pipeline" in r.json()["detail"]
    assert [x["id"] for x in (await _kanban(client, pid))["taches"]] == [t["id"]]


async def test_annuler_sans_verrou_409(client):
    pid = await _projet(client)
    t = await _tache(client, pid)
    r = await client.post(f"/api/taches/{t['id']}/annuler")
    assert (r.status_code, r.json()["detail"]) == (409, "rien à annuler")


async def test_annuler_leve_le_verrou(client, sessions):
    pid = await _projet(client)
    t = await _tache(client, pid)
    p = (await client.post("/api/pipelines", json={"projet_id": pid, "type": "spec"})).json()
    async with sessions() as s:
        x = await s.get(Tache, t["id"])
        x.verrou, x.colonne = p["id"], "en_cours"
        await s.commit()
    r = await client.post(f"/api/taches/{t['id']}/annuler")
    assert r.status_code == 200
    assert (r.json()["verrou"], r.json()["colonne"]) == (None, "a_faire")
    assert (await client.get(f"/api/pipelines/{p['id']}")).json()["etat"] == "echouee"


async def test_supprimer_garde_le_journal(client, sessions):
    pid = await _projet(client)
    t = await _tache(client, pid, "Ma tâche")
    assert (await client.delete(f"/api/taches/{t['id']}")).status_code == 204
    async with sessions() as s:
        ev = (
            await s.scalars(select(TacheEvenement).where(TacheEvenement.type == "suppression"))
        ).one()
    assert ev.donnees["titre"] == "Ma tâche"
    assert (await _kanban(client, pid))["taches"] == []


async def test_dependances_non_terminees(client):
    pid = await _projet(client)
    a = await _tache(client, pid, "A")
    b = await _tache(client, pid, "B", depend_de=[a["id"]])
    r = await client.post(f"/api/taches/{b['id']}/deplacer", json={"colonne": "prete"})
    assert r.status_code == 200
    vues = {t["id"]: t for t in (await _kanban(client, pid))["taches"]}
    assert vues[b["id"]]["depend_de"] == [a["id"]]
    assert vues[b["id"]]["dependances_non_terminees"] == [a["id"]]
    await client.post(f"/api/taches/{a['id']}/deplacer", json={"colonne": "terminee"})
    vues = {t["id"]: t for t in (await _kanban(client, pid))["taches"]}
    assert vues[b["id"]]["dependances_non_terminees"] == []
    assert (await _kanban(client, pid))["propositions"] == []


async def test_deplacements_concurrents_colonne_vide(client, sessions):
    pid = await _projet(client)
    a, b = await _agent(sessions, pid, "A"), await _agent(sessions, pid, "B")
    async with sessions() as s:
        (await s.get(Tache, b)).colonne = "en_cours"
        await s.commit()

    async def bouger(tid):
        async with sessions() as s:
            t = await s.get(Tache, tid)
            await deplacer_tache(s, t, "prete", None, "nicolas")
            await asyncio.sleep(0.1)
            await s.commit()

    await asyncio.gather(bouger(a), bouger(b))
    prete = [t for t in (await _kanban(client, pid))["taches"] if t["colonne"] == "prete"]
    assert sorted(t["rang"] for t in prete) == [1000, 2000]


async def test_patch_null_refuse(client):
    pid = await _projet(client)
    t = await _tache(client, pid)
    r = await client.patch(f"/api/taches/{t['id']}", json={"criteres": None})
    assert r.status_code == 422
