from common.config import load_config

# None = clé obligatoire ; un dict = sous-section avec ses propres défauts.
SCHEMA = {
    "docs_dir": None,
    "index_dir": "data/index",
    "chunking": {"size": 800, "overlap": 100},
    "embedding": {"model": None, "batch_size": 16, "query_prefix": "", "passage_prefix": ""},
    "retrieval": {"mode": "dense", "k": 5, "candidates": 20, "rerank": ""},
    "generation": {"model": None, "max_tokens": 400, "temperature": 0.0},
}


def _merge(schema, given, where):
    if not isinstance(given, dict):
        raise ValueError(f"'{where}' must be a mapping")
    unknown = set(given) - set(schema)
    if unknown:
        raise ValueError(f"unknown key(s) in '{where}': {sorted(unknown)}")
    out = {}
    for key, default in schema.items():
        if isinstance(default, dict):
            out[key] = _merge(default, given.get(key, {}), f"{where}.{key}")
        elif key in given:
            out[key] = given[key]
        elif default is None:
            raise ValueError(f"'{where}.{key}' is required")
        else:
            out[key] = default
    return out


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def rag_settings(cfg):
    s = _merge(SCHEMA, cfg.get("rag"), "rag")
    size, overlap = s["chunking"]["size"], s["chunking"]["overlap"]
    if not (_is_int(size) and _is_int(overlap) and size > 0 and 0 <= overlap < size):
        raise ValueError("rag.chunking: need integers with size > 0 and 0 <= overlap < size")
    if not (_is_int(s["retrieval"]["k"]) and s["retrieval"]["k"] > 0):
        raise ValueError("rag.retrieval.k must be a positive integer")
    r = s["retrieval"]
    if "candidates" not in cfg["rag"].get("retrieval", {}) and _is_int(r["k"]):
        r["candidates"] = max(r["candidates"], r["k"])  # défaut qui suit k ; un candidates explicite < k reste une erreur
    if r["mode"] not in ("dense", "hybrid"):
        raise ValueError("rag.retrieval.mode must be 'dense' or 'hybrid'")
    if not isinstance(r["rerank"], str):
        raise ValueError("rag.retrieval.rerank must be a string (model id, or '' for none)")
    if not (_is_int(r["candidates"]) and r["candidates"] >= r["k"]):
        raise ValueError("rag.retrieval.candidates must be an integer >= k")
    return s


def load_rag_config(path):
    cfg = load_config(path)
    try:
        cfg["rag"] = rag_settings(cfg)
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from e
    return cfg
