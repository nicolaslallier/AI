import asyncio
import json
from pathlib import Path

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from portail import journal
from portail import missions as mod_missions
from portail.agents import Agent, Catalogue, CatalogueInvalide
from portail.boucle import ErreurOutils, ResultatBoucle, boucle_outils
from portail.execution import ConfigExecution
from portail.llm import ErreurLLM
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
    completer,
    lire_secrets,
    tourner,
)
from portail.outils import OutilsEspace
from tests.conftest import FauxAgent

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
    MessageLLM.model_validate(
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "lire", "arguments": "{}"}}
        ]}
    )  # fmt: skip
    MessageLLM.model_validate({"role": "tool", "content": "r", "tool_call_id": "a", "name": "lire"})


@pytest.mark.parametrize(
    "appel",
    [
        {"id": "a"},
        {"id": "a", "type": "function", "function": {"name": "lire", "arguments": {}}},
        {"id": "a", "type": "function", "function": {"name": "lire", "arguments": "{}", "z": 1}},
        {"id": "a", "type": "autre", "function": {"name": "lire", "arguments": "{}"}},
        {"id": "a", "type": "function", "function": {"name": "n" * 200, "arguments": "{}"}},
        {"id": "a", "type": "function", "function": {"name": "lire", "arguments": "x" * 300_000}},
        {"id": "a", "type": "function", "function": {"name": "lire", "arguments": "{}"}, "z": 1},
    ],
)
def test_tool_calls_stricts(appel):
    with pytest.raises(ValidationError):
        MessageLLM.model_validate({"role": "assistant", "content": None, "tool_calls": [appel]})


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


async def test_purge_ferme_vraiment_les_expirees():
    horloge = Horloge()
    missions = _missions(horloge)
    vieille = _ouvrir(missions)
    vieille.tache = asyncio.ensure_future(asyncio.Event().wait())
    en_vol = asyncio.ensure_future(asyncio.Event().wait())
    vieille.en_vol.add(en_vol)
    vieille.occupee = True
    horloge.t = 100
    _ouvrir(missions)
    await asyncio.sleep(0)
    assert vieille.fermee and not vieille.occupee
    assert vieille.tache.cancelled() and en_vol.cancelled()


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


# --- client de mission ---------------------------------------------------------


class _Outils:
    """Des outils de dépôt qui ne touchent à rien."""

    arret = False

    def __init__(self, panne=None):
        self.panne, self.executes = panne, []

    def schemas(self):
        return [
            {"type": "function", "function": {"name": n, "description": n, "parameters": {}}}
            for n in ("lister", "lire", "chercher")
        ]

    async def executer(self, nom, arguments):
        if self.panne:
            raise self.panne
        self.executes.append((nom, arguments))
        return "contenu", False


def _appel(nom="lire", arguments='{"chemin": "README.md"}', id_="a"):
    return {"id": id_, "type": "function", "function": {"name": nom, "arguments": arguments}}


def _messages():
    return [{"role": "system", "content": "p"}, {"role": "user", "content": "relis"}]


async def _tourner(faux, llm, outils=None, agent=None, messages=None, **kw):
    appels = []

    async def sur_appel(libelle, resultat):
        appels.append((libelle, resultat))

    messages = _messages() if messages is None else messages
    r = await faux.registre.faire_tourner(llm, agent or _agent(), messages, outils, sur_appel, **kw)
    return r, appels


def _jeton(faux):
    return faux.missions[0]["corps"]["jeton"]


def _morte(faux):
    assert faux.registre.trouver(f"Bearer {_jeton(faux)}") is None
    assert faux.registre._en_cours == []


