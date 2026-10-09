from rag.ask import format_answer

PASSAGES = [
    {"doc_id": "geo.md", "start": 0, "end": 86, "score": 0.8213},
    {"doc_id": "rag.md", "start": 10, "end": 50, "score": 0.5},
]


def out(**kw):
    base = {"answer": "Paris [1].", "passages": PASSAGES, "cited": [1], "invalid_citations": 0}
    return {**base, **kw}


def test_cited_passages_only_with_french_decimal():
    text = format_answer("Capitale ?", out())
    assert text.startswith("Q : Capitale ?\n\nParis [1].")
    assert "[1] geo.md · caractères 0–86" in text and "(score 0,82)" in text
    assert "rag.md" not in text and "⚠" not in text


def test_no_valid_citation_means_no_sources_section():
    text = format_answer("Q ?", out(answer="Je n'ai pas trouvé…", cited=[]))
    assert "Sources" not in text


def test_invalid_citation_warning():
    text = format_answer("Q ?", out(answer="x [9]", cited=[], invalid_citations=1))
    assert "⚠ Citation invalide" in text and "1" in text


def test_numbers_follow_answer_numbering():
    text = format_answer("Q ?", out(answer="a [2] b [1]", cited=[2, 1]))
    assert text.index("[2] rag.md") < text.index("[1] geo.md")
