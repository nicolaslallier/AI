import asyncio
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from portail import journal
from portail.agents import Agent, Catalogue, CatalogueInvalide
from portail.execution import ConfigExecution
from portail.missions import (
    DemandeMission,
    DemandeModele,
    DemandeOutil,
    ErreurMission,
    LigneFluxMission,
    LigneMission,
    MessageLLM,
    Missions,
    ReponseErreur,
    ReponseModele,
    ReponseOutil,
    Sante,
    lire_secrets,
)
from portail.outils import OutilsEspace

EXEMPLES = json.loads((Path(__file__).parents[2] / "docs/agents-contrat-v1.json").read_text())


def test_exemples_du_contrat():
    def aller_retour(modele, exemple):
        valide = modele.model_validate(exemple)
        assert valide.model_dump(mode="json", exclude_unset=True) == exemple

    aller_retour(DemandeMission, EXEMPLES["mission"])
    lignes, flux = TypeAdapter(LigneMission), TypeAdapter(LigneFluxMission)
    for cle in ("ligne_texte", "ligne_fin", "ligne_erreur"):
        assert (
            lignes.dump_python(lignes.validate_python(EXEMPLES[cle]), exclude_unset=True)
            == (EXEMPLES[cle])
        )
    aller_retour(DemandeModele, EXEMPLES["demande_modele"])
    aller_retour(ReponseModele, EXEMPLES["reponse_modele"])
    for ligne in EXEMPLES["demande_modele_flux_lignes"]:
        assert flux.dump_python(flux.validate_python(ligne), exclude_unset=True) == ligne
    aller_retour(DemandeOutil, EXEMPLES["demande_outil"])
    aller_retour(ReponseOutil, EXEMPLES["reponse_outil"])
    aller_retour(Sante, EXEMPLES["sante"])
    aller_retour(ReponseErreur, EXEMPLES["erreur"])


def test_faute_de_frappe_dans_un_exemple_echoue():
    with pytest.raises(ValidationError):
        DemandeModele.model_validate({**EXEMPLES["demande_modele"], "outil": True})


def test_message_refuse_les_champs_inventes():
    with pytest.raises(ValidationError):
        MessageLLM.model_validate({"role": "user", "content": "x", "inventé": "y" * 10})
    MessageLLM.model_validate({"role": "assistant", "content": None, "tool_calls": [{"id": "a"}]})
    MessageLLM.model_validate({"role": "tool", "content": "r", "tool_call_id": "a", "name": "lire"})


def test_bornes_des_demandes():
    with pytest.raises(ValidationError):
        DemandeModele.model_validate({"messages": [{"role": "user", "content": "x" * 600_000}]})
    with pytest.raises(ValidationError):
        DemandeModele.model_validate({"messages": [{"role": "user", "content": "x"}] * 2001})
    with pytest.raises(ValidationError):
        DemandeOutil.model_validate({"nom": "n" * 200, "arguments": "{}"})
    with pytest.raises(ValidationError):
        DemandeOutil.model_validate({"nom": "lire", "arguments": "x" * 300_000})


@pytest.mark.parametrize("extra", [{"model": "gpt-x"}, {"tools": []}])
def test_demande_modele_refuse_les_champs_inconnus(extra):
    with pytest.raises(ValidationError):
        DemandeModele.model_validate({"messages": [], **extra})


CFG = ConfigExecution(
    image="img",
    chemins_tests=["tests/**"],
    commandes={"installer": "uv sync", "tests": "pytest", "tests_cibles": "pytest {fichiers}"},
)


def _agent(nom="revue", **kw):
    base = {
        "nom": nom,
        "description": "d",
        "modele": "m",
        "prompt_systeme": "p",
        "contexte_max": 1000,
        "outils": ["lister", "lire", "chercher"],
        "service": "http://agent-revue:8080",
    }
    return Agent(**{**base, **kw})


class Horloge:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


async def _rien(nom, args):
    return None


def _ouvrir(missions, agent=None, outils=None):
    return missions.ouvrir(None, agent or _agent(), outils, _rien, "v0")


def _missions(horloge=None):
    return Missions({"revue": "s" * 32}, 60, horloge=horloge or Horloge())


def test_jeton_trouve_puis_mort_a_la_fermeture():
    missions = _missions()
    m = _ouvrir(missions)
    assert missions.trouver(f"Bearer {m.jeton}") is m
    asyncio.run(missions.fermer(m))
    assert missions.trouver(f"Bearer {m.jeton}") is None


@pytest.mark.parametrize("entete", [None, "", "Bearer ", "Basic x", "Bearer autre"])
def test_jeton_inconnu_ou_mal_forme(entete):
    missions = _missions()
    _ouvrir(missions)
    assert missions.trouver(entete) is None


def test_jeton_expire():
    horloge = Horloge()
    missions = _missions(horloge)
    m = _ouvrir(missions)
    horloge.t = 60
    assert missions.trouver(f"Bearer {m.jeton}") is m
    horloge.t = 61
    assert missions.trouver(f"Bearer {m.jeton}") is None