async def test_requete_de_mission(faux_agent, faux_llm):
    faux_llm.reponses = [{"role": "assistant", "content": "ok"}]
    mission = journal.nouvelle_mission("revue")
    outils = _Outils()
    await _tourner(faux_agent, faux_llm, outils, _agent(outils=["lire", "chercher"], tours_max=7))
    [requete] = faux_agent.missions
    assert requete["entetes"]["authorization"] == f"Bearer {FauxAgent.SECRET}"
    corps = requete["corps"]
    assert (corps["contrat"], corps["agent"], corps["mission"]) == ("v1", "revue", mission)
    assert corps["jeton"] and corps["flux"] is False
    assert [s["function"]["name"] for s in corps["outils"]] == ["lire", "chercher"]
    assert corps["parametres"]["tours_max"] == 7
    assert FauxAgent.SECRET not in json.dumps(corps)
    _morte(faux_agent)


async def test_mission_avec_outils(faux_agent, faux_llm):
    faux_llm.reponses = [
        {"role": "assistant", "content": None, "tool_calls": [_appel()]},
        {"role": "assistant", "content": "fini"},
    ]
    messages = _messages()
    r, appels = await _tourner(faux_agent, faux_llm, _Outils(), messages=messages)
    assert r == ResultatBoucle(texte="fini", limite_atteinte=False)
    assert appels == [("lire(README.md)", "contenu")]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool", "assistant"]
    assert messages[2]["tool_calls"] == [_appel()]
    assert messages[3] == {"role": "tool", "tool_call_id": "a", "content": "contenu"}


async def test_flux_relaye_le_texte(faux_agent, faux_llm):
    async def jouer(demande, portail):
        yield {"type": "texte", "texte": "bon"}
        yield {"type": "texte", "texte": "jour"}
        yield {"type": "fin", "texte": "bonjour", "messages": [], "limite_atteinte": False}

    faux_agent.jouer = jouer
    recus = []

    async def sur_texte(t):
        recus.append(t)

    r, _ = await _tourner(faux_agent, faux_llm, sur_texte=sur_texte)
    assert faux_agent.missions[0]["corps"]["flux"] is True
    assert recus == ["bon", "jour"] and r.texte == "bonjour"


async def test_flux_demande_seulement_sans_outils(faux_agent, faux_llm):
    async def sur_texte(t): ...

    faux_llm.reponses = [{"role": "assistant", "content": "ok"}]
    await _tourner(faux_agent, faux_llm, _Outils(), sur_texte=sur_texte)
    assert faux_agent.missions[0]["corps"]["flux"] is False


async def test_agent_injoignable(faux_agent, faux_llm):
    faux_agent.joignable = False
    with pytest.raises(ErreurMission, match="« revue » injoignable"):
        await _tourner(faux_agent, faux_llm)
    assert faux_agent.missions == [] and faux_agent.registre._en_cours == []


async def test_contrat_incompatible(faux_agent, faux_llm):
    faux_agent.contrat = "v2"
    with pytest.raises(ErreurMission, match="« revue » : contrat incompatible"):
        await _tourner(faux_agent, faux_llm)
    assert faux_agent.missions == [] and faux_agent.registre._en_cours == []


def _fin(**kw):
    return {"type": "fin", "texte": "t", "messages": [], "limite_atteinte": False, **kw}


@pytest.mark.parametrize(
    ("lignes", "attendu"),
    [
        (
            [{"type": "erreur", "erreur": "boum " + "x" * 400}],
            "agent « revue » : mission en erreur",
        ),
        ([], "mission interrompue"),
        ([{"type": "texte", "texte": "a"}], "mission interrompue"),
        (["pas du json\n"], "mission interrompue"),
        ([{"type": "inconnu"}], "mission interrompue"),
        ([_fin(messages=[{"role": "user", "content": "x", "inventé": 1}])], "mission interrompue"),
        ([_fin(limite_atteinte="peut-être")], "mission interrompue"),
    ],
)
async def test_ligne_erreur_et_flux_coupe(faux_agent, faux_llm, lignes, attendu):
    async def jouer(demande, portail):
        for ligne in lignes:
            yield ligne

    faux_agent.jouer = jouer
    with pytest.raises(ErreurMission, match=attendu) as e:
        await _tourner(faux_agent, faux_llm)
    assert len(str(e.value)) < 330
    _morte(faux_agent)


