import pytest

from evalkit.report import fmt_rate, render_report


def rows(correct):
    return [
        {"id": f"q{i}", "question": f"Q{i} ?", "expected": "x", "answer": f"rép{i}", "correct": c}
        for i, c in enumerate(correct)
    ]


def make(base, rag):
    results = {"base": rows(base), "base+rag": rows(rag)}
    metrics = {
        "base": {"n": len(base), "accuracy": sum(base) / len(base)},
        "base+rag": {"n": len(rag), "accuracy": sum(rag) / len(rag), "recall_at_k": 0.5, "citation_validity": None},
    }
    return metrics, results


def render(metrics, results, **kw):
    return render_report("t", "uv run python -m evalkit.compare c.yaml", metrics, results,
                         {"base": 1.234, "base+rag": None}, min_gap=kw.pop("min_gap", 2), **kw)


def test_fmt_rate():
    assert fmt_rate(31, 50) == "0,62 (31/50)"
    assert fmt_rate(0, 0) == "—"


def test_table_shows_counts_and_dashes_for_missing_metrics():
    metrics, results = make([True] * 3 + [False] * 7, [True] * 8 + [False] * 2)
    out = render(metrics, results)
    base_line = next(l for l in out.splitlines() if l.startswith("| base |"))
    assert "0,30 (3/10)" in base_line and base_line.count("—") >= 2 and "1,2 s" in base_line
    rag_line = next(l for l in out.splitlines() if l.startswith("| base+rag |"))
    assert "0,80 (8/10)" in rag_line and "0,50" in rag_line and "—" in rag_line  # latence et fidélité None


def test_verdict_flags_small_gaps_as_inconclusive():
    metrics, results = make([True] * 5 + [False] * 5, [True] * 6 + [False] * 4)  # +1 question, min_gap=2
    out = render(metrics, results)
    assert "non concluant" in out.split("## Tableau")[0]
    metrics, results = make([True] * 3 + [False] * 7, [True] * 8 + [False] * 2)  # +5 questions
    verdict = render(metrics, results).split("## Tableau")[0]
    assert "non concluant" not in verdict and "+50 points" in verdict


def test_judge_and_prompt_caveats_are_always_stated():
    out = render(*make([True, False], [True, True]))
    assert "règles" in out.split("## Limites")[1]


def test_cas_parlants_picks_questions_where_systems_disagree_and_skips_when_none():
    metrics, results = make([True, False, True, False], [True, True, True, True])
    out = render(metrics, results)
    parlants = out.split("## Cas parlants")[1].split("## Limites")[0]
    assert "Q1 ?" in parlants and "Q3 ?" in parlants and "Q0 ?" not in parlants
    metrics, results = make([True, True], [True, True])
    assert "Aucune divergence" in render(metrics, results).split("## Cas parlants")[1]


def test_warnings_come_first_and_single_system_has_no_comparative_verdict():
    metrics, results = make([True, False], [True, True])
    out = render(metrics, results, warnings=["Fuite : q1"])
    assert out.index("Fuite : q1") < out.index("## Verdict")
    one = render({"base": metrics["base"]}, {"base": results["base"]})
    assert "un seul système" in one.split("## Tableau")[0].lower()


def test_reproduction_command_is_verbatim():
    assert "uv run python -m evalkit.compare c.yaml" in render(*make([True], [True]))


def test_rendered_lines_fit_80_columns_outside_table_and_command():
    names = ["base", "base+rag", "ft", "ft+rag"]
    results = {
        n: [{"id": "q1", "question": "Q " + "très " * 60 + "?", "expected": "x" * 50,
             "answer": "réponse\nlongue " + "é" * 2000, "correct": c}]
        for n, c in zip(names, [True, False, True, False])
    }
    metrics = {n: {"n": 1, "accuracy": float(c)} for n, c in zip(names, [True, False, True, False])}
    out = render_report("t", "uv run python -m evalkit.compare c.yaml", metrics, results,
                        {n: None for n in names}, min_gap=2,
                        notes=["note " + "très " * 40])
    in_bash = False
    for line in out.splitlines():
        if line.startswith("```"):
            in_bash = not in_bash
            continue
        if in_bash or line.startswith("|"):
            continue
        assert len(line) <= 80, line


def test_rejects_empty_results():
    with pytest.raises(ValueError, match="empty"):
        render_report("t", "c", {}, {}, {}, min_gap=2)


def test_rejects_metrics_and_results_with_different_systems():
    metrics, results = make([True], [True])
    with pytest.raises(ValueError, match="same systems"):
        render_report("t", "c", metrics, {"base": results["base"]}, {}, min_gap=2)


def test_rejects_systems_with_different_row_counts():
    metrics, results = make([True, False], [True, True])
    results["base+rag"] = rows([True, True, True])
    with pytest.raises(ValueError, match="same number of rows"):
        render_report("t", "c", metrics, results, {}, min_gap=2)


def test_rejects_systems_with_different_n():
    metrics, results = make([True, False], [True, True])
    metrics["base+rag"]["n"] = 5
    with pytest.raises(ValueError, match="same n"):
        render_report("t", "c", metrics, results, {}, min_gap=2)
