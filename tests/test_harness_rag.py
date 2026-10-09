import pytest

from evalkit.harness import evaluate

QA = [
    {"id": "a", "question": "qa", "answer": "x", "sources": ["d1.md"]},
    {"id": "b", "question": "qb", "answer": "y", "sources": ["d2.md"]},
    {"id": "c", "question": "qc", "answer": "z", "sources": []},
]


def system_from(table):
    return lambda q: table[q]


def test_recall_and_citation_validity():
    sys_ = system_from(
        {
            "qa": {"answer": "x", "sources": ["d1.md"], "retrieved": ["d9.md", "d1.md"], "citations": 2, "invalid_citations": 1},
            "qb": {"answer": "y", "sources": [], "retrieved": ["d9.md"], "citations": 0, "invalid_citations": 0},
            "qc": {"answer": "z", "sources": [], "retrieved": ["d1.md"], "citations": 1, "invalid_citations": 0},
        }
    )
    m, rows = evaluate(sys_, QA)
    assert m["recall_at_k"] == 0.5  # qa hit, qb miss, qc excluded (no expected sources)
    assert m["citation_validity"] == pytest.approx(1 - 1 / 3)
    assert [r["retrieval_hit"] for r in rows] == [True, False, None]


def test_no_citations_gives_none_not_zero_division():
    sys_ = system_from({q["question"]: {"answer": "a", "sources": [], "retrieved": ["d1.md"], "citations": 0, "invalid_citations": 0} for q in QA})
    m, _ = evaluate(sys_, QA)
    assert m["citation_validity"] is None


def test_m0_style_systems_are_unchanged():
    sys_ = system_from({q["question"]: {"answer": q["answer"], "sources": q["sources"]} for q in QA})
    m, rows = evaluate(sys_, QA)
    assert "recall_at_k" not in m and "citation_validity" not in m
    assert all("retrieval_hit" not in r for r in rows)


@pytest.mark.parametrize(
    "extra", [{"retrieved": "d1.md"}, {"retrieved": [1]}, {"citations": -1}, {"citations": True}, {"invalid_citations": "2"}]
)
def test_bad_optional_fields_name_the_question(extra):
    sys_ = system_from({q["question"]: {"answer": "a", "sources": [], **extra} for q in QA})
    with pytest.raises(ValueError, match="'a'"):
        evaluate(sys_, QA)
