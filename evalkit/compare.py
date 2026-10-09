from common.config import is_int, load_config, merge_section
from rag.config import rag_settings

SYSTEMS = ("base", "base+rag", "ft", "ft+rag")
SCHEMA = {"systems": list(SYSTEMS), "adapter": "", "system_prompt": "", "train_file": "", "min_gap": 2}


def compare_settings(cfg):
    c = merge_section(SCHEMA, cfg.get("compare", {}), "compare")
    s = c["systems"]
    if not (isinstance(s, list) and s and all(x in SYSTEMS for x in s) and len(set(s)) == len(s)):
        raise ValueError(f"compare.systems must be a non-empty list, without duplicates, among {list(SYSTEMS)}")
    for key in ("adapter", "system_prompt", "train_file"):
        if not isinstance(c[key], str):
            raise ValueError(f"compare.{key} must be a string")
    if any(x.startswith("ft") for x in s) and not c["adapter"]:
        raise ValueError("compare.adapter is required when a 'ft' system is selected (run finetune.train first)")
    if not (is_int(c["min_gap"]) and c["min_gap"] >= 1):
        raise ValueError("compare.min_gap must be an integer >= 1")
    return c


def load_compare_config(path):
    cfg = load_config(path)
    if not isinstance(cfg.get("eval_set"), str):
        raise ValueError(f"{path}: 'eval_set' is required and must be a string")
    try:
        cfg["compare"] = compare_settings(cfg)
        cfg["rag"] = rag_settings(cfg)
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from e
    return cfg