async def test_refus_de_l_agent(faux_agent, faux_llm):
    faux_agent.code = 401
    with pytest.raises(ErreurMission, match=r"refusé la mission \(401\)"):
        await _tourner(faux_agent, faux_llm)
    _morte(faux_agent)


async def test_duree_depassee(faux_agent, faux_llm):
    faux_agent.registre.duree_s = 0.05

    async def jouer(demande, portail):
        await asyncio.Event().wait()
        yield {}

    faux_agent.jouer = jouer
    with pytest.raises(ErreurMission, match="durée de mission dépassée"):
        await _tourner(faux_agent, faux_llm)
    assert faux_agent.deconnecte.is_set()
    _morte(faux_agent)


@pytest.mark.parametrize(
    "borne", [{"LIGNE_MAX": 50}, {"LIGNES_MAX": 3}], ids=["ligne_trop_longue", "trop_de_lignes"]
)
async def test_reponse_de_l_agent_bornee(faux_agent, faux_llm, monkeypatch, borne):
    for nom, v in borne.items():
        monkeypatch.setattr(mod_missions, nom, v)

    async def jouer(demande, portail):
        for _ in range(10):
            yield {"type": "texte", "texte": "x" * 40}
        yield _fin()

    faux_agent.jouer = jouer
    with pytest.raises(ErreurMission, match="mission interrompue"):
        await _tourner(faux_agent, faux_llm)
    assert faux_agent.deconnecte.is_set()
    _morte(faux_agent)


async def test_erreur_du_portail_relevee(faux_agent, faux_llm):
    faux_llm.exception = ErreurLLM("corps LiteLLM")
    with pytest.raises(ErreurLLM) as e:
        await _tourner(faux_agent, faux_llm)
    assert "texte de l'agent" not in str(e.value)
    _morte(faux_agent)


async def test_erreur_d_outil_du_portail_relevee_et_flux_coupe(faux_agent, faux_llm):
    faux_llm.reponses = [{"role": "assistant", "content": None, "tool_calls": [_appel()]}]
    with pytest.raises(ErreurOutils, match="outil lire en échec") as e:
        await _tourner(faux_agent, faux_llm, _Outils(panne=RuntimeError("secret-ZZ")))
    assert "secret-ZZ" not in str(e.value) and not isinstance(e.value, ErreurMission)
    assert faux_agent.deconnecte.is_set()
    _morte(faux_agent)


async def test_limite_de_l_agent_jamais_crue(faux_agent, faux_llm):
    async def jouer(demande, portail):
        yield _fin(limite_atteinte=True)

    faux_agent.jouer = jouer
    r, _ = await _tourner(faux_agent, faux_llm)
    assert r.limite_atteinte is False  # seuls les compteurs du portail comptent


async def test_total_du_flux_borne(faux_agent, faux_llm, monkeypatch):
    monkeypatch.setattr(mod_missions, "TOTAL_MAX", 300)

    async def jouer(demande, portail):
        for _ in range(20):
            yield {"type": "texte", "texte": "x" * 40}
        yield _fin()

    faux_agent.jouer = jouer
    with pytest.raises(ErreurMission) as e:
        await _tourner(faux_agent, faux_llm)
    assert str(e.value) == "agent « revue » : mission interrompue"
    assert faux_agent.deconnecte.is_set()
    _morte(faux_agent)


async def test_lecture_lineaire_de_milliers_de_lignes(faux_agent, faux_llm):
    async def jouer(demande, portail):
        yield "".join('{"type": "texte", "texte": "a"}\n' for _ in range(20_000))
        yield _fin(texte="ok")

    faux_agent.jouer = jouer
    recus = []

    async def sur_texte(t):
        recus.append(t)

    r, _ = await asyncio.wait_for(_tourner(faux_agent, faux_llm, sur_texte=sur_texte), 10)
    assert r.texte == "ok" and len(recus) == 20_000


