from datetime import UTC, datetime, timedelta

from portail.agents import rangement
from portail.bureau import debut_du_jour
from portail.db import (
    ActionConversation,
    AppelLLM,
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


async def _appels(sessions, agent, mission, n=1, **kw):
    async with sessions() as s, s.begin():
        s.add_all(
            AppelLLM(
                agent=agent, modele="m", mission=mission, duree_ms=1, issue="ok",
                **{k: (v[i] if isinstance(v, list) else v) for k, v in kw.items()},
            )
            for i in range(n)
        )  # fmt: skip


async def test_activite_du_jour(client, sessions):
    hier = datetime.now(UTC) - timedelta(days=2)
    await _appels(sessions, "a", "m", 2, jetons_entree=[10, None], jetons_sortie=[5, None])
    await _appels(sessions, "a", "m0", jetons_entree=100, jetons_sortie=100, quand=hier)
    await _appels(sessions, "zzz", "mz", jetons_entree=1, jetons_sortie=1)
    b = await _bureau(client)
    assert (b["postes"]["a"]["appels_jour"], b["postes"]["a"]["jetons_jour"]) == (2, 15)
    assert b["postes"]["b"]["appels_jour"] == 0
    assert "zzz" not in b["postes"]


async def test_tour_de_la_mission_en_cours(client, sessions):
    _, eid = await _etape(sessions, "double", "a", "en_cours")
    await _appels(sessions, "a", "m1", 2, etape_id=eid)
    await _appels(sessions, "a", "m2", 3, etape_id=eid)
    assert (await _bureau(client))["postes"]["a"]["travaux"][0]["tour"] == 3


async def test_jauge_des_vrais_jetons(client, sessions):
    _, eid = await _etape(sessions, "double", "a", "en_cours")
    await _appels(sessions, "a", "m2", 3, etape_id=eid, jetons_entree=[1_000, 25_000, None])
    j = (await _bureau(client))["postes"]["a"]["travaux"][0]["jauge"]
    assert (j["utilises"], j["max"], j["niveau"]) == (25_000, 32_768, "alerte")


async def test_sans_usage_pas_de_jauge(client, sessions):
    _, eid = await _etape(sessions, "double", "a", "en_cours")
    await _appels(sessions, "a", "m", 2, etape_id=eid)
    t = (await _bureau(client))["postes"]["a"]["travaux"][0]
    assert t["jauge"] is None and t["tour"] == 2


async def test_sans_appel_ni_tour_ni_jauge(client, sessions):
    await _etape(sessions, "double", "a", "en_cours")
    t = (await _bureau(client))["postes"]["a"]["travaux"][0]
    assert t["jauge"] is None and t["tour"] is None


async def test_tour_seulement_au_travail(client, sessions):
    async with sessions() as s, s.begin():
        c = Conversation(agent="orchestrateur", etat="pret")
        s.add(c)
        await s.flush()
        s.add(ActionConversation(conversation_id=c.id, nom="x", etat="proposee"))
        cid = c.id
    await _appels(sessions, "orchestrateur", "m", 2, conversation_id=cid, jetons_entree=500)
    t = (await _bureau(client))["postes"]["orchestrateur"]["travaux"][0]
    assert t["etat"] == "en_attente" and t["tour"] is None
    assert t["jauge"]["utilises"] == 500


async def test_avis_tour_par_pipeline(client, sessions):
    pid, eid = await _etape(sessions, "planification", "plan", "terminee")
    async with sessions() as s, s.begin():
        pl = await s.get(Pipeline, pid)
        d = Document(projet_id=pl.projet_id, pipeline_id=pid, etape_id=eid, type="plan")
        s.add(d)
        await s.flush()
        s.add(Avis(document_id=d.id, version=1, agent="a", etat="en_cours"))
    await _appels(sessions, "a", "m", 2, pipeline_id=pid)
    # même agent, même pipeline, plus récentes, mais d'une étape : pas le tour de l'avis
    await _appels(sessions, "a", "m-etape", 3, pipeline_id=pid, etape_id=eid)
    assert (await _bureau(client))["postes"]["a"]["travaux"][0]["tour"] == 2


async def test_tour_conversation_au_travail(client, sessions):
    async with sessions() as s, s.begin():
        c = Conversation(agent="orchestrateur", etat="en_cours")
        s.add(c)
        await s.flush()
        cid = c.id
    await _appels(sessions, "orchestrateur", "m1", 2, conversation_id=cid)
    await _appels(sessions, "orchestrateur", "m2", 4, conversation_id=cid)
    t = (await _bureau(client))["postes"]["orchestrateur"]["travaux"][0]
    assert t["etat"] == "au_travail" and t["tour"] == 4


# --- détail d'un poste -------------------------------------------------


async def test_detail_modele_et_outils(client):
    r = await client.get("/api/bureau/spec")
    assert r.status_code == 200
    d = r.json()
    assert (d["nom"], d["modele"], d["outils"]) == ("spec", "m", ["lister", "lire", "chercher"])
    assert d["contexte_max"] == 32768 and d["missions"] == []


async def test_detail_sans_prompt(client, sessions):
    await _appels(sessions, "spec", "m1")
    r = await client.get("/api/bureau/spec")
    assert "prompt_systeme" not in r.json()
    assert not {"consigne_redaction", "consigne_avis"} & r.json().keys()
    assert "Tu es spec." not in r.text and "Rédige la spec." not in r.text


async def test_agent_inconnu_404(client):
    r = await client.get(f"/api/bureau/{MARQUEUR}")
    assert r.status_code == 404 and MARQUEUR not in r.text


async def _ligne(sessions, mission, quand, duree_ms=1000, issue="ok", **kw):
    async with sessions() as s, s.begin():
        s.add(
            AppelLLM(
                agent="a", modele="m", mission=mission, quand=quand, duree_ms=duree_ms,
                issue=issue, **kw,
            )
        )  # fmt: skip


async def test_dernieres_missions(client, sessions):
    t0 = datetime.now(UTC) - timedelta(hours=1)
    sec = lambda n: t0 + timedelta(seconds=n)
    await _ligne(sessions, "m1", sec(10), 4000, "erreur", tache_id=7, pipeline_id=3,
                 jetons_entree=100, jetons_sortie=10)  # fmt: skip
    await _ligne(sessions, "m1", sec(30), 2000, "ok", tache_id=7, pipeline_id=3,
                 jetons_entree=None, jetons_sortie=None)  # fmt: skip
    await _ligne(sessions, "m1", sec(40), 500, "ok", tache_id=7, pipeline_id=3,
                 jetons_entree=50, jetons_sortie=5)  # fmt: skip
    await _ligne(sessions, "m2", sec(100), conversation_id=9)
    await _ligne(sessions, "m3", sec(200), issue="delai")
    ms = (await client.get("/api/bureau/a")).json()["missions"]
    assert [m["mission"] for m in ms] == ["m3", "m2", "m1"]
    m1 = ms[2]
    assert (m1["appels"], m1["jetons_entree"], m1["jetons_sortie"]) == (3, 150, 15)
    assert m1["issue"] == "ok" and (m1["libelle"], m1["lien"]) == ("T7", "/pipelines/3")
    debut = sec(10) - timedelta(milliseconds=4000)
    assert datetime.fromisoformat(m1["debut"]) == debut
    assert m1["duree_ms"] == int((sec(40) - debut).total_seconds() * 1000)
    assert (ms[1]["libelle"], ms[1]["lien"]) == ("conversation #9", "/chat/9")
    assert ms[0]["lien"] is None and ms[0]["libelle"] is None and ms[0]["issue"] == "delai"


async def test_missions_limitees_a_dix(client, sessions):
    for i in range(12):
        await _appels(sessions, "a", f"m{i}")
    ms = (await client.get("/api/bureau/a")).json()["missions"]
    assert [m["mission"] for m in ms] == [f"m{i}" for i in range(11, 1, -1)]


async def test_lignes_sans_mission_ignorees(client, sessions):
    await _appels(sessions, "a", None, 3)
    await _appels(sessions, "a", "m1")
    ms = (await client.get("/api/bureau/a")).json()["missions"]
    assert [m["mission"] for m in ms] == ["m1"]
