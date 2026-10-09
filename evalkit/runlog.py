import json

import yaml

from common.jsonl import write_jsonl
from common.runs import new_run_dir


def save_run(cfg, data_sha256, metrics, results, root="runs"):
    run_dir = new_run_dir(cfg["name"], root)
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (run_dir / "metrics.json").write_text(
        json.dumps({**metrics, "data_sha256": data_sha256}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_jsonl(run_dir / "outputs.jsonl", results)
    return run_dir
