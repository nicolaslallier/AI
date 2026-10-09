import pytest

from rag.generate import NOT_FOUND, build_messages, parse_citations


def test_messages_number_passages_from_one():
    chunks = [{"doc_id": "a.md", "text": "alpha"}, {"doc_id": "b.md", "text": "beta"}]
    system, user = build_messages("Quoi ?", chunks)
    assert system["role"] == "system" and NOT_FOUND in system["content"]
    assert "[1] (a.md)\nalpha" in user["content"] and "[2] (b.md)\nbeta" in user["content"]
    assert user["content"].rstrip().endswith("Question : Quoi ?")


@pytest.mark.parametrize(
    "text, n, expected",
    [
        ("Paris [1].", 3, ([1], 1, 0)),
        ("A [2] puis B [1] puis C [2].", 3, ([2, 1], 3, 0)),
        ("Voir [1][3].", 3, ([1, 3], 2, 0)),
        ("Voir [1, 2].", 3, ([1, 2], 2, 0)),
        ("Faux [7] et vrai [1].", 3, ([1], 2, 1)),
        ("Zéro [0].", 3, ([], 1, 1)),
        (NOT_FOUND, 3, ([], 0, 0)),
        ("Pas de citation.", 0, ([], 0, 0)),
        ("Tableau t[1] ou [a] ou [].", 3, ([1], 1, 0)),
    ],
)
def test_parse_citations(text, n, expected):
    assert parse_citations(text, n) == expected
