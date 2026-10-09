import hashlib
import json
from datetime import date

from common.jsonl import read_jsonl
from evalkit.runlog import save_run

CFG = {"name": "demo", "seed": 1}
METRICS = {"n": 1, "accuracy": 1.0, "source_hit_rate": None}
RESULTS = [{"id": "1", "answer": "x"}]


def data_file(tmp_path):
    p = tmp_path / "eval.jsonl"
    p.write_text('{"id":"1"}\n', encoding="utf-8")
    return p


def test_save_run_writes_config_metrics_outputs(tmp_path):
    d = data_file(tmp_path)
    run = save_run(CFG, hashlib.sha256(d.read_bytes()).hexdigest(), METRICS, RESULTS, root=tmp_path / "runs")
    assert run.name == f"{date.today().isoformat()}-demo"
    assert "name: demo" in (run / "config.yaml").read_text(encoding="utf-8")
    saved = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    assert saved["accuracy"] == 1.0
    assert saved["data_sha256"] == hashlib.sha256(d.read_bytes()).hexdigest()
    assert read_jsonl(run / "outputs.jsonl") == RESULTS


def test_same_name_twice_does_not_overwrite(tmp_path):
    d = data_file(tmp_path)
    a = save_run(CFG, hashlib.sha256(d.read_bytes()).hexdigest(), METRICS, RESULTS, root=tmp_path / "runs")
    b = save_run(CFG, hashlib.sha256(d.read_bytes()).hexdigest(), METRICS, RESULTS, root=tmp_path / "runs")
    assert a != b and a.exists() and b.exists()
    assert b.name == a.name + "-2"