def test_deux_missions_deux_jetons():
    missions = _missions()
    journal.commencer(mission="abc")
    a, b = _ouvrir(missions), _ouvrir(missions)
    journal.commencer()
    assert a.id == b.id == "abc"
    assert a.jeton != b.jeton
    assert missions.trouver(f"Bearer {a.jeton}") is a
    assert missions.trouver(f"Bearer {b.jeton}") is b


def test_contexte_copie_a_l_ouverture():
    missions = _missions()
    journal.commencer(mission="abc", pipeline_id=3)
    m = _ouvrir(missions)
    journal.commencer()
    assert m.contexte == {"mission": "abc", "pipeline_id": 3}


def test_schemas_offerts(tmp_path):
    import subprocess

    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    outils = OutilsEspace(tmp_path, "tests", CFG, None)
    m = _ouvrir(_missions(), outils=outils)
    assert [s["function"]["name"] for s in m.schemas] == ["lister", "lire", "chercher"]
    assert m.noms == {"lister", "lire", "chercher"}
    assert _ouvrir(_missions()).schemas == []


async def test_outil_en_vol_annule_a_la_fermeture():
    missions = _missions()
    m = _ouvrir(missions)
    demarre, bloque, nettoye = asyncio.Event(), asyncio.Event(), []

    async def outil():
        demarre.set()
        try:
            await bloque.wait()
        finally:
            await asyncio.sleep(0)
            nettoye.append(True)

    tache = asyncio.create_task(missions.en_vol(m, outil()))
    await demarre.wait()
    assert len(m.en_vol) == 1
    await missions.fermer(m)
    assert nettoye == [True]  # annulé et terminé avant le retour de fermer
    assert not m.en_vol
    with pytest.raises(ErreurMission):  # la requête n'est pas annulée : elle apprend l'arrêt
        await tache


async def test_en_vol_apres_fermeture_n_execute_rien():
    missions = _missions()
    m = _ouvrir(missions)
    await missions.fermer(m)
    lance = []

    async def outil():
        lance.append(True)

    with pytest.raises(ErreurMission):
        await missions.en_vol(m, outil())
    assert lance == [] and not m.en_vol


async def test_annulation_de_la_requete_reste_une_annulation():
    missions = _missions()
    m = _ouvrir(missions)
    demarre = asyncio.Event()

    async def outil():
        demarre.set()
        await asyncio.Event().wait()

    tache = asyncio.create_task(missions.en_vol(m, outil()))
    await demarre.wait()
    tache.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tache


def test_jeton_absent_du_repr():
    m = _ouvrir(_missions())
    assert m.jeton not in repr(m)
    corps = {**EXEMPLES["mission"], "jeton": "JETON-SECRET-ZZ"}
    assert "JETON-SECRET-ZZ" not in repr(DemandeMission.model_validate(corps))


def test_ouvrir_purge_les_expirees():
    horloge = Horloge()
    missions = _missions(horloge)
    vieille = _ouvrir(missions)
    horloge.t = 100
    neuve = _ouvrir(missions)
    assert missions._en_cours == [neuve]
    assert vieille not in missions._en_cours


async def test_en_vol_rend_le_resultat():
    missions = _missions()
    m = _ouvrir(missions)

    async def deux():
        return 2

    assert await missions.en_vol(m, deux()) == 2
    assert not m.en_vol


def _catalogue(**services):
    return Catalogue(agents={n: _agent(n, service=s) for n, s in services.items()}, pipelines={})


def test_lire_secrets():
    cat = _catalogue(revue="http://agent-revue:8080", code=None)
    assert lire_secrets(cat, {"PORTAIL_AGENT_SECRET_REVUE": "x" * 32}) == {"revue": "x" * 32}


@pytest.mark.parametrize("environ", [{}, {"PORTAIL_AGENT_SECRET_REVUE": "court" * 6 + "a"}])
def test_lire_secrets_refuse_absent_ou_court(environ):
    cat = _catalogue(revue="http://agent-revue:8080")
    with pytest.raises(CatalogueInvalide, match="revue") as e:
        lire_secrets(cat, environ)
    assert "PORTAIL_AGENT_SECRET_REVUE" in str(e.value)
    for v in environ.values():
        assert v not in str(e.value)


def test_lire_secrets_refuse_un_secret_blanc():
    cat = _catalogue(revue="http://agent-revue:8080")
    with pytest.raises(CatalogueInvalide, match="revue"):
        lire_secrets(cat, {"PORTAIL_AGENT_SECRET_REVUE": " " * 40})


def test_lire_secrets_refuse_une_variable_partagee():
    cat = _catalogue(**{"a-b": "http://agent-a:8080", "a_b": "http://agent-b:8080"})
    with pytest.raises(CatalogueInvalide, match="PORTAIL_AGENT_SECRET_A_B"):
        lire_secrets(cat, {"PORTAIL_AGENT_SECRET_A_B": "x" * 32})
