import pytest
from conftest import CATALOGUE_TEST
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from portail.agents import Agent, Catalogue
from portail.db import Document, Pipeline, Projet, Proposition
from portail.etats import Etat
from portail.moteur import (
    Refus,
    annuler_pipeline,
    changer_etat,
    creer_pipeline,
    recuperer_interrompues,
    terminer_etape,
)


def _agent(nom):
    return Agent(nom=nom, description=nom, modele="m", prompt_systeme="p", contexte_max=1000)


CAT = Catalogue(agents={"a": _agent("a"), "b": _agent("b")}, pipelines={"double": ["a", "b"]})


async def _creer(session):
    projet = Projet(nom="p")
    session.add(projet)
    await session.flush()
    pipeline, _ = await creer_pipeline(session, CAT, projet.id, "double")
    await session.flush()
    await session.refresh(pipeline, ["etapes"])
    return pipeline


async def _relire(session, pipeline):
    pid = pipeline.id
    session.expire_all()
    r = await session.execute(
        select(Pipeline).where(Pipeline.id == pid).options(selectinload(Pipeline.etapes))
    )
    return r.scalar_one()


async def test_creer_pipeline_demarre_la_premiere_etape(sessions):
    async with sessions() as s:
        p = await _creer(s)
        assert [e.ordre for e in p.etapes] == [0, 1]
        assert [e.etat for e in p.etapes] == [Etat.EN_ATTENTE, Etat.A_FAIRE]
        assert p.etat == Etat.EN_ATTENTE


async def test_terminer_enchaine_sur_la_suivante(sessions):
    async with sessions() as s:
        p = await _creer(s)
        await terminer_etape(s, CAT, p.etapes[0])
        p = await _relire(s, p)
        assert [e.etat for e in p.etapes] == [Etat.TERMINEE, Etat.EN_ATTENTE]
        assert p.etat == Etat.EN_ATTENTE


async def test_terminer_la_derniere_termine_le_pipeline(sessions):
    async with sessions() as s:
        p = await _creer(s)
        await terminer_etape(s, CAT, p.etapes[0])
        await terminer_etape(s, CAT, p.etapes[1])
        p = await _relire(s, p)
        assert p.etat == Etat.TERMINEE


async def test_type_inconnu(sessions):
    async with sessions() as s:
        projet = Projet(nom="p")
        s.add(projet)
        await s.flush()
        with pytest.raises(Refus) as e:
            await creer_pipeline(s, CAT, projet.id, "inconnu")
        assert e.value.code == 404


async def test_recuperer_interrompues(sessions):
    async with sessions() as s:
        p = await _creer(s)
        await changer_etat(s, p.etapes[0], Etat.EN_COURS)
        assert await recuperer_interrompues(s) == 1
        p = await _relire(s, p)
        assert p.etapes[0].etat == Etat.ECHOUEE
        assert p.etapes[0].erreur == "interrompue par un redémarrage du serveur"
        assert p.etat == Etat.ECHOUEE


async def test_changer_etat_met_a_jour_maj_le(sessions):
    async with sessions() as s:
        p = await _creer(s)
        await s.refresh(p, ["maj_le"])
        avant = p.maj_le
        await changer_etat(s, p.etapes[0], Etat.EN_COURS)
        assert p.maj_le > avant


async def _projet(s, spec=True):
    projet = Projet(nom="p")
    s.add(projet)
    await s.flush()
    if spec:
        p, _ = await creer_pipeline(s, CATALOGUE_TEST, projet.id, "spec")
        s.add(
            Document(
                projet_id=projet.id,
                pipeline_id=p.id,
                etape_id=p.etapes[0].id,
                type="spec",
                etat="validee",
            )
        )
        await s.flush()
    return projet


async def test_etape_auto_demarre_en_cours(sessions):
    async with sessions() as s:
        projet = await _projet(s)
        p, a_lancer = await creer_pipeline(s, CATALOGUE_TEST, projet.id, "planification")
        assert p.etapes[0].etat == Etat.EN_COURS
        assert p.etapes[0].action == "rediger"
        assert a_lancer is p.etapes[0]


async def test_terminer_lance_l_etape_taches(sessions):
    async with sessions() as s:
        projet = await _projet(s)
        p, _ = await creer_pipeline(s, CATALOGUE_TEST, projet.id, "planification")
        suivante = await terminer_etape(s, CATALOGUE_TEST, p.etapes[0])
        assert suivante is p.etapes[1]
        assert suivante.etat == Etat.EN_COURS
        assert suivante.action == "taches"


async def test_planification_sans_spec_409(sessions):
    async with sessions() as s:
        projet = await _projet(s, spec=False)
        with pytest.raises(Refus) as e:
            await creer_pipeline(s, CATALOGUE_TEST, projet.id, "planification")
        assert (e.value.code, e.value.message) == (409, "aucune spec validée pour ce projet")


async def test_une_seule_planification_active_409(sessions):
    async with sessions() as s:
        projet = await _projet(s)
        await creer_pipeline(s, CATALOGUE_TEST, projet.id, "planification")
        with pytest.raises(Refus) as e:
            await creer_pipeline(s, CATALOGUE_TEST, projet.id, "planification")
        assert (e.value.code, e.value.message) == (
            409,
            "une planification est déjà en cours pour ce projet",
        )


async def test_planification_possible_apres_echec(sessions):
    async with sessions() as s:
        projet = await _projet(s)
        p, _ = await creer_pipeline(s, CATALOGUE_TEST, projet.id, "planification")
        await changer_etat(s, p.etapes[0], Etat.ECHOUEE, "boum")
        _, a_lancer = await creer_pipeline(s, CATALOGUE_TEST, projet.id, "planification")
        assert a_lancer is not None


async def test_annuler_rejette_les_propositions(sessions):
    async with sessions() as s:
        projet = await _projet(s)
        p, _ = await creer_pipeline(s, CATALOGUE_TEST, projet.id, "planification")
        e0 = p.etapes[0]
        for etat in ("ouverte", "acceptee"):
            s.add(
                Proposition(
                    pipeline_id=p.id,
                    etape_id=e0.id,
                    projet_id=projet.id,
                    sorte="nouvelle",
                    etat=etat,
                )
            )
        await s.flush()
        await annuler_pipeline(s, p)
        assert (e0.etat, e0.erreur) == (Etat.ECHOUEE, "annulé")
        assert p.etat == Etat.ECHOUEE
        etats = (await s.scalars(select(Proposition.etat).order_by(Proposition.id))).all()
        assert list(etats) == ["rejetee", "acceptee"]
        with pytest.raises(Refus) as e:
            await annuler_pipeline(s, p)
        assert e.value.code == 409
