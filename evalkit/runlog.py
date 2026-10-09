import json
from datetime import date
from pathlib import Path

import yaml

from common.jsonl import write_jsonl


def save_run(cfg, data_sha256, metrics, results, root="runs"):
    base = Path(root) / f"{date.today().isoformat()}-{cfg['name']}"
    base.parent.mkdir(parents=True, exist_ok=True)
    run_dir, n = base, 2
    while True:
        try:
            run_dir.mkdir()
            break
        except FileExistsError:
            run_dir = Path(f"{base}-{n}")
            n += 1
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (run_dir / "metrics.json").write_text(
        json.dumps({**metrics, "data_sha256": data_sha256}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_jsonl(run_dir / "outputs.jsonl", results)
    return run_dir