async def test_longue_ligne_par_petits_morceaux(faux_agent, faux_llm, monkeypatch):
    monkeypatch.setattr(mod_missions, "LIGNE_MAX", 5000)

    async def jouer(demande, portail):
        for _ in range(100):
            yield "x" * 100  # jamais de saut de ligne

    faux_agent.jouer = jouer
    with pytest.raises(ErreurMission, match="mission interrompue"):
        await _tourner(faux_agent, faux_llm)


class _Goutte(httpx.AsyncByteStream):
    def __init__(self, n, pause):
        self.n, self.pause = n, pause

    async def __aiter__(self):
        for _ in range(self.n):
            await asyncio.sleep(self.pause)
            yield b"x"


async def test_sante_delai_total_et_taille_bornee():
    def lent(request):
        return httpx.Response(200, stream=_Goutte(200, 0.02))

    def gros(request):
        return httpx.Response(200, content=b"x" * 10_000)

    for h in (lent, gros):
        missions = Missions({"revue": "s" * 32}, 60, transport=httpx.MockTransport(h))
        debut = asyncio.get_running_loop().time()
        assert await missions.sante(_agent(), delai_s=0.2) is None
        assert asyncio.get_running_loop().time() - debut < 1


async def test_la_limite_du_portail_n_est_pas_masquee(faux_agent, faux_llm):
    faux_llm.reponses = [{"role": "assistant", "content": "ok"}] * 3

    async def jouer(demande, portail):
        for _ in range(4):  # tours_max + 1 appels permis, le suivant est refusé
            await portail("modele", {"messages": [{"role": "user", "content": "x"}]})
        yield _fin(limite_atteinte=False)

    faux_agent.jouer = jouer
    r, _ = await _tourner(faux_agent, faux_llm, agent=_agent(tours_max=2))
    assert r.limite_atteinte is True


async def test_annulation_ferme_la_connexion(faux_agent, faux_llm):
    demarre = asyncio.Event()

    async def jouer(demande, portail):
        demarre.set()
        await asyncio.Event().wait()
        yield {}

    faux_agent.jouer = jouer
    tache = asyncio.create_task(_tourner(faux_agent, faux_llm, _Outils()))
    await asyncio.wait_for(demarre.wait(), 5)
    jeton = _jeton(faux_agent)
    tache.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tache
    assert faux_agent.deconnecte.is_set()
    r = await faux_agent.portail(jeton)("outils", {"nom": "lire", "arguments": "{}"})
    assert r.status_code == 401
    _morte(faux_agent)


async def test_fermer_annule_aussi_le_flux():
    missions = _missions()
    m = _ouvrir(missions)
    m.tache = asyncio.ensure_future(asyncio.Event().wait())
    await missions.fermer(m)
    assert m.tache.cancelled()


async def test_ouvrir_dans_le_try_pas_de_mission_orpheline(faux_agent, faux_llm):
    # des messages que le contrat refuse : la mission ne doit pas rester ouverte
    with pytest.raises(ErreurMission):
        await _tourner(faux_agent, faux_llm, messages=[{"role": "user", "content": "x", "z": 1}])
    assert faux_agent.registre._en_cours == [] and faux_agent.missions == []


async def test_sans_service_c_est_boucle_outils(faux_agent, faux_llm):
    agent = _agent(service=None)
    reponses = [{"role": "assistant", "content": "bonjour"}]
    faux_llm.reponses = list(reponses)
    attendu = await boucle_outils(faux_llm, agent, _messages(), _Outils(), _rien)
    faux_llm.reponses = list(reponses)
    r = await tourner(faux_llm, None, agent, _messages(), _Outils(), _rien)
    assert r == attendu == ResultatBoucle(texte="bonjour", limite_atteinte=False)
    assert faux_agent.missions == [] and faux_agent.sante == []


async def test_service_sans_registre(faux_llm):
    with pytest.raises(ErreurMission, match="registre des missions absent"):
        await tourner(faux_llm, None, _agent(), _messages(), _Outils(), _rien)
    with pytest.raises(ErreurMission, match="registre des missions absent"):
        await completer(faux_llm, None, _agent(), _messages(), {"type": "json_object"})


