from rag.recall import recall_table

QA = [
    {"id": "1", "question": "q1", "answer": "x", "sources": ["a.md"]},
    {"id": "2", "question": "q2", "answer": "x", "sources": ["b.md"]},
    {"id": "3", "question": "q3", "answer": "x", "sources": []},  # sans source attendue : ignorée
]


def fake(mapping):
    return lambda q: [{"doc_id": d} for d in mapping[q]]


def test_recall_table_counts_only_questions_with_sources():
    r = recall_table(QA, {"good": fake({"q1": ["a.md"], "q2": ["b.md"], "q3": []}),
                          "half": fake({"q1": ["a.md"], "q2": ["z.md"], "q3": []})})
    assert r == {"good": 1.0, "half": 0.5}


def test_recall_table_none_when_no_expected_sources():
    assert recall_table(QA[2:], {"x": fake({"q3": []})}) == {"x": None}
