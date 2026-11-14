import json

import pytest
from conftest import FauxLLM

from portail.agents import Agent
from portail.boucle import ErreurOutils, boucle_outils
from portail.contexte import elaguer_resultats_outils
from portail.outils import OutilsDepot


def _appel(nom="lire", arguments='{"chemin": "README.md"}', id="c1"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": id, "type": "function", "function": {"name": nom, "arguments": arguments}}],
    }  # fmt: skip


def _texte(t):
    return {"role": "assistant", "content": t}


@pytest.fixture
def outils(tmp_path):
    (tmp_path / "README.md").write_text("# Salut\n")
    return OutilsDepot(tmp_path)


def _agent(**kw):
    return Agent(
        nom="plan", description="p", modele="mod", prompt_systeme="s", contexte_max=32768,
        outils=["lister", "lire", "chercher"], **kw,
    )  # fmt: skip


async def _go(llm, outils, agent=None, messages=None):
    vus = []

    async def sur_appel(libelle, resultat):
        vus.append((libelle, resultat))

    messages = messages if messages is not None else [{"role": "user", "content": "go"}]
    res = await boucle_outils(llm, agent or _agent(), messages, outils, sur_appel)
    return res, vus, messages


async def test_boucle_execute_les_outils_puis_repond(outils):
    llm = FauxLLM()
    llm.reponses = [_appel(), _texte("<think>x</think>Fini")]
    res, vus, messages = await _go(llm, outils)
    assert res.texte == "Fini" and res.limite_atteinte is False
    assert vus == [("lire(README.md)", "# Salut")]
    assert messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": "# Salut"}
    assert [n["function"]["name"] for n in llm.appels[0]["outils"]] == [
        "lister",
        "lire",
        "chercher",
    ]


async def test_boucle_limite_tours(outils):
    llm = FauxLLM()
    llm.reponses = [_appel(id="a"), _appel(id="b"), _texte("Bilan")]
    res, _, messages = await _go(llm, outils, _agent(tours_max=2))
    assert res.limite_atteinte is True and res.texte == "Bilan"
    assert llm.appels[-1]["outils"] is None
    consigne = (
        "Limite d'outils atteinte : conclus maintenant avec ce que tu as, sans appeler d'outil."
    )
    assert messages[-1] == {"role": "user", "content": consigne}


async def test_trois_appels_mal_formes_echouent(outils):
    llm = FauxLLM()
    llm.reponses = [_appel(arguments="{{", id=str(i)) for i in range(3)]
    with pytest.raises(ErreurOutils, match="le modèle mod ne gère pas correctement les outils"):
        await _go(llm, outils)


async def test_mal_forme_puis_bien_forme_remet_a_zero(outils):
    llm = FauxLLM()
    mauvais = lambda i: _appel(arguments="{{", id=f"m{i}")
    llm.reponses = [mauvais(1), mauvais(2), _appel(), mauvais(3), mauvais(4), _texte("ok")]
    res, _, _ = await _go(llm, outils)
    assert res.texte == "ok"


async def test_contenu_none_sans_outil(outils):
    llm = FauxLLM()
    llm.reponses = [{"role": "assistant", "content": None}]
    res, _, _ = await _go(llm, outils)
    assert res.texte == ""


def test_elagage():
    gros = "x" * 1200
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {"role": "tool", "tool_call_id": "1", "content": gros},
        {"role": "tool", "tool_call_id": "2", "content": gros},
        {"role": "tool", "tool_call_id": "3", "content": gros},
    ]
    n = elaguer_resultats_outils(messages, 1000)
    assert n >= 1
    assert messages[2]["content"] == "[résultat retiré : relire si besoin]"
    assert messages[0]["content"] == "s" and messages[1]["content"] == "u"
    assert messages[3]["content"] == messages[4]["content"] == gros  # arrêt dès sous 0,75
    assert n == 1
    assert json.dumps(messages)  # reste sérialisable


