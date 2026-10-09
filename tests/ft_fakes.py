import yaml


def make_ft_cfg(tmp_path, **ft_overrides):
    ft = {
        "source": "data/examples/ft_source.jsonl",
        "data_dir": str(tmp_path / "data"),
        "model": "fake-model",
        "train": {"iters": 20, "steps_per_report": 5, "steps_per_eval": 10},
    }
    ft.update(ft_overrides)
    return {"name": "t", "seed": 0, "finetune": ft}


def write_cfg(tmp_path, cfg):
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path
