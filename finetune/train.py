import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

from common.runs import new_run_dir
from finetune.config import ft_settings, load_ft_config
from finetune.curves import plot, read_log, summarize

CALLBACK_NAME = "ailab-jsonl"
LOG_NAME = "train_log.jsonl"


class JsonlCallback:
    """Callback `mlx-lm` : une ligne JSON par rapport. `log_dir` = le dossier d'adaptateurs ; le journal
    est écrit à côté (dans le dossier du run), pas dedans."""

    def __init__(self, project_name, log_dir, config, wrapped_callback=None):
        self.path = Path(log_dir).parent / LOG_NAME

    def _write(self, row):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def on_train_loss_report(self, info):
        self._write(
            {
                "step": info["iteration"],
                "train_loss": info["train_loss"],
                "it_per_sec": info["iterations_per_second"],
                "peak_mem_gb": info["peak_memory"],
            }
        )

    def on_val_loss_report(self, info):
        self._write({"step": info["iteration"], "val_loss": info["val_loss"]})


def mlx_args(s, seed, adapter_dir):
    """Traduit la section `finetune` en arguments `mlx_lm.lora` (les autres gardent les défauts de mlx-lm)."""
    t, lora = s["train"], s["lora"]
    return {
        "model": s["model"],
        "train": True,
        "data": s["data_dir"],
        "seed": seed,
        "adapter_path": str(adapter_dir),
        "num_layers": lora["num_layers"],
        "lora_parameters": {"rank": lora["rank"], "scale": lora["scale"], "dropout": lora["dropout"]},
        "batch_size": t["batch_size"],
        "iters": t["iters"],
        "learning_rate": t["learning_rate"],
        "steps_per_report": t["steps_per_report"],
        "steps_per_eval": t["steps_per_eval"],
        "val_batches": t["val_batches"],
        "max_seq_length": t["max_seq_length"],
        "save_every": t["save_every"],
        "grad_checkpoint": t["grad_checkpoint"],
        "report_to": CALLBACK_NAME,
    }


def run_mlx_lora(args):
    from mlx_lm.lora import CONFIG_DEFAULTS, run
    from mlx_lm.tuner.callbacks import SUPPORT_CALLBACK

    # `run()` ignore tout callback passé en paramètre et n'utilise que `report_to` :
    # on enregistre donc le nôtre dans la table de mlx-lm.
    SUPPORT_CALLBACK[CALLBACK_NAME] = JsonlCallback
    run(SimpleNamespace(**{**CONFIG_DEFAULTS, **args}))


def data_sha256(data_dir):
    h = hashlib.sha256()
    for name in ("train", "valid", "test"):
        h.update((Path(data_dir) / f"{name}.jsonl").read_bytes())
    return h.hexdigest()


def train(cfg, root="runs"):
    s = ft_settings(cfg)
    d = Path(s["data_dir"])
    for n in ("train", "valid", "test"):
        if not (d / f"{n}.jsonl").is_file():
            raise ValueError(f"{d}: missing {n}.jsonl — run: uv run python -m finetune.prepare <config>")
    bs = s["train"]["batch_size"]
    for n in ("train", "valid"):
        rows = len((d / f"{n}.jsonl").read_text(encoding="utf-8").splitlines())
        if rows < bs:
            raise ValueError(f"{d / f'{n}.jsonl'}: {rows} rows < finetune.train.batch_size ({bs})")
    sha = data_sha256(d)
    run_dir = new_run_dir(cfg["name"], root)
    (run_dir / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    run_mlx_lora(mlx_args(s, cfg["seed"], run_dir / "adapters"))
    log = read_log(run_dir / LOG_NAME)
    metrics = {**summarize(log), "iters": s["train"]["iters"], "data_sha256": sha}
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    plot(log, run_dir / "curves.png")
    return run_dir, metrics


def main(argv):
    cfg = load_ft_config(argv[0])
    run_dir, m = train(cfg)
    print(json.dumps(m, indent=2))
    if m.get("val_rising"):
        print("⚠ la perte de validation remonte : sur-apprentissage probable (moins d'itérations, rang plus faible).")
    print(f"run saved to {run_dir}")
    print(f"Suite : mettre finetune.adapter: {run_dir}/adapters puis uv run python -m evalkit.run {argv[0]}")
    return m


if __name__ == "__main__":
    main(sys.argv[1:])
