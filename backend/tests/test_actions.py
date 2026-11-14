import pytest
from conftest import CATALOGUE_TEST
from sqlalchemy import select

from portail.actions import executer_action, valider_action
from portail.db import (
    ActionConversation,
    Conversation,
    Etape,
    Pipeline,
    Projet,
    Tache,
    TacheEvenement,
)
from portail.moteur import Refus, creer_pipeline, spec_courante
from portail.schemas import DonneesTache
from portail.taches import creer_tache


async def _projet(s) -> int:
    p = Projet(nom="P")
    s.add(p)
    await s.flush()
    return p.id


async def _tache(s, pid, **kw) -> Tache:
    return await creer_tache(
        s, pid, DonneesTache(titre="T"), "agent:plan", origine="agent", protegee=False, **kw
    )


async def _action(s, nom, parametres) -> ActionConversation:
    c = Conversation()
    s.add(c)
    await s.flush()
    a = ActionConversation(conversation_id=c.id, nom=nom, parametres=parametres)
    s.add(a)
    await s.flush()
    assert a.etat == "proposee"
    return a


async def _refus(s, nom, parametres) -> Refus:
    with pytest.raises(Refus) as e:
        await valider_action(s, CATALOGUE_TEST, nom, parametres)
    assert e.value.code == 422
    return e.value


async def test_valider_lancer_pipeline_dev_refuse(sessions):
    async with sessions() as s:
        pid = await _projet(s)
        r = await _refus(s, "lancer_pipeline", {"projet_id": pid, "type": "dev"})
    assert "Prête" in r.message


async def test_valider_projet_inconnu(sessions):
    async with sessions() as s:
        await _refus(s, "creer_tache", {"projet_id": 999, "titre": "T"})
        await _refus(s, "lancer_pipeline", {"projet_id": 999, "type": "spec"})


async def test_valider_colonne_inconnue(sessions):
    async with sessions() as s:
        t = await _tache(s, await _projet(s))
        await _refus(s, "deplacer_tache", {"tache_id": t.id, "colonne": "nulle_part"})
        await _refus(s, "annuler_tache", {"tache_id": 999})
        assert await valider_action(
            s, CATALOGUE_TEST, "deplacer_tache", {"tache_id": t.id, "colonne": "prete"}
        ) == {"tache_id": t.id, "colonne": "prete"}


async def test_valider_parametres_invalides(sessions):
    async with sessions() as s:
        await _refus(s, "creer_projet", {"nom": "P", "depot_url": "http://ailleurs"})
        await _refus(s, "creer_projet", {})
        await _refus(s, "inconnue", {})
        assert await valider_action(s, CATALOGUE_TEST, "creer_projet", {"nom": " P "}) == {
            "nom": "P"
        }


async def test_valider_spec_vide(sessions):
    async with sessions() as s:
        pid = await _projet(s)
        await _refus(s, "deposer_spec", {"projet_id": pid, "contenu": "  \n "})


async def test_valider_spec_deja_ouverte(sessions):
    async with sessions() as s:
        pid = await _projet(s)
        await creer_pipeline(s, CATALOGUE_TEST, pid, "spec")
        r = await _refus(s, "deposer_spec", {"projet_id": pid, "contenu": "# Spec"})
    assert r.message == "un pipeline de spec est déjà ouvert : finis-le ou annule-le"


async def test_executer_creer_projet(sessions):
    async with sessions() as s:
        a = await _action(s, "creer_projet", {"nom": "Nouveau", "description": "d"})
        ex = await executer_action(s, CATALOGUE_TEST, a)
        p = await s.scalar(select(Projet).where(Projet.nom == "Nouveau"))
    assert p is not None and p.description == "d"
    assert ex.lien == f"/projets/{p.id}" and ex.etapes_a_lancer == []


