import pytest
from test_dev import CIBLES, CODE_OK, TESTS_OK, Monde, verdict

from portail.db import ExecutionDev, Pipeline, Projet, Tache
from portail.github import ErreurGitHub
from portail.ordonnanceur import Ordonnanceur
from portail.suivi_pr import SuiviPR


@pytest.fixture
async def monde(tmp_path, sessions):
    m = Monde(tmp_path, sessions)
    await m.creer()
    m.lanceur.codes = {CIBLES: [1]}
    m.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok", "propre")]
    m.pid = await m.lancer()  # tâche en revue, PR n° 1 ouverte
    m.github.etats[1] = "ouverte"
    m.ordo = Ordonnanceur(sessions, m.orch, 1)
    m.suivi = SuiviPR(sessions, m.github, m.orch, m.ordo)
    return m


async def _tache(monde, id=1):
    async with monde.sessions() as s:
        return await s.get(Tache, id)


async def test_fusionnee_termine_et_libere(monde):
    monde.github.etats[1] = "fusionnee"
    ex, *_ = await monde.etat(monde.pid)
    dossier = monde.reglages.espaces_dir / ex.espace
    assert dossier.exists()
    await monde.suivi.passer()
    t = await _tache(monde)
    assert (t.colonne, t.verrou) == ("terminee", None)
    assert not dossier.exists()
    assert monde.ordo._reveil.is_set()


async def test_fermee_retour_a_faire(monde):
    monde.github.etats[1] = "fermee"
    await monde.suivi.passer()
    t = await _tache(monde)
    assert (t.colonne, t.verrou) == ("a_faire", None)
    assert not monde.ordo._reveil.is_set()


async def test_ouverte_rien(monde):
    await monde.suivi.passer()
    t = await _tache(monde)
    assert (t.colonne, t.verrou) == ("en_revue", monde.pid)


async def test_verrou_autre_ignore(monde):
    monde.github.etats[1] = "fusionnee"
    async with monde.sessions() as s:
        (await s.get(Tache, 1)).verrou = None
        await s.commit()
    await monde.suivi.passer()
    assert (await _tache(monde)).colonne == "en_revue"


async def test_erreur_sur_une_pr_n_arrete_pas_les_autres(monde):
    async with monde.sessions() as s:
        p = await s.get(Projet, 1)
        t2 = Tache(projet_id=p.id, titre="b", colonne="en_revue", rang=2000, origine="manuel")
        s.add(t2)
        await s.flush()
        p2 = Pipeline(projet_id=p.id, type="dev")
        s.add(p2)
        await s.flush()
        t2.verrou = p2.id
        s.add(
            ExecutionDev(
                pipeline_id=p2.id, tache_id=t2.id, n=1, branche="b", espace="e2",
                base="main", base_sha="x", phase="fini", pr_numero=2,
            )
        )  # fmt: skip
        await s.commit()
    appels = []
    vrai = monde.github.etat_pr

    async def etat_pr(depot, numero):
        appels.append(numero)
        if numero == 2:
            raise ErreurGitHub("boum")
        return await vrai(depot, numero)

    monde.github.etat_pr = etat_pr
    monde.github.etats[1] = "fusionnee"
    await monde.suivi.passer()
    assert sorted(appels) == [1, 2]
    assert (await _tache(monde)).colonne == "terminee"
