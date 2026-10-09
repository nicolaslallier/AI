import json
import re

import pytest

import evalkit.compare as cmp
from common.jsonl import read_jsonl, read_qa, write_jsonl
from evalkit.compare import leaked_ids, main, run_compare
from fakes import make_cfg
from ft_fakes import write_cfg

QA = [
    {"id": "a", "question": "Capitale de la France ?", "answer": "Paris", "sources": ["geo.md"]},
    {"id": "b", "question": "Rang LoRA ?", "answer": "8", "sources": []},
]


def test_leak_detection_is_normalized_and_optional(tmp_path):
    train = tmp_path / "train.jsonl"
    write_jsonl(train, [{"messages": [{"role": "user", "content": "  capitale de la FRANCE ? "},
                                       {"role": "assistant", "content": "Paris"}]}])
    assert leaked_ids(str(train), QA) == ["a"]
    assert leaked_ids("", QA) == []


def test_example_eval_set_does_not_leak_into_example_ft_source():
    qs = {r["question"] for r in read_qa("data/examples/compare_eval.jsonl")}
    assert not qs & {r["question"] for r in read_qa("data/examples/ft_source.jsonl")}


def test_run_compare_measures_latency_and_keeps_order():
    systems = {
        "x": lambda q: {"answer": "Paris" if "France" in q else "?", "sources": []},
        "y": lambda q: {"answer": "Paris 8", "sources": []},
    }
    metrics, results, latency = run_compare(systems, QA)
    assert list(metrics) == ["x", "y"] and metrics["x"]["accuracy"] == 0.5 and metrics["y"]["accuracy"] == 1.0
    assert all(latency[n] >= 0 for n in systems) and len(results["x"]) == 2


def test_main_writes_an_immutable_run_with_report_and_manifest(tmp_path, monkeypatch, capsys):
    cfg = make_cfg(tmp_path)
    eval_path = tmp_path / "eval.jsonl"
    write_jsonl(eval_path, QA)
    adapter = tmp_path / "ftrun" / "adapters"
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text(json.dumps({"model": "fake"}), encoding="utf-8")
    (tmp_path / "ftrun" / "metrics.json").write_text(json.dumps({"data_sha256": "abc"}), encoding="utf-8")
    cfg.update(eval_set=str(eval_path), runs_dir=str(tmp_path / "runs"),
               compare={"systems": ["base", "ft"], "adapter": str(adapter)})
    monkeypatch.setattr(cmp, "build_systems", lambda c: {
        "base": lambda q: {"answer": "Paris", "sources": []},
        "ft": lambda q: {"answer": "Paris 8", "sources": []}})
    path = write_cfg(tmp_path, cfg)
    main([str(path)])
    main([str(path)])  # deuxième run le même jour: nouveau dossier, jamais d'écrasement
    runs = sorted((tmp_path / "runs").iterdir())
    assert len(runs) == 2 and runs[1].name.endswith("-2")
    run = runs[0]
    assert {p.name for p in run.iterdir()} == {"config.yaml", "metrics.json", "outputs.jsonl", "report.md"}
    m = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    assert m["systems"]["ft"]["accuracy"] == 1.0 and m["systems"]["base"]["accuracy"] == 0.5
    assert m["manifest"]["ft_data_sha256"] == "abc" and m["manifest"]["base_model"] == "fake"
    assert len(m["manifest"]["eval_set_sha256"]) == 64 and len(m["manifest"]["adapter_config_sha256"]) == 64
    assert len(read_jsonl(run / "outputs.jsonl")) == 4
    assert "## Verdict" in (run / "report.md").read_text(encoding="utf-8")
    assert "run saved to" in capsys.readouterr().out


