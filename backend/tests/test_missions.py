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
    LigneMission,
    Missions,
    ReponseModele,
    ReponseOutil,
    Sante,
    lire_secrets,
)
from portail.outils import OutilsEspace

EXEMPLES = json.loads((Path(__file__).parents[2] / "docs/agents-contrat-v1.json").read_text())


def test_exemples_du_contrat():
    DemandeMission.model_validate(EXEMPLES["mission"])
    lignes = TypeAdapter(LigneMission)
    for cle in ("ligne_texte", "ligne_fin", "ligne_erreur"):
        lignes.validate_python(EXEMPLES[cle])
    DemandeModele.model_validate(EXEMPLES["demande_modele"])
    ReponseModele.model_validate(EXEMPLES["reponse_modele"])
    for ligne in EXEMPLES["demande_modele_flux_lignes"]:
        assert ligne["type"] in ("texte", "fin", "erreur")
    DemandeOutil.model_validate(EXEMPLES["demande_outil"])
    ReponseOutil.model_validate(EXEMPLES["reponse_outil"])
    Sante.model_validate(EXEMPLES["sante"])
    assert isinstance(EXEMPLES["erreur"]["erreur"], str)


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
    bloque = asyncio.Event()
    tache = asyncio.create_task(missions.en_vol(m, bloque.wait()))
    await asyncio.sleep(0)
    assert len(m.en_vol) == 1
    await missions.fermer(m)
    with pytest.raises(asyncio.CancelledError):
        await tache
    assert not m.en_vol


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
