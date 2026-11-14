import pytest

from portail.agents import Agent
from portail.contexte import _niveau, construire, estimer_jetons, jauge
from portail.db import Document, Message


def _agent(contexte_max=100):
    return Agent(
        nom="a", description="d", modele="m", prompt_systeme="SYS", contexte_max=contexte_max
    )


def _msgs(n):
    return [
        Message(id=i, role="user" if i % 2 else "assistant", contenu=f"m{i}")
        for i in range(1, n + 1)
    ]


def test_sans_brouillon_tout_l_historique():
    r = construire(_agent(), _msgs(3), None)
    assert r[0] == {"role": "system", "content": "SYS"}
    assert [m["content"] for m in r[1:]] == ["m1", "m2", "m3"]


def test_avec_brouillon_seulement_les_messages_apres():
    doc = Document(contenu="TXT", dernier_message_id=2)
    r = construire(_agent(), _msgs(4), doc)
    assert [m["content"] for m in r[2:]] == ["m3", "m4"]
    assert r[1]["role"] == "system"
    assert r[1]["content"] == "Brouillon courant :\n\nTXT"
    assert len(r) == 4


def test_brouillon_sans_dernier_message_garde_tout():
    r = construire(_agent(), _msgs(2), Document(contenu="T", dernier_message_id=None))
    assert len(r) == 4


def test_roles_autres_exclus():
    ms = _msgs(2) + [Message(id=3, role="system", contenu="x")]
    assert len(construire(_agent(), ms, None)) == 3


def test_consigne_ajoutee_en_dernier():
    r = construire(_agent(), _msgs(2), None, "go")
    assert r[-1] == {"role": "user", "content": "go"}


def test_estimer_jetons():
    assert estimer_jetons([{"role": "user", "content": "x" * 40}]) == 14


@pytest.mark.parametrize(
    "ratio,niveau", [(0.74, "ok"), (0.75, "alerte"), (0.89, "alerte"), (0.90, "plein")]
)
def test_niveaux_jauge(ratio, niveau):
    assert _niveau(ratio) == niveau


def test_jauge():
    j = jauge(_agent(100), [{"role": "user", "content": "x" * 280}])  # 74 jetons
    assert (j.utilises, j.max, j.ratio, j.niveau) == (74, 100, 0.74, "ok")


def test_annexes_et_messages_tool_ignores():
    ms = [
        Message(id=1, role="user", contenu="U"),
        Message(id=2, role="tool", contenu="T"),
        Message(id=3, role="assistant", contenu="A"),
    ]
    r = construire(_agent(), ms, None, annexes=["A1", "A2"])
    assert [(m["role"], m["content"]) for m in r] == [
        ("system", "SYS"),
        ("system", "A1"),
        ("system", "A2"),
        ("user", "U"),
        ("assistant", "A"),
    ]
