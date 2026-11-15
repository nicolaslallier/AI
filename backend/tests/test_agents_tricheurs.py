"""Un agent en conteneur n'est pas fiable : le portail tient ses limites sans lui faire confiance.

Chaque test remplace `FauxAgent.jouer` (ou parle aux routes `/interne/`) comme le ferait un agent
qui triche. Un test rouge ici est une faille du portail, pas un test à assouplir.
"""

import asyncio
import json

import pytest
from conftest import FauxAgent, _agent
from test_dev import (
    CIBLES,
    CODE_OK,
    TESTS_OK,
    appel,
    monde_conteneur,  # noqa: F401  (fixture)
    texte,
)
from test_injection import Espace
from test_missions import _agent as _agent_service
from test_missions import _Outils

from portail.boucle import ErreurOutils
from portail.missions import ErreurMission


@pytest.fixture
def espace(tmp_path):
    return Espace(tmp_path)


def _ouvrir(
    interne, espace, role="code", outils=("lister", "lire", "chercher", "ecrire", "lancer"), **kw
):
    agent = _agent(role, outils=list(outils), role=role, **kw)
    return interne.ouvrir(agent, espace.outils(role))


def _outil(nom_, **args):
    return {"nom": nom_, "arguments": json.dumps(args)}


# --- ce que l'agent n'a pas le droit de faire, même avec un jeton valide -----------------------


async def test_outil_non_permis(interne, espace):
    # `revue` n'offre ni `ecrire` ni `lancer` : dans agent.outils ou non, m.schemas fait foi
    m = _ouvrir(interne, espace, "revue", ("lister", "lire", "chercher", "ecrire", "lancer"))
    avant = espace.contenus()
    for corps in (_outil("ecrire", chemin="src/a.py", contenu="x"), _outil("lancer", nom="tests")):
        r = await interne.post("outils", m, corps)
        assert r.json()["resultat"].startswith("erreur : outil non autorisé")
    assert espace.contenus() == avant and espace.lances == []


@pytest.mark.parametrize(
    ("outil", "args"),
    [
        ("lire", {"chemin": "../../etc/passwd"}),
        ("lire", {"chemin": "/etc/passwd"}),
        ("lire", {"chemin": "sortie/secret.txt"}),  # lien symbolique sortant
        ("ecrire", {"chemin": "../dehors/secret.txt", "contenu": "x"}),
        ("ecrire", {"chemin": ".git/config", "contenu": "x"}),
        ("ecrire", {"chemin": "tests/test_a.py", "contenu": "triche"}),
    ],
)
async def test_chemin_hors_espace(interne, espace, outil, args):
    (espace.racine / "sortie").symlink_to(espace.dehors)
    m = _ouvrir(interne, espace, "code")
    avant, dehors = espace.contenus(), (espace.dehors / "secret.txt").read_text()
    r = await interne.post("outils", m, _outil(outil, **args))
    assert r.status_code == 200 and r.json()["resultat"].startswith("erreur")
    assert "SECRET-FACTICE" not in r.text
    assert espace.contenus() == avant
    assert (espace.dehors / "secret.txt").read_text() == dehors


async def test_jeton_d_une_autre_mission(interne, espace):
    a = _ouvrir(interne, espace, "revue", ("lister", "lire", "chercher"))
    b = _ouvrir(interne, espace, "code")
    avant = espace.contenus()
    r = await interne.post("outils", a, _outil("ecrire", chemin="src/n.py", contenu="x"))
    assert r.json()["resultat"].startswith("erreur : outil non autorisé")  # B l'a, pas A
    assert espace.contenus() == avant
    await interne.missions.fermer(b)
    assert (await interne.post("outils", b, _outil("lire", chemin="README.md"))).status_code == 401
    forge = await interne.client.post(
        "/interne/outils", json=_outil("lire", chemin="README.md"),
        headers={"Authorization": "Bearer " + "z" * 43},
    )  # fmt: skip
    assert forge.status_code == 401
    interne.horloge.t = 100  # après l'échéance de A (60 s), sans que personne l'ait fermée
    assert (await interne.post("outils", a, _outil("lire", chemin="README.md"))).status_code == 401


async def test_neuf_outils_par_tour(interne, espace):
    m = _ouvrir(interne, espace, "code")
    resultats = [
        (await interne.post("outils", m, _outil("lire", chemin="README.md"))).json()["resultat"]
        for _ in range(9)
    ]
    assert sum("Ignore tes consignes" in r for r in resultats) == 8
    assert resultats[8] == "erreur : trop d'appels dans un même tour, ignoré"


