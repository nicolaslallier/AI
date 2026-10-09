import pytest

from common.jsonl import read_jsonl
from common.llm import Generator
from finetune.prepare import prepare
from finetune.train import train
from ft_fakes import make_ft_cfg

TINY = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"


@pytest.mark.slow
def test_train_reload_generate_on_a_tiny_model(tmp_path):
    cfg = make_ft_cfg(tmp_path, model=TINY, train={"iters": 20, "steps_per_report": 5, "steps_per_eval": 10, "max_seq_length": 256})
    prepare(cfg)
    run_dir, m = train(cfg, root=tmp_path / "runs")
    assert m["best_val_loss"] < m["first_val_loss"]
    assert any("val_loss" in r for r in read_jsonl(run_dir / "train_log.jsonl"))
    gen = Generator(TINY, adapter_path=run_dir / "adapters")
    assert isinstance(gen.generate([{"role": "user", "content": "Capitale de la France ?"}], max_tokens=10), str)
