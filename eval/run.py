import importlib
import json
import random
import sys

from common.config import load_config
from common.jsonl import read_qa
from eval.harness import evaluate
from eval.runlog import save_run


def load_system(spec):
    module, _, func = spec.partition(":")
    try:
        return getattr(importlib.import_module(module), func)
    except (ImportError, AttributeError) as e:
        raise ValueError(f"cannot load system {spec!r}: {e}") from e


def main(argv):
    cfg = load_config(argv[0])
    random.seed(cfg["seed"])
    qa = read_qa(cfg["eval_set"])
    system = load_system(cfg["system"])(cfg)
    metrics, results = evaluate(system, qa)
    run_dir = save_run(cfg, cfg["eval_set"], metrics, results, root=cfg.get("runs_dir", "runs"))
    print(json.dumps(metrics, indent=2))
    print(f"run saved to {run_dir}")
    return metrics


if __name__ == "__main__":
    main(sys.argv[1:])