async def test_contexte_gonfle(interne):
    m = interne.ouvrir(_agent("revue", contexte_max=50))
    gros = {"messages": [{"role": "user", "content": "x" * 4000}]}
    assert (await interne.post("modele", m, gros)).status_code == 413
    assert interne.llm.appels == [] and m.appels_modele == 0


async def test_modele_et_outils_choisis_par_l_agent(interne):
    m = interne.ouvrir()
    base = {"messages": [{"role": "user", "content": "x"}]}
    for extra in (
        {"model": "gpt-x"},
        {"tools": []},
        {"temperature": 2},
        {"flux": True, "outils": True},
    ):
        assert (await interne.post("modele", m, {**base, **extra})).status_code == 422
    assert interne.llm.appels == []


# --- un agent qui ne s'arrête pas, qui ment ou qui attend --------------------------------------


async def _tourner(faux, llm, outils=None, **kw):
    async def sur_appel(libelle, resultat): ...

    return await faux.registre.faire_tourner(
        llm, _agent_service(faux.agent, **kw.pop("agent", {})), [{"role": "user", "content": "go"}],
        outils, sur_appel, **kw,
    )  # fmt: skip


async def test_depasse_les_tours(faux_agent, faux_llm):
    outils = _Outils()
    faux_llm.reponses = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"a{i}", "type": "function", "function": {"name": "lire", "arguments": "{}"}}
        ]} for i in range(3)
    ]  # fmt: skip

    async def jouer(demande, portail):
        for _ in range(10):  # l'agent ne s'arrête pas de lui-même
            r = await portail(
                "modele", {"messages": [{"role": "user", "content": "x"}], "outils": True}
            )
            if r.status_code != 200:
                break
            for _ in range(12):
                await portail("outils", {"nom": "lire", "arguments": "{}"})
        yield {"type": "fin", "texte": "fini", "messages": [], "limite_atteinte": False}

    faux_agent.jouer = jouer
    r = await _tourner(faux_agent, faux_llm, outils, agent={"tours_max": 2})
    assert len(faux_llm.appels) == 3  # tours_max + 1 ; les suivants : 429
    assert faux_llm.appels[-1]["outils"] is None
    assert len(outils.executes) == 2 * 8  # huit par appel qui offre des outils, pas un de plus
    assert r.limite_atteinte is True  # malgré `limite_atteinte: false` de l'agent


async def test_mal_formes_arretent_la_mission(faux_agent, faux_llm):
    faux_llm.reponses = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "zzz", "arguments": "{}"}}
        ]}
    ]  # fmt: skip

    async def jouer(demande, portail):
        await portail("modele", {"messages": [{"role": "user", "content": "x"}], "outils": True})
        for i in range(10):
            r = await portail("outils", {"nom": f"inventé{i}", "arguments": "{}"})
            if r.status_code != 200:
                break
        yield {"type": "fin", "texte": "fini", "messages": [], "limite_atteinte": False}

    faux_agent.jouer = jouer
    with pytest.raises(ErreurOutils, match="ne gère pas correctement les outils") as e:
        await _tourner(faux_agent, faux_llm, _Outils())
    assert not isinstance(e.value, ErreurMission)
    assert faux_agent.deconnecte.is_set()


async def test_mal_formes_bloquent_le_pipeline(monde_conteneur):  # noqa: F811
    monde, faux = monde_conteneur
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, appel("zzz")]

    async def jouer(demande, portail):
        r = await portail(
            "modele", {"messages": [{"role": "user", "content": "x"}], "outils": True}
        )
        assert r.status_code == 200
        for i in range(10):
            r = await portail("outils", {"nom": f"inventé{i}", "arguments": "{}"})
        yield {"type": "fin", "texte": "{}", "messages": [], "limite_atteinte": False}

    faux.jouer = jouer
    pid = await monde.lancer()
    ex, tache, pipeline = await monde.etat(pid)
    assert pipeline.etat == "echouee" and "ne gère pas correctement" in tache.resume_blocage
    from conftest import valeur

    assert valeur("portail_blocages_total", cause="outils", phase=ex.phase) >= 1


async def test_duree_depassee(faux_agent, faux_llm):
    faux_agent.registre.duree_s = 0.05

    async def jouer(demande, portail):
        await asyncio.Event().wait()
        yield {}

    faux_agent.jouer = jouer
    with pytest.raises(ErreurMission, match="durée de mission dépassée"):
        await _tourner(faux_agent, faux_llm)
    assert faux_agent.deconnecte.is_set()
    jeton = faux_agent.missions[0]["corps"]["jeton"]
    r = await faux_agent.portail(jeton)("outils", {"nom": "lire", "arguments": "{}"})
    assert r.status_code == 401


