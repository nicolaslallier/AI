from datetime import UTC, datetime, timedelta

from portail.agents import rangement
from portail.bureau import debut_du_jour
from portail.db import (
    ActionConversation,
    Avis,
    Conversation,
    Document,
    Etape,
    ExecutionDev,
    Pipeline,
    Projet,
    Tache,
)
from tests.conftest import CATALOGUE_TEST

MARQUEUR = "ZZ-secret-7731"


async def _projet(s) -> Projet:
    p = Projet(nom="p")
    s.add(p)
    await s.flush()
    return p


async def _etape(sessions, type_, agent, etat, erreur=None, pipeline_etat="en_cours", **pk):
    """Insère un pipeline et une étape ; rend (pipeline_id, etape_id)."""
    async with sessions() as s, s.begin():
        p = await _projet(s)
        pl = Pipeline(projet_id=p.id, type=type_, etat=pipeline_etat, **pk)
        s.add(pl)
        await s.flush()
        e = Etape(pipeline_id=pl.id, ordre=1, agent=agent, etat=etat, erreur=erreur)
        s.add(e)
        await s.flush()
        return pl.id, e.id


async def _bureau(client, **_):
    r = await client.get("/api/bureau")
    assert r.status_code == 200
    return r.json()


async def test_groupes_depuis_le_catalogue(client):
    b = await _bureau(client)
    attendu = [{"nom": n, "agents": a} for n, a in rangement(CATALOGUE_TEST)]
    assert b["groupes"] == attendu
    assert b["groupes"][-1]["nom"] is None
    assert set(b["postes"]) == set(CATALOGUE_TEST.agents)
    assert all(p["etat"] == "libre" and p["travaux"] == [] for p in b["postes"].values())


async def test_etape_en_cours_au_travail_avec_lien(client, sessions):
    pid, _ = await _etape(sessions, "planification", "plan", "en_cours")
    p = (await _bureau(client))["postes"]["plan"]
    assert p["etat"] == "au_travail"
    t = p["travaux"][0]
    assert (t["sorte"], t["etat"]) == ("etape", "au_travail")
    assert t["libelle"] == f"planification #{pid}"
    assert t["lien"] == f"/pipelines/{pid}"


async def test_etape_dev_libelle_tache(client, sessions):
    pid, _ = await _etape(sessions, "dev", "a", "en_cours")
    async with sessions() as s, s.begin():
        pl = await s.get(Pipeline, pid)
        t = Tache(projet_id=pl.projet_id, titre="t", rang=1, origine="manuel")
        s.add(t)
        await s.flush()
        s.add(
            ExecutionDev(
                pipeline_id=pid, tache_id=t.id, n=1, branche="b", espace="e", base="main",
                base_sha="x", phase="tests",
            )
        )  # fmt: skip
        tid = t.id
    t = (await _bureau(client))["postes"]["a"]["travaux"][0]
    assert t["libelle"] == f"T{tid}"
    assert t["lien"] == f"/pipelines/{pid}"


async def test_etape_en_attente_de_nicolas(client, sessions):
    await _etape(sessions, "planification", "plan", "en_attente", pipeline_etat="en_attente")
    p = (await _bureau(client))["postes"]["plan"]
    assert p["etat"] == "en_attente"
    assert p["travaux"][0]["etat"] == "en_attente"


async def test_deux_conversations_deux_travaux(client, sessions):
    async with sessions() as s, s.begin():
        cs = [Conversation(agent="orchestrateur", etat="en_cours") for _ in range(2)]
        s.add_all(cs)
        await s.flush()
        ids = sorted(c.id for c in cs)
    p = (await _bureau(client))["postes"]["orchestrateur"]
    assert [t["lien"] for t in p["travaux"]] == [f"/chat/{i}" for i in ids]
    assert [t["libelle"] for t in p["travaux"]] == [f"conversation #{i}" for i in ids]


async def test_action_proposee_en_attente(client, sessions):
    async with sessions() as s, s.begin():
        c1 = Conversation(agent="orchestrateur", etat="pret")
        c2 = Conversation(agent="pm", etat="en_cours")
        s.add_all([c1, c2])
        await s.flush()
        for c in (c1, c2):
            s.add(ActionConversation(conversation_id=c.id, nom="x", etat="proposee"))
    postes = (await _bureau(client))["postes"]
    assert postes["orchestrateur"]["etat"] == "en_attente"
    assert len(postes["pm"]["travaux"]) == 1
    assert postes["pm"]["etat"] == "au_travail"


async def test_erreur_du_jour_seulement(client, sessions):
    await _etape(sessions, "double", "a", "echouee", "boum", pipeline_etat="echouee")
    await _etape(sessions, "double", "b", "echouee", "annulé", pipeline_etat="echouee")
    async with sessions() as s, s.begin():
        s.add(Conversation(agent="pm", etat="erreur", erreur="boum"))
    postes = (await _bureau(client))["postes"]
    assert postes["a"]["etat"] == "en_erreur"
    assert postes["pm"]["etat"] == "en_erreur"
    assert postes["b"]["etat"] == "libre" and postes["b"]["travaux"] == []

    from portail.bureau import lire_bureau

    async with sessions() as s:
        plus_tard = datetime.now(UTC) + timedelta(days=2)
        b = await lire_bureau(s, CATALOGUE_TEST, plus_tard)
    assert b.postes["a"].etat == "libre" and b.postes["pm"].etat == "libre"