async def test_completer_ouvre_une_mission_sans_outils(faux_agent, faux_llm):
    format_ = {"type": "json_object"}
    faux_llm.reponses = [{"role": "assistant", "content": '<think>x</think>{"a": 1}'}] * 2
    messages = _messages()
    texte = await completer(faux_llm, faux_agent.registre, _agent(), messages, format_)
    corps = faux_agent.missions[0]["corps"]
    assert (corps["outils"], corps["response_format"]) == ([], format_)
    assert faux_llm.appels[-1]["response_format"] == format_
    assert texte == '{"a": 1}' and len(messages) == 2  # l'historique de l'appelant ne bouge pas
    # sans service : appel direct au modèle, réflexion retirée
    sans = _agent(service=None)
    assert await completer(faux_llm, None, sans, messages, format_) == '{"a": 1}'
    assert len(faux_agent.missions) == 1


async def test_completer_refuse_tout_outil(faux_agent, faux_llm):
    async def jouer(demande, portail):
        r = await portail("outils", {"nom": "ecrire", "arguments": "{}"})
        yield _fin(texte=str(r.status_code))

    faux_agent.jouer = jouer
    texte = await completer(faux_llm, faux_agent.registre, _agent(), _messages(), {"type": "x"})
    assert texte == "409"  # aucun appel au modèle n'a offert d'outil à cette mission


MARQUEUR = "ZZ-secret-7731"


async def test_flot_de_texte_interrompt_la_mission(faux_agent, faux_llm, monkeypatch):
    monkeypatch.setattr(mod_missions, "CONTENU_MAX", 100)

    async def jouer(demande, portail):
        for _ in range(10):
            yield {"type": "texte", "texte": "x" * 40}
        yield _fin()

    faux_agent.jouer = jouer
    recu = []

    async def sur_texte(t):
        recu.append(t)

    with pytest.raises(ErreurMission, match="mission interrompue"):
        await _tourner(faux_agent, faux_llm, sur_texte=sur_texte)
    assert sum(map(len, recu)) <= 100
    _morte(faux_agent)


@pytest.mark.parametrize(
    "ligne", [{"type": "texte", "texte": "x" * 500_001}, _fin(texte="x" * 500_001)]
)
async def test_ligne_de_texte_trop_longue_refusee(faux_agent, faux_llm, ligne):
    async def jouer(demande, portail):
        yield ligne

    faux_agent.jouer = jouer
    with pytest.raises(ErreurMission, match="mission interrompue"):
        await _tourner(faux_agent, faux_llm)
    _morte(faux_agent)


async def test_aucun_texte_de_l_agent_dans_l_erreur(faux_agent, faux_llm):
    async def jouer(demande, portail):
        yield {"type": "erreur", "erreur": f"@{MARQUEUR} https://x.test"}

    faux_agent.jouer = jouer
    with pytest.raises(ErreurMission) as e:
        await _tourner(faux_agent, faux_llm)
    assert str(e.value) == "agent « revue » : mission en erreur"
    faux_agent.contrat = MARQUEUR
    with pytest.raises(ErreurMission) as e:
        await _tourner(faux_agent, faux_llm)
    assert str(e.value) == "agent « revue » : contrat incompatible"


@pytest.mark.parametrize(
    "champ, valeur",
    [
        ("version", "v" * 65),
        ("version", "a b"),
        ("version", ""),
        ("contrat", "v" * 17),
        ("agent", "a b"),
    ],
)
async def test_sante_hors_bornes_agent_injoignable(faux_agent, faux_llm, champ, valeur):
    setattr(faux_agent, champ, valeur)
    assert await faux_agent.registre.sante(_agent()) is None


async def test_sante_d_un_autre_agent_refusee_avant_le_secret(faux_agent, faux_llm):
    faux_agent.agent = "tri"
    with pytest.raises(ErreurMission, match="« revue » : agent inattendu"):
        await _tourner(faux_agent, faux_llm)
    assert faux_agent.missions == [] and faux_agent.registre._en_cours == []
