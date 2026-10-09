import math
from pathlib import Path

from common.jsonl import read_jsonl


def summarize(log):
    """Agrège `train_log.jsonl` (une ligne par rapport : `step` + `train_loss` ou `val_loss`)."""
    train = [r for r in log if "train_loss" in r]
    val = [r for r in log if "val_loss" in r and math.isfinite(r["val_loss"])]
    out = {"n_val_points": len(val)}
    if train:
        out["final_train_loss"] = train[-1]["train_loss"]
        out["peak_mem_gb"] = max(r["peak_mem_gb"] for r in train)
        out["it_per_sec"] = sum(r["it_per_sec"] for r in train) / len(train)
    if val:
        best = min(val, key=lambda r: r["val_loss"])
        out.update(
            first_val_loss=val[0]["val_loss"],
            final_val_loss=val[-1]["val_loss"],
            best_val_loss=best["val_loss"],
            best_val_step=best["step"],
            # 5 % de tolérance : un léger bruit n'est pas du sur-apprentissage
            val_rising=val[-1]["val_loss"] > 1.05 * best["val_loss"],
        )
    return out


def plot(log, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    for key, label in (("train_loss", "train"), ("val_loss", "validation")):
        pts = [(r["step"], r[key]) for r in log if key in r and math.isfinite(r[key])]
        if pts:
            ax.plot(*zip(*pts), marker="o" if key == "val_loss" else None, label=label)
    ax.set_xlabel("itération")
    ax.set_ylabel("perte")
    if ax.lines:
        ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def read_log(path):
    return read_jsonl(path) if Path(path).exists() else []
