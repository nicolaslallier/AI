import hashlib
import importlib
import json
import random
import sys
from pathlib import Path

from common.config import load_config
from common.jsonl import read_qa
from evalkit.harness import evaluate
from evalkit.runlog import save_run


def load_system(spec):
    module, sep, func = spec.partition(":")
    if not (module and sep and func):
        raise ValueError(f"system must be 'module:function', got {spec!r}")
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as e:
        if e.name != module and not module.startswith(f"{e.name}."):
            raise  # a dependency of the system is missing: keep the real error
        raise ValueError(f"cannot load system {spec!r}: {e}") from e
    try:
        return getattr(mod, func)
    except AttributeError as e:
        raise ValueError(f"cannot load system {spec!r}: {e}") from e


def main(argv):
    cfg = load_config(argv[0])
    for k in ("eval_set", "system"):
        if not isinstance(cfg.get(k), str):
            raise ValueError(f"{argv[0]}: '{k}' is required and must be a string")
    random.seed(cfg["seed"])
    digest = hashlib.sha256(Path(cfg["eval_set"]).read_bytes()).hexdigest()
    qa = read_qa(cfg["eval_set"])
    system = load_system(cfg["system"])(cfg)
    metrics, results = evaluate(system, qa)
    run_dir = save_run(cfg, digest, metrics, results, root=cfg.get("runs_dir", "runs"))
    print(json.dumps(metrics, indent=2))
    print(f"run saved to {run_dir}")
    return metrics


if __name__ == "__main__":
    main(sys.argv[1:])