def test_debut_du_jour_minuit_toronto():
    d = debut_du_jour(datetime(2026, 11, 15, 3, 0, tzinfo=UTC))  # encore le 14 à Toronto
    assert (d.year, d.month, d.day, d.hour) == (2026, 11, 14, 0)
    assert d.utcoffset() == timedelta(hours=-5)


async def test_pipeline_annule_ou_termine_ignore(client, sessions):
    await _etape(sessions, "double", "a", "en_attente", pipeline_etat="terminee")
    p = (await _bureau(client))["postes"]["a"]
    assert p["travaux"] == [] and p["etat"] == "libre"


async def test_avis_en_cours_au_travail(client, sessions):
    pid, eid = await _etape(sessions, "planification", "plan", "terminee")
    async with sessions() as s, s.begin():
        pl = await s.get(Pipeline, pid)
        d = Document(projet_id=pl.projet_id, pipeline_id=pid, etape_id=eid, type="plan")
        s.add(d)
        await s.flush()
        s.add(Avis(document_id=d.id, version=1, agent="a", etat="en_cours"))
    p = (await _bureau(client))["postes"]["a"]
    assert p["etat"] == "au_travail"
    t = p["travaux"][0]
    assert (t["sorte"], t["libelle"], t["lien"]) == (
        "avis",
        f"avis plan #{pid}",
        f"/pipelines/{pid}",
    )


async def test_priorite_des_etats(client, sessions):
    await _etape(sessions, "double", "a", "echouee", "boum", pipeline_etat="echouee")
    await _etape(sessions, "double", "a", "en_cours")
    p = (await _bureau(client))["postes"]["a"]
    assert p["etat"] == "au_travail"
    assert [t["etat"] for t in p["travaux"]] == ["au_travail", "en_erreur"]


async def test_agent_hors_catalogue_ignore(client, sessions):
    await _etape(sessions, "double", "portail", "en_cours")
    b = await _bureau(client)
    assert "portail" not in b["postes"]
    assert all(p["travaux"] == [] for p in b["postes"].values())


async def test_bureau_sans_contenu(client, sessions):
    pid, eid = await _etape(sessions, "dev", "a", "echouee", MARQUEUR, pipeline_etat="echouee")
    async with sessions() as s, s.begin():
        pl = await s.get(Pipeline, pid)
        et = await s.get(Etape, eid)
        et.apercu = MARQUEUR
        et.action = MARQUEUR
        et.sha = MARQUEUR
        t = Tache(
            projet_id=pl.projet_id, titre=MARQUEUR, description=MARQUEUR, criteres=[MARQUEUR],
            fichiers=[MARQUEUR], rang=1, origine="manuel",
        )  # fmt: skip
        s.add(t)
        await s.flush()
        s.add(
            ExecutionDev(
                pipeline_id=pid, tache_id=t.id, n=1, branche=MARQUEUR, espace=MARQUEUR,
                base="main", base_sha=MARQUEUR, phase="tests", remarques=[MARQUEUR],
                fichiers_tests=[MARQUEUR], sortie_rouge=MARQUEUR,
            )
        )  # fmt: skip
        c = Conversation(agent="pm", titre=MARQUEUR, etat="erreur", erreur=MARQUEUR)
        c2 = Conversation(agent="orchestrateur", titre=MARQUEUR, etat="pret")
        s.add_all([c, c2])
        await s.flush()
        s.add(
            ActionConversation(
                conversation_id=c2.id, nom=MARQUEUR, parametres={"x": MARQUEUR},
                etat="proposee", resultat=MARQUEUR, lien=MARQUEUR,
            )
        )  # fmt: skip
        # un avis en cours, rendu par le bureau, sur un document chargé de contenu
        d = Document(
            projet_id=pl.projet_id, pipeline_id=pid, etape_id=eid, type="plan", contenu=MARQUEUR
        )
        s.add(d)
        await s.flush()
        s.add(Avis(document_id=d.id, version=1, agent="b", contenu=MARQUEUR, etat="en_cours"))
    b = await _bureau(client)
    assert MARQUEUR not in (await client.get("/api/bureau")).text
    assert b["postes"]["a"]["etat"] == "en_erreur"
    assert b["postes"]["b"]["travaux"][0]["sorte"] == "avis"
    assert b["postes"]["orchestrateur"]["etat"] == "en_attente"


async def test_agent_dans_deux_pipelines_un_seul_poste(client, sessions):
    from portail.agents import Catalogue

    cat = Catalogue(
        agents=CATALOGUE_TEST.agents,
        pipelines={"un": ["a", "b"], "deux": ["a", "plan"]},
    )
    await _etape(sessions, "un", "a", "en_cours")
    await _etape(sessions, "deux", "a", "en_attente", pipeline_etat="en_attente")
    from portail.bureau import lire_bureau

    async with sessions() as s:
        b = await lire_bureau(s, cat, datetime.now(UTC))
    assert list(b.postes).count("a") == 1
    assert [t.etat for t in b.postes["a"].travaux] == ["au_travail", "en_attente"]
    assert [g.nom for g in b.groupes if "a" in g.agents] == ["un", "deux"]


async def test_etape_abandonnee_pas_une_erreur(client, sessions):
    from portail.etats import REPRISE_ABANDONNEE

    await _etape(sessions, "double", "a", "echouee", REPRISE_ABANDONNEE, pipeline_etat="echouee")
    assert (await _bureau(client))["postes"]["a"]["etat"] == "libre"
