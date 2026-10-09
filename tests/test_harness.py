import pytest

from evalkit.harness import evaluate
from evalkit.metrics import answer_correct, normalize, source_hit

QA = [
    {"id": "1", "question": "Capitale ?", "answer": "Paris", "sources": ["geo.md"]},
    {"id": "2", "question": "2+2 ?", "answer": "4", "sources": []},
]


def system(answers, sources=()):
    return lambda q: {"answer": answers[q], "sources": list(sources)}


def test_normalize_ignores_case_accents_whitespace():
    assert normalize("  Été \n") == "ete"


def test_answer_correct_is_contains_match():
    assert answer_correct("C'est PARIS.", "Paris")
    assert answer_correct("c'est ETE", "Été")
    assert not answer_correct("Lyon", "Paris")


def test_source_hit():
    assert source_hit(["a", "b"], ["b"])
    assert not source_hit([], ["b"])


def test_perfect_system():
    metrics, results = evaluate(system({"Capitale ?": "Paris", "2+2 ?": "4"}, ["geo.md"]), QA)
    assert metrics == {"n": 2, "accuracy": 1.0, "source_hit_rate": 1.0}
    assert results[0]["correct"] is True and results[0]["source_hit"] is True
    assert results[1]["source_hit"] is None  # no expected source -> excluded from recall


def test_partial_system():
    metrics, _ = evaluate(system({"Capitale ?": "Lyon", "2+2 ?": "4"}, ["autre.md"]), QA)
    assert metrics == {"n": 2, "accuracy": 0.5, "source_hit_rate": 0.0}


def test_empty_eval_set_does_not_divide_by_zero():
    assert evaluate(system({}), []) == ({"n": 0, "accuracy": 0.0, "source_hit_rate": None}, [])


def test_no_question_with_sources_gives_none_recall():
    qa = [QA[1]]
    metrics, _ = evaluate(system({"2+2 ?": "4"}), qa)
    assert metrics["source_hit_rate"] is None


@pytest.mark.parametrize("bad", [{"answer": "x"}, "texte", None])
def test_malformed_system_output_names_the_question(bad):
    with pytest.raises(ValueError, match="'1'"):
        evaluate(lambda q: bad, QA)


def test_word_boundary_match():
    assert not answer_correct("il y en a 14", "4")
    assert not answer_correct("Ouistiti", "Oui")


@pytest.mark.parametrize("bad", ["geo.md", [{"a": 1}]])
def test_bad_sources_type_names_the_question(bad):
    with pytest.raises(ValueError, match="'1'"):
        evaluate(lambda q: {"answer": "x", "sources": bad}, QA)
