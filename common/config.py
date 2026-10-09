import re

import yaml


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError(f"{path}: config must be a YAML mapping")
    if not re.fullmatch(r"[\w.-]+", str(cfg.get("name", ""))):
        raise ValueError(f"{path}: 'name' is required and may only contain letters, digits, _ . -")
    if not isinstance(cfg.get("seed"), int):
        raise ValueError(f"{path}: 'seed' is required and must be an integer")
    return cfg
