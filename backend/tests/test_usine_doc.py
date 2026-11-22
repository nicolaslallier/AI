import asyncio
import json

import pytest
from conftest import CATALOGUE_TEST, OUTILS, URL, FauxLLM, FauxNotifieur, _agent
from sqlalchemy import select

from portail.agents import Catalogue
from portail.config import Reglages
from portail.db import CarteDoc, Etape, Pipeline, Projet
from portail.depots import Depots
from portail.etats import Etat
from portail.llm import ErreurLLM
from portail.ordonnanceur import Ordonnanceur
from portail.usine_doc import UsineDoc

CATALOGUE_DOC = Catalogue(
    agents={
        **CATALOGUE_TEST.agents,
        "documentaliste": _agent("documentaliste"),
        "revue": _agent("revue", outils=OUTILS, produit="verdict", role="revue"),
    },
    pipelines={**CATALOGUE_TEST.pipelines, "doc": ["documentaliste", "revue"]},
    modeles_permis=["m", "g"],
)


def texte(t):
    return {"content": t}


def verdict(decision, *remarques):
    return texte(json.dumps({"decision": decision, "remarques": list(remarques)}))


@pytest.fixture
def usine(sessions, tmp_path):
    r = Reglages(database_url=URL, donnees_dir=tmp_path / "donnees", url_publique="https://p.x")
    return UsineDoc(
        sessions, CATALOGUE_DOC, FauxLLM(), Depots(tmp_path / "donnees", ""), None, r,
        FauxNotifieur(),
    )  # fmt: skip


async def _carte(sessions, depot, colonne="a_rediger") -> int:
    async with sessions() as s:
        p = Projet(nom="p", depot_url=f"file://{depot}")
        s.add(p)
        await s.flush()
        c = CarteDoc(
            projet_id=p.id, titre="Guide", genre="guide", consigne="Pour démarrer.",
            chemin=f"01 - Projets/p/Docs/p - Guide {colonne}.md", remarques=[], colonne=colonne,
        )  # fmt: skip
        s.add(c)
        await s.commit()
        return c.id


async def _lire(sessions, cid):
    async with sessions() as s:
        c = await s.get(CarteDoc, cid)
        p = c.pipeline_id and await s.get(Pipeline, c.pipeline_id)
        return c, p


async def _tourner(usine):
    await asyncio.gather(*await usine.tour(1))


async def test_nominal_a_valider(usine, sessions, depot_origine):
    cid = await _carte(sessions, depot_origine)
    usine._llm.reponses = [texte("# Guide\n\nTexte."), verdict("ok")]
    await _tourner(usine)
    c, p = await _lire(sessions, cid)
    assert c.erreur is None, c.erreur
    assert (c.colonne, c.contenu, c.erreur, p.type, p.etat) == (
        "a_valider",
        "# Guide\n\nTexte.",
        None,
        "doc",
        Etat.TERMINEE,
    )
    assert len(c.sha) == 40
    assert usine._notifieur.envoyes == [
        {"titre": f"Portail — doc D{cid}", "message": "Doc à valider", "lien": "https://p.x/docs"}
    ]
    # le rédacteur lit le dépôt sans pouvoir l'écrire
    noms = {o["function"]["name"] for o in usine._llm.appels[0]["outils"]}
    assert noms == {"lister", "lire", "chercher"}
    assert "Pour démarrer." in json.dumps(usine._llm.appels[0]["messages"], ensure_ascii=False)
    assert usine.taches == {}


async def test_renvoi_puis_ok(usine, sessions, depot_origine):
    cid = await _carte(sessions, depot_origine)
    usine._llm.reponses = [
        texte("v1"),
        verdict("renvoyer_code", "ajoute l'installation"),
        texte("v2"),
        verdict("ok"),
    ]
    await _tourner(usine)
    c, _ = await _lire(sessions, cid)
    assert (c.colonne, c.contenu, c.renvois) == ("a_valider", "v2", 1)
    seconde = json.dumps(usine._llm.appels[2]["messages"], ensure_ascii=False)
    assert "ajoute l'installation" in seconde and "v1" in seconde
    async with sessions() as s:
        agents = (await s.scalars(select(Etape.agent).order_by(Etape.ordre))).all()
    assert agents == ["documentaliste", "revue", "documentaliste", "revue"]


async def test_renvois_max_passe_a_valider_avec_remarques(usine, sessions, depot_origine):
    usine._reglages.renvois_max = 0
    cid = await _carte(sessions, depot_origine)
    usine._llm.reponses = [texte("v1"), verdict("renvoyer_code", "faux")]
    await _tourner(usine)
    c, _ = await _lire(sessions, cid)
    assert (c.colonne, c.remarques) == ("a_valider", ["faux"])


async def test_verdict_illisible_passe_a_valider(usine, sessions, depot_origine):
    cid = await _carte(sessions, depot_origine)
    usine._llm.reponses = [texte("v1"), texte("bof"), texte("toujours bof")]
    await _tourner(usine)
    c, _ = await _lire(sessions, cid)
    assert c.colonne == "a_valider"


async def test_erreur_llm_carte_en_erreur_plus_tiree(usine, sessions, depot_origine):
    cid = await _carte(sessions, depot_origine)
    usine._llm.exception = ErreurLLM("modèle indisponible")
    await _tourner(usine)
    c, p = await _lire(sessions, cid)
    assert (c.colonne, c.erreur, p.etat) == ("a_rediger", "modèle indisponible", Etat.ECHOUEE)
    assert await usine.tour(1) == []


async def test_document_vide_en_erreur(usine, sessions, depot_origine):
    cid = await _carte(sessions, depot_origine)
    usine._llm.reponses = [texte("  ")]
    await _tourner(usine)
    c, _ = await _lire(sessions, cid)
    assert c.erreur == "document vide ou trop long"


async def test_reprise_remet_a_rediger(usine, sessions, depot_origine):
    cid = await _carte(sessions, depot_origine, "revue")
    async with sessions() as s:
        p = Pipeline(projet_id=1, type="doc", etat=Etat.EN_COURS)
        s.add(p)
        await s.flush()
        s.add(Etape(pipeline_id=p.id, ordre=0, agent="revue", etat=Etat.EN_COURS))
        (await s.get(CarteDoc, cid)).pipeline_id = p.id
        await s.commit()
    await usine.reprendre()
    c, p = await _lire(sessions, cid)
    assert (c.colonne, p.etat) == ("a_rediger", Etat.ECHOUEE)
    async with sessions() as s:
        assert await s.scalar(select(Etape.etat)) == Etat.ECHOUEE


class _FauxOrch:
    def __init__(self, occupees):
        self.taches = dict.fromkeys(range(occupees))


@pytest.mark.parametrize(("max_", "lancees"), [(1, 0), (2, 1)])
async def test_capacite_partagee_avec_le_dev(usine, sessions, depot_origine, max_, lancees):
    await _carte(sessions, depot_origine)
    usine._llm.reponses = [asyncio.Event()]  # la rédaction reste en cours
    ordo = Ordonnanceur(sessions, _FauxOrch(1), max_, usine)
    await ordo.tour()
    assert len(usine.taches) == lancees
    for t in usine.taches.values():
        t.cancel()
    await asyncio.gather(*usine.taches.values(), return_exceptions=True)
