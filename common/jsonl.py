import json
from pathlib import Path

QA_KEYS = ("id", "question", "answer", "sources")


def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{n}: invalid JSON ({e.msg})") from e
    return rows


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_qa(path):
    rows = read_jsonl(path)
    seen = set()
    for i, r in enumerate(rows, 1):
        for k in QA_KEYS:
            if k not in r:
                raise ValueError(f"{path}: row {i}: missing key '{k}'")
        if not isinstance(r["sources"], list):
            raise ValueError(f"{path}: row {i}: 'sources' must be a list")
        if not str(r["answer"]).strip():
            raise ValueError(f"{path}: row {i}: 'answer' must not be empty")
        if r["id"] in seen:
            raise ValueError(f"{path}: row {i}: duplicate id {r['id']!r}")
        seen.add(r["id"])
    return rows
