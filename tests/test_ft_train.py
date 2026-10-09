import json

import pytest

import finetune.train as ft_train
from common.jsonl import read_jsonl
from finetune.config import ft_settings
from finetune.prepare import prepare
from ft_fakes import make_ft_cfg


def fake_mlx(calls):
    def run(args):
        calls.append(args)
        cb = ft_train.JsonlCallback(None, args["adapter_path"], args)
        cb.on_val_loss_report({"iteration": 0, "val_loss": 4.0, "val_time": 0.1})
        cb.on_train_loss_report(
            {"iteration": 5, "train_loss": 2.0, "iterations_per_second": 3.0, "peak_memory": 1.2, "learning_rate": 1e-4}
        )
        cb.on_val_loss_report({"iteration": 9, "val_loss": 1.0, "val_time": 0.1})

    return run


def test_mlx_args_map_the_config(tmp_path):
    s = ft_settings(make_ft_cfg(tmp_path, lora={"rank": 4}, train={"iters": 7, "learning_rate": 5e-5}))
    a = ft_train.mlx_args(s, 3, tmp_path / "ad")
    assert a["model"] == "fake-model" and a["seed"] == 3 and a["train"] is True
    assert a["lora_parameters"] == {"rank": 4, "scale": 20.0, "dropout": 0.0}
    assert a["iters"] == 7 and a["learning_rate"] == 5e-5 and a["adapter_path"] == str(tmp_path / "ad")
    assert a["data"] == s["data_dir"] and a["report_to"] == ft_train.CALLBACK_NAME


def test_train_writes_run_dir_with_log_metrics_and_curves(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ft_train, "run_mlx_lora", fake_mlx(calls))
    cfg = make_ft_cfg(tmp_path)
    prepare(cfg)
    run_dir, m = ft_train.train(cfg, root=tmp_path / "runs")
    assert calls[0]["adapter_path"] == str(run_dir / "adapters")
    assert read_jsonl(run_dir / "train_log.jsonl")[1] == {
        "step": 5, "train_loss": 2.0, "it_per_sec": 3.0, "peak_mem_gb": 1.2,
    }
    saved = json.loads((run_dir / "metrics.json").read_text())
    assert saved == m and m["best_val_loss"] == 1.0 and m["first_val_loss"] == 4.0
    assert len(m["data_sha256"]) == 64 and (run_dir / "curves.png").exists()
    assert (run_dir / "config.yaml").exists()


def test_second_training_never_overwrites_the_first(tmp_path, monkeypatch):
    monkeypatch.setattr(ft_train, "run_mlx_lora", fake_mlx([]))
    cfg = make_ft_cfg(tmp_path)
    prepare(cfg)
    first, _ = ft_train.train(cfg, root=tmp_path / "runs")
    second, _ = ft_train.train(cfg, root=tmp_path / "runs")
    assert first != second and (first / "metrics.json").exists()
    assert len(read_jsonl(first / "train_log.jsonl")) == 3


def test_train_before_prepare_names_the_command(tmp_path, monkeypatch):
    monkeypatch.setattr(ft_train, "run_mlx_lora", fake_mlx([]))
    with pytest.raises(ValueError, match="finetune.prepare"):
        ft_train.train(make_ft_cfg(tmp_path), root=tmp_path / "runs")
    assert not (tmp_path / "runs").exists()
