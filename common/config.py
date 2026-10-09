import re

import yaml


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError(f"{path}: config must be a YAML mapping")
    if not re.fullmatch(r"[\w.-]+", str(cfg.get("name", ""))):
        raise ValueError(f"{path}: 'name' is required and may only contain letters, digits, _ . -")
    if not isinstance(cfg.get("seed"), int) or isinstance(cfg["seed"], bool):
        raise ValueError(f"{path}: 'seed' is required and must be an integer")
    return cfg


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def merge_section(schema, given, where):
    """Complète `given` avec les défauts de `schema` ; clé inconnue ou obligatoire absente = erreur.

    None = clé obligatoire ; un dict = sous-section avec ses propres défauts.
    """
    if not isinstance(given, dict):
        raise ValueError(f"'{where}' must be a mapping")
    unknown = set(given) - set(schema)
    if unknown:
        raise ValueError(f"unknown key(s) in '{where}': {sorted(unknown)}")
    out = {}
    for key, default in schema.items():
        if isinstance(default, dict):
            out[key] = merge_section(default, given.get(key, {}), f"{where}.{key}")
        elif key in given:
            out[key] = given[key]
        elif default is None:
            raise ValueError(f"'{where}.{key}' is required")
        else:
            out[key] = default
    return out