def test_elagage_sous_le_seuil():
    messages = [{"role": "tool", "tool_call_id": "1", "content": "x" * 100}]
    assert elaguer_resultats_outils(messages, 1000) == 0
    assert messages[0]["content"] == "x" * 100


def _appel_brut(tool_call):
    return {"role": "assistant", "content": None, "tool_calls": [tool_call]}


async def test_tool_calls_mal_structures_ne_levent_pas(outils):
    llm = FauxLLM()
    llm.reponses = [
        _appel_brut({"id": "a"}),  # pas de function
        _appel_brut({"function": {"name": "lire", "arguments": '{"chemin": "README.md"}'}}),
        _appel_brut({"id": "c", "function": {"name": "lire", "arguments": 42}}),
        _appel_brut(
            {"id": "d", "function": {"name": "lire", "arguments": {"chemin": "README.md"}}}
        ),
        _texte("fin"),
    ]
    res, vus, messages = await _go(llm, outils)
    assert res.texte == "fin"
    tools = [m for m in messages if m["role"] == "tool"]
    assert tools[0]["tool_call_id"] == "a" and tools[0]["content"].startswith("erreur")
    assert tools[1]["tool_call_id"] and tools[1]["content"] == "# Salut"  # id généré
    assert tools[2]["content"].startswith("erreur")  # arguments = 42
    assert tools[3]["content"] == "# Salut"  # dict sérialisé
    assert vus[0][0] == "outil inconnu"


async def test_tool_calls_mal_structures_comptent_pour_trois(outils):
    llm = FauxLLM()
    llm.reponses = [_appel_brut({}) for _ in range(3)]
    with pytest.raises(ErreurOutils):
        await _go(llm, outils)


async def test_limite_avec_tool_calls_dans_le_dernier_appel(outils):
    llm = FauxLLM()
    derniere = {**_appel(id="z"), "content": "Bilan"}
    llm.reponses = [_appel(id="a"), derniere]
    res, _, _ = await _go(llm, outils, _agent(tours_max=1))
    assert res.limite_atteinte is True and res.texte == "Bilan"


async def test_outil_hors_liste_non_execute(outils, monkeypatch):
    appelles = []
    monkeypatch.setattr(outils, "chercher", lambda *a, **k: appelles.append(1))
    llm = FauxLLM()
    llm.reponses = [_appel(nom="chercher", arguments='{"motif": "x"}'), _texte("ok")]
    _, _, messages = await _go(llm, outils, _agent_lire())
    assert not appelles
    assert messages[-1]["content"] == "erreur : outil non autorisé : chercher"


def _agent_lire():
    return Agent(
        nom="p", description="p", modele="mod", prompt_systeme="s", contexte_max=32768,
        outils=["lire"],
    )  # fmt: skip


async def test_trois_outils_non_autorises_echouent(outils):
    llm = FauxLLM()
    llm.reponses = [_appel(nom="chercher", id=str(i)) for i in range(3)]
    with pytest.raises(ErreurOutils):
        await _go(llm, outils, _agent_lire())


async def test_agent_sans_outils_refuse(outils):
    agent = Agent(nom="p", description="p", modele="m", prompt_systeme="s", contexte_max=100)
    with pytest.raises(ErreurOutils):
        await _go(FauxLLM(), outils, agent)


async def test_trop_d_appels_par_tour(outils):
    llm = FauxLLM()
    multi = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": f"c{i}", "function": {"name": "lire", "arguments": '{"chemin": "README.md"}'}}
            for i in range(10)
        ],
    }
    llm.reponses = [multi, _texte("ok")]
    _, vus, messages = await _go(llm, outils)
    tools = [m for m in messages if m["role"] == "tool"]
    assert [t["tool_call_id"] for t in tools] == [f"c{i}" for i in range(10)]
    assert len(vus) == 8
    assert tools[9]["content"] == "erreur : trop d'appels dans un même tour, ignoré"