async def test_executer_deposer_spec_validee(sessions):
    async with sessions() as s:
        pid = await _projet(s)
        a = await _action(s, "deposer_spec", {"projet_id": pid, "contenu": "# Spec"})
        ex = await executer_action(s, CATALOGUE_TEST, a)
        assert (await spec_courante(s, pid)).contenu == "# Spec"
        pipeline = await s.scalar(select(Pipeline).where(Pipeline.type == "spec"))
        assert pipeline.etat == "terminee" and ex.lien == f"/pipelines/{pipeline.id}"
        await creer_pipeline(s, CATALOGUE_TEST, pid, "planification")


async def test_executer_lancer_planification(sessions):
    async with sessions() as s:
        pid = await _projet(s)
        await executer_action(
            s, CATALOGUE_TEST, await _action(s, "deposer_spec", {"projet_id": pid, "contenu": "S"})
        )
        a = await _action(s, "lancer_pipeline", {"projet_id": pid, "type": "planification"})
        ex = await executer_action(s, CATALOGUE_TEST, a)
        etapes = [await s.get(Etape, i) for i in ex.etapes_a_lancer]
    assert [e.agent for e in etapes] == ["plan"]


async def test_executer_creer_tache(sessions):
    async with sessions() as s:
        pid = await _projet(s)
        a = await _action(s, "creer_tache", {"projet_id": pid, "titre": "Nouvelle"})
        ex = await executer_action(s, CATALOGUE_TEST, a)
        t = await s.scalar(select(Tache).where(Tache.titre == "Nouvelle"))
    assert t.protegee is True and ex.lien == f"/projets/{pid}/kanban"


async def test_executer_deplacer_vers_prete(sessions):
    async with sessions() as s:
        t = await _tache(s, await _projet(s))
        a = await _action(s, "deplacer_tache", {"tache_id": t.id, "colonne": "prete"})
        await executer_action(s, CATALOGUE_TEST, a)
        ev = await s.scalar(select(TacheEvenement).where(TacheEvenement.type == "deplacement"))
    assert t.colonne == "prete" and ev.auteur == "nicolas"


async def test_executer_modifier_tache_la_protege(sessions):
    async with sessions() as s:
        t = await _tache(s, await _projet(s))
        a = await _action(s, "modifier_tache", {"tache_id": t.id, "titre": "Autre"})
        await executer_action(s, CATALOGUE_TEST, a)
    assert t.protegee is True and t.titre == "Autre" and t.criteres == []


async def test_confirmer_refus_du_portail(sessions):
    async with sessions() as s:
        pid = await _projet(s)
        pipeline, _ = await creer_pipeline(s, CATALOGUE_TEST, pid, "spec")
        t = await _tache(s, pid)
        t.verrou = pipeline.id
        a = await _action(s, "deplacer_tache", {"tache_id": t.id, "colonne": "prete"})
        await s.commit()
        with pytest.raises(Refus):
            async with s.begin_nested():
                await executer_action(s, CATALOGUE_TEST, a)
        await s.commit()
    async with sessions() as s:
        assert (await s.get(Tache, t.id)).colonne == "a_faire"
        types = (await s.scalars(select(TacheEvenement.type))).all()
    assert types == ["creation"]


@pytest.mark.parametrize("mauvais", [2**40, 0, -1, True, "3"])
async def test_valider_ids_hors_bornes(sessions, mauvais):
    async with sessions() as s:
        pid = await _projet(s)
        t = await _tache(s, pid)
        await _refus(s, "lancer_pipeline", {"projet_id": mauvais, "type": "spec"})
        await _refus(s, "deplacer_tache", {"tache_id": mauvais, "colonne": "prete"})
        await _refus(s, "creer_tache", {"projet_id": pid, "titre": "T", "depend_de": [mauvais]})
        await _refus(s, "modifier_tache", {"tache_id": t.id, "depend_de": [mauvais]})
        await _refus(s, "modifier_tache", {"tache_id": t.id, "depend_de": None})
        assert (await s.get(Tache, t.id)).colonne == "a_faire"  # transaction toujours utilisable