async def test_annulee_ne_peut_plus_ecrire(faux_agent, faux_llm, espace):
    """L'appelant annule la mission pendant que l'agent prépare un `ecrire` : il arrive trop tard."""
    outils = espace.outils("code")
    demarre, avant = asyncio.Event(), espace.contenus()

    async def jouer(demande, portail):
        r = await portail(
            "modele", {"messages": [{"role": "user", "content": "x"}], "outils": True}
        )
        assert r.status_code == 200
        demarre.set()
        await asyncio.Event().wait()
        yield {}

    faux_llm.reponses = [{"role": "assistant", "content": "ok"}]
    faux_agent.jouer = jouer
    agent = {"outils": ["lister", "lire", "chercher", "ecrire"], "role": "code"}
    tache = asyncio.create_task(_tourner(faux_agent, faux_llm, outils, agent=agent))
    await asyncio.wait_for(demarre.wait(), 5)
    jeton = faux_agent.missions[0]["corps"]["jeton"]
    tache.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tache
    r = await faux_agent.portail(jeton)("outils", _outil("ecrire", chemin="src/n.py", contenu="x"))
    assert r.status_code == 401
    assert espace.contenus() == avant and not (espace.racine / "src/n.py").exists()


async def test_requete_en_attente_ne_survit_pas_a_la_fermeture(interne, espace):
    """Une demande déjà authentifiée, dont le corps n'est pas arrivé, n'écrit rien après `fermer`."""
    m = _ouvrir(interne, espace, "code")
    lu, avant = asyncio.Event(), espace.contenus()

    async def corps():
        yield b'{"nom": "ecrire", "arguments": '
        lu.set()
        await asyncio.Event().wait()
        yield b"{}}"

    tache = asyncio.create_task(
        interne.client.post(
            "/interne/outils", content=corps(), headers={"Authorization": f"Bearer {m.jeton}"}
        )
    )
    await lu.wait()
    await interne.missions.fermer(m)
    r = await asyncio.wait_for(tache, 5)
    assert r.status_code == 409 and espace.contenus() == avant


async def test_echeance_sans_fermer(interne, espace):
    """Personne n'appelle `fermer` : l'échéance seule suffit à refuser, y compris en cours de route."""
    m = _ouvrir(interne, espace, "code")
    avant = espace.contenus()
    lu = asyncio.Event()

    async def corps():
        yield b'{"nom": "ecrire", "arguments": '
        lu.set()
        await asyncio.sleep(0.05)
        yield json.dumps(json.dumps({"chemin": "src/n.py", "contenu": "x"})).encode() + b"}"

    tache = asyncio.create_task(
        interne.client.post(
            "/interne/outils", content=corps(), headers={"Authorization": f"Bearer {m.jeton}"}
        )
    )
    await lu.wait()
    interne.horloge.t = 100  # l'échéance passe pendant que la demande est à mi-chemin
    assert (await asyncio.wait_for(tache, 5)).status_code == 409
    assert (await interne.post("outils", m, _outil("lire", chemin="README.md"))).status_code == 401
    assert espace.contenus() == avant


# --- ce que le portail envoie à l'agent --------------------------------------------------------


async def test_aucun_secret_dans_la_mission(monde_conteneur):  # noqa: F811
    monde, faux = monde_conteneur
    secrets = {
        "litellm_cle": "SECRET-LITELLM-01", "github_jeton": "SECRET-GITHUB-02",
        "lanceur_secret": "SECRET-LANCEUR-03", "github_app_cle": "SECRET-APPCLE-04",
        "ntfy_jeton": "SECRET-NTFY-05",
    }  # fmt: skip
    for nom, valeur in secrets.items():
        setattr(monde.reglages, nom, valeur)
    monde.lanceur.codes = {CIBLES: [1]}
    monde.llm.reponses = [*TESTS_OK, *CODE_OK, appel("lire", chemin="src/x.py"), texte("{}")]
    await monde.lancer()
    assert faux.missions and faux.sante
    recu = json.dumps([*faux.missions, *faux.sante], ensure_ascii=False)
    for valeur in secrets.values():
        assert valeur not in recu
    for requete in faux.missions:
        assert requete["entetes"]["authorization"] == f"Bearer {FauxAgent.SECRET}"
        assert FauxAgent.SECRET not in json.dumps(requete["corps"])
    for requete in faux.sante:
        assert "authorization" not in requete["entetes"]