def test_main_reports_leaks_and_rejects_empty_eval(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    eval_path, train = tmp_path / "eval.jsonl", tmp_path / "train.jsonl"
    write_jsonl(eval_path, QA)
    write_jsonl(train, [{"messages": [{"role": "user", "content": "Rang LoRA ?"}]}])
    cfg.update(eval_set=str(eval_path), runs_dir=str(tmp_path / "runs"),
               compare={"systems": ["base"], "train_file": str(train)})
    monkeypatch.setattr(cmp, "build_systems", lambda c: {"base": lambda q: {"answer": "Paris", "sources": []}})
    main([str(write_cfg(tmp_path, cfg))])
    report = (next((tmp_path / "runs").iterdir()) / "report.md").read_text(encoding="utf-8")
    warning = report.split("## Verdict")[0]
    assert "entraînement" in warning
    flat = " ".join(warning.replace(">", " ").split())  # le texte est replié à 80 colonnes
    leak_list = re.search(r"\(([^)]*)\) ;", flat).group(1)  # ids entre parenthèses
    assert "b" in re.split(r"\W+", leak_list) and "a" not in re.split(r"\W+", leak_list)

    write_jsonl(eval_path, [])
    with pytest.raises(ValueError, match="empty"):
        main([str(write_cfg(tmp_path, cfg))])


def _cfg_for(tmp_path, monkeypatch, **compare):
    cfg = make_cfg(tmp_path)
    eval_path = tmp_path / "eval.jsonl"
    write_jsonl(eval_path, QA)
    cfg.update(eval_set=str(eval_path), runs_dir=str(tmp_path / "runs"), compare=compare)

    def boom(c):
        raise AssertionError("build_systems must not be called")

    monkeypatch.setattr(cmp, "build_systems", boom)
    return write_cfg(tmp_path, cfg)


def test_missing_train_file_fails_before_any_model_load(tmp_path, monkeypatch):
    path = _cfg_for(tmp_path, monkeypatch, systems=["base"], train_file=str(tmp_path / "nope.jsonl"))
    with pytest.raises(ValueError, match="nope.jsonl"):
        main([str(path)])


@pytest.mark.parametrize("row", [
    [1], {"messages": "x"}, {"messages": [3]}, {"messages": [{"role": "user", "content": 5}]}])
def test_malformed_train_row_names_file_and_row(tmp_path, monkeypatch, row):
    train = tmp_path / "train.jsonl"
    write_jsonl(train, [{"messages": []}, row])
    path = _cfg_for(tmp_path, monkeypatch, systems=["base"], train_file=str(train))
    with pytest.raises(ValueError, match=r"train\.jsonl.*2"):
        main([str(path)])


def test_rows_without_messages_are_tolerated(tmp_path):
    train = tmp_path / "train.jsonl"
    write_jsonl(train, [{"text": "x"}])
    assert leaked_ids(str(train), QA) == []


def test_missing_adapter_gives_actionable_error(tmp_path, monkeypatch):
    path = _cfg_for(tmp_path, monkeypatch, systems=["ft"], adapter=str(tmp_path / "gone"))
    with pytest.raises(ValueError, match=r"compare\.adapter.*gone.*finetune\.train"):
        main([str(path)])


def test_corrupt_training_metrics_names_the_file(tmp_path, monkeypatch):
    adapter = tmp_path / "ftrun" / "adapters"
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "ftrun" / "metrics.json").write_text("{not json", encoding="utf-8")
    path = _cfg_for(tmp_path, monkeypatch, systems=["ft"], adapter=str(adapter))
    with pytest.raises(ValueError, match="metrics.json"):
        main([str(path)])


def test_render_failure_leaves_no_run_dir(tmp_path, monkeypatch):
    path = _cfg_for(tmp_path, monkeypatch, systems=["base"])
    monkeypatch.setattr(cmp, "build_systems", lambda c: {"base": lambda q: {"answer": "Paris", "sources": []}})

    def bad(*a, **k):
        raise ValueError("render failed")

    monkeypatch.setattr(cmp, "render_report", bad)
    with pytest.raises(ValueError, match="render failed"):
        main([str(path)])
    assert not (tmp_path / "runs").exists() or not list((tmp_path / "runs").iterdir())
