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
    assert json.dumps(messages)  # reste sérialisable
