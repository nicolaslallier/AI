import hashlib
import json
from datetime import date
from pathlib import Path

import yaml

from common.jsonl import write_jsonl


def save_run(cfg, data_path, metrics, results, root="runs"):
    base = Path(root) / f"{date.today().isoformat()}-{cfg['name']}"
    run_dir, n = base, 2
    while run_dir.exists():
        run_dir = Path(f"{base}-{n}")
        n += 1
    run_dir.mkdir(parents=True)
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    digest = hashlib.sha256(Path(data_path).read_bytes()).hexdigest()
    (run_dir / "metrics.json").write_text(
        json.dumps({**metrics, "data_sha256": digest}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_jsonl(run_dir / "outputs.jsonl", results)
    return run_dir
