import json

import pytest

from common.jsonl import write_jsonl
from evalkit.run import main

QA = [
    {"id": "1", "question": "Capitale ?", "answer": "Paris", "sources": ["geo.md"]},
    {"id": "2", "question": "2+2 ?", "answer": "4", "sources": []},
]


def setup(tmp_path, system="evalkit.trivial:build"):
    write_jsonl(tmp_path / "eval.jsonl", QA)
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        f"name: e2e\nseed: 7\neval_set: {tmp_path / 'eval.jsonl'}\n"
        f"system: {system}\nruns_dir: {tmp_path / 'runs'}\n",
        encoding="utf-8",
    )
    return cfg


def test_end_to_end_with_trivial_system(tmp_path):
    metrics = main([str(setup(tmp_path))])
    assert metrics == {"n": 2, "accuracy": 1.0, "source_hit_rate": 1.0}
    (run,) = (tmp_path / "runs").iterdir()
    saved = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    assert saved["accuracy"] == 1.0 and "data_sha256" in saved


def test_same_config_gives_same_metrics(tmp_path):
    cfg = setup(tmp_path)
    assert main([str(cfg)]) == main([str(cfg)])


def test_unknown_system_is_a_clear_error(tmp_path):
    with pytest.raises(ValueError, match="nope"):
        main([str(setup(tmp_path, system="evalkit.trivial:nope"))])
