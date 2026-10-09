import pytest

from common.jsonl import write_jsonl
from evalkit.compare import main
from fakes import make_cfg
from finetune.prepare import prepare
from finetune.train import train
from ft_fakes import make_ft_cfg, write_cfg
from test_ft_smoke import TINY


@pytest.mark.slow
def test_compare_base_vs_ft_on_a_tiny_model(tmp_path):
    ft_cfg = make_ft_cfg(tmp_path, model=TINY, train={"iters": 10, "steps_per_report": 5, "steps_per_eval": 5, "max_seq_length": 256})
    prepare(ft_cfg)
    run_dir, _ = train(ft_cfg, root=tmp_path / "ftruns")
    eval_path = tmp_path / "eval.jsonl"
    write_jsonl(eval_path, [{"id": "a", "question": "Capitale de la France ?", "answer": "Paris", "sources": []}])
    cfg = make_cfg(tmp_path, generation={"model": TINY, "max_tokens": 16})
    cfg.update(eval_set=str(eval_path), runs_dir=str(tmp_path / "runs"),
               compare={"systems": ["base", "ft"], "adapter": str(run_dir / "adapters")})
    main([str(write_cfg(tmp_path, cfg))])
    report = (next((tmp_path / "runs").iterdir()) / "report.md").read_text(encoding="utf-8")
    assert "| base |" in report and "| ft |" in report
