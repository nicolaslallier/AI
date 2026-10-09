from common.config import is_int, load_config, merge_section

# None = clé obligatoire ; un dict = sous-section avec ses propres défauts.
SCHEMA = {
    "source": None,
    "data_dir": None,
    "model": None,
    "system_prompt": "",
    "adapter": "",
    "split": {"valid": 0.15, "test": 0.15},
    "lora": {"rank": 8, "scale": 20.0, "dropout": 0.0, "num_layers": 16},
    "train": {
        "batch_size": 2,
        "learning_rate": 1e-4,
        "iters": 600,
        "steps_per_report": 10,
        "steps_per_eval": 50,
        "val_batches": 25,
        "max_seq_length": 1024,
        "save_every": 100,
        "grad_checkpoint": False,
    },
    "generation": {"max_tokens": 200, "temperature": 0.0},
}

POSITIVE_INTS = (
    ("lora", "rank"), ("lora", "num_layers"), ("train", "batch_size"), ("train", "iters"),
    ("train", "steps_per_report"), ("train", "steps_per_eval"), ("train", "val_batches"),
    ("train", "max_seq_length"), ("train", "save_every"), ("generation", "max_tokens"),
)


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def ft_settings(cfg):
    s = merge_section(SCHEMA, cfg.get("finetune"), "finetune")
    for key in ("source", "data_dir", "model"):
        if not (isinstance(s[key], str) and s[key]):
            raise ValueError(f"finetune.{key} must be a non-empty string")
    for key in ("system_prompt", "adapter"):
        if not isinstance(s[key], str):
            raise ValueError(f"finetune.{key} must be a string")
    for sec, key in POSITIVE_INTS:
        if not (is_int(s[sec][key]) and s[sec][key] > 0):
            raise ValueError(f"finetune.{sec}.{key} must be a positive integer")
    v, t = s["split"]["valid"], s["split"]["test"]
    if not (_number(v) and _number(t) and v > 0 and t > 0 and v + t < 1):
        raise ValueError("finetune.split: valid and test must be > 0 and sum to < 1")
    if not (_number(s["train"]["learning_rate"]) and s["train"]["learning_rate"] > 0):
        raise ValueError("finetune.train.learning_rate must be a number > 0")
    if not isinstance(s["train"]["grad_checkpoint"], bool):
        raise ValueError("finetune.train.grad_checkpoint must be true or false")
    if not (_number(s["lora"]["scale"]) and s["lora"]["scale"] > 0):
        raise ValueError("finetune.lora.scale must be a number > 0")
    d = s["lora"]["dropout"]
    if not (_number(d) and 0 <= d < 1):
        raise ValueError("finetune.lora.dropout must be a number in [0, 1)")
    t = s["generation"]["temperature"]
    if not (_number(t) and t >= 0):
        raise ValueError("finetune.generation.temperature must be a number >= 0")
    return s


def load_ft_config(path):
    cfg = load_config(path)
    try:
        cfg["finetune"] = ft_settings(cfg)
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from e
    return cfg
