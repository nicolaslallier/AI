from datetime import UTC, datetime, timedelta

import pytest
from conftest import commentaire
from sqlalchemy import select, update
from test_dev import CIBLES, CODE_OK, TESTS_OK, Monde, verdict

from portail.db import CommentairePris, ExecutionDev, Pipeline, Projet, Tache
from portail.github import ErreurGitHub
from portail.ordonnanceur import Ordonnanceur
from portail.suivi_pr import SuiviPR, lot_pret


@pytest.fixture
async def monde(tmp_path, sessions):
    m = Monde(tmp_path, sessions)
    await m.creer()
    m.lanceur.codes = {CIBLES: [1]}
    m.llm.reponses = [*TESTS_OK, *CODE_OK, verdict("ok", "propre")]
    m.pid = await m.lancer()  # tâche en revue, PR n° 1 ouverte
    m.github.etats[1] = "ouverte"
    m.ordo = Ordonnanceur(sessions, m.orch, 1)
    m.suivi = SuiviPR(sessions, m.github, m.orch, m.ordo, proprietaire="NicolasLallier")
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


# --- lot_pret (pur) ------------------------------------------------------

T0 = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)


def lot(commentaires, maintenant=T0 + timedelta(hours=1), deja=frozenset(), depuis=T0):
    return lot_pret(commentaires, set(deja), "nicolaslallier", depuis, maintenant, 600)


def revue(id_, texte="à revoir", etat="CHANGES_REQUESTED", **kw):
    return commentaire("revue", id_, texte, cree_le=T0, etat_revue=etat, **kw)


def test_revue_part_tout_de_suite_avec_ses_lignes():
    r = revue(1)
    ligne = commentaire("ligne", 2, cree_le=T0, revue_id=1, chemin="a.py", ligne=3)
    conv = commentaire("conversation", 3, cree_le=T0)
    assert lot([r, ligne, conv], maintenant=T0) == [r, ligne, conv]


def test_trois_conversations_rapprochees_une_seule_fois_apres_10_min():
    convs = [commentaire("conversation", i, cree_le=T0 + i * 2 * MIN) for i in range(3)]
    assert lot(convs, maintenant=T0 + 13 * MIN) == []
    assert lot(convs, maintenant=T0 + 14 * MIN) == convs


def test_approve_ne_declenche_rien():
    a = revue(1, "bravo", "APPROVED")
    ligne = commentaire("ligne", 2, cree_le=T0, revue_id=1, chemin="a.py", ligne=1)
    assert lot([a, ligne, revue(3, "x", "DISMISSED")]) == []


def test_revue_vide_sans_ligne_rien():
    assert lot([revue(1, "")]) == []


def test_revue_vide_avec_ligne_compte():
    ligne = commentaire("ligne", 2, cree_le=T0, revue_id=1, chemin="a.py", ligne=1)
    assert lot([revue(1, ""), ligne]) == [ligne]  # la revue vide n'entre pas dans le lot


def test_revue_emporte_les_conversations():
    r, conv = revue(1), commentaire("conversation", 2, cree_le=T0)
    assert lot([conv, r], maintenant=T0) == [r, conv]  # pas de délai d'attente


def test_filtre_auteur():
    def de(id_, auteur, type_="User"):
        return commentaire(
            "revue", id_, auteur=auteur, auteur_type=type_, cree_le=T0, etat_revue="COMMENTED"
        )

    pas_lui = [de(1, "dependabot[bot]", "Bot"), de(2, "autre"), de(3, "portail-ia[bot]", "Bot")]
    assert lot(pas_lui) == []
    lui = de(4, "NicolasLallier")
    assert lot([*pas_lui, lui]) == [lui]


def test_deja_pris_ignore():
    assert lot([revue(1)], deja={("revue", 1)}) == []
    assert lot([revue(1)], deja={("ligne", 1)}) == [revue(1)]


def test_avant_depuis_ignore():
    assert lot([revue(1)], depuis=T0 + MIN) == []


# --- SuiviPR : reprises --------------------------------------------------


async def _reprises(monde):
    async with monde.sessions() as s:
        return (
            await s.scalars(
                select(ExecutionDev).where(ExecutionDev.mode == "reprise").order_by(ExecutionDev.id)
            )
        ).all()


def _lu(monde, *commentaires):
    monde.github.lus[1] = list(commentaires)


def _revue_de_nicolas(id_=10):
    return commentaire("revue", id_, "corrige ça", etat_revue="CHANGES_REQUESTED")


async def test_suivi_cree_une_reprise_en_attente(monde):
    _lu(monde, _revue_de_nicolas())
    await monde.suivi.passer()
    (rep,) = await _reprises(monde)
    assert (rep.phase, rep.pr_numero) == ("attente", 1)
    _ex, tache, pipeline = await monde.etat(rep.pipeline_id)
    assert (pipeline.etat, tache.colonne, tache.verrou) == ("en_attente", "en_revue", monde.pid)
    assert monde.ordo._reveil.is_set()


async def test_reprise_en_attente_pas_de_seconde(monde):
    _lu(monde, _revue_de_nicolas())
    await monde.suivi.passer()
    _lu(monde, _revue_de_nicolas(), _revue_de_nicolas(11))
    await monde.suivi.passer()
    assert len(await _reprises(monde)) == 1


async def test_rien_traite_deux_fois_apres_redemarrage(monde):
    _lu(monde, _revue_de_nicolas())
    await monde.suivi.passer()
    (rep,) = await _reprises(monde)
    async with monde.sessions() as s:  # la reprise a fini : la tâche est de nouveau En revue
        (await s.get(Tache, 1)).verrou = rep.pipeline_id
        await s.execute(
            update(Pipeline).where(Pipeline.id == rep.pipeline_id).values(etat="terminee")
        )
        await s.commit()
    neuf = SuiviPR(
        monde.sessions, monde.github, monde.orch, monde.ordo, proprietaire="nicolaslallier"
    )
    await neuf.passer()
    assert len(await _reprises(monde)) == 1
    async with monde.sessions() as s:
        assert len((await s.scalars(select(CommentairePris))).all()) == 1


async def test_sans_proprietaire_aucune_lecture(monde):
    _lu(monde, _revue_de_nicolas())
    lectures = []

    async def revues(depot, numero):
        lectures.append(numero)
        return []

    monde.github.revues = revues
    sans = SuiviPR(monde.sessions, monde.github, monde.orch, monde.ordo)
    await sans.passer()
    assert lectures == [] and await _reprises(monde) == []
    monde.github.etats[1] = "fusionnee"  # le suivi de C1 continue
    await sans.passer()
    assert (await _tache(monde)).colonne == "terminee"
