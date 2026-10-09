import hashlib
import sys
from pathlib import Path

from common.jsonl import read_qa, write_jsonl
from finetune.config import ft_settings, load_ft_config
from finetune.data import to_messages


def split_of(row_id, seed, valid, test):
    """Appartenance déterministe : ne dépend que de (seed, id), jamais des autres lignes."""
    h = hashlib.sha256(f"{seed}:{row_id}".encode()).digest()
    x = int.from_bytes(h[:8], "big") / 2**64
    return "test" if x < test else "valid" if x < test + valid else "train"


def prepare(cfg):
    s = ft_settings(cfg)
    rows = read_qa(s["source"])
    parts = {"train": [], "valid": [], "test": []}
    for r in rows:
        parts[split_of(r["id"], s["split"]["seed"], s["split"]["valid"], s["split"]["test"])].append(r)
    empty = [k for k, v in parts.items() if not v]
    if empty:
        counts = {k: len(v) for k, v in parts.items()}
        raise ValueError(
            f"{s['source']}: {len(rows)} rows give an empty split ({counts}); "
            "add more rows or adjust finetune.split"
        )
    out = Path(s["data_dir"])
    for name, part in parts.items():
        write_jsonl(
            out / f"{name}.jsonl",
            [{"messages": to_messages(r["question"], s["system_prompt"], r["answer"])} for r in part],
        )
        if name != "train":  # format du harnais M0 : valid sert à choisir, test à conclure
            write_jsonl(out / f"{name}_eval.jsonl", part)
    return {k: len(v) for k, v in parts.items()}


def main(argv):
    cfg = load_ft_config(argv[0])
    counts = prepare(cfg)
    out = cfg["finetune"]["data_dir"]
    print(f"train {counts['train']} · valid {counts['valid']} · test {counts['test']} → {out}")
    print(f"Suite : uv run python -m finetune.train {argv[0]}")
    return counts


if __name__ == "__main__":
    main(sys.argv[1:])
