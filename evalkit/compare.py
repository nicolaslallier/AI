import finetune.system as ft_system
import rag.system as rag_system
from common.config import is_int, load_config, merge_section
from finetune.data import to_messages
from rag.config import rag_settings
from rag.index import open_index
from rag.ingest import load_documents

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


def build_systems(cfg):
    """Charge tout ce qu'il faut d'abord (index périmé, adaptateur incompatible = échec avant l'évaluation)."""
    c, r = cfg["compare"], cfg["rag"]
    g, want = r["generation"], c["systems"]
    gens = {}
    if {"base", "base+rag"} & set(want):
        gens["base"] = ft_system.make_generator({"model": g["model"], "adapter": ""})
    if {"ft", "ft+rag"} & set(want):
        gens["ft"] = ft_system.make_generator({"model": g["model"], "adapter": c["adapter"]})
    if any(x.endswith("+rag") for x in want):
        index = open_index(r, load_documents(r["docs_dir"]))
        embedder = rag_system.make_embedder(r)

    def plain(gen):
        def answer(question):
            text = gen.generate(
                to_messages(question, c["system_prompt"]), max_tokens=g["max_tokens"], temperature=g["temperature"]
            )
            return {"answer": text, "sources": []}

        return answer

    systems = {}
    for name in want:
        gen = gens["ft" if name.startswith("ft") else "base"]
        if name.endswith("+rag"):
            # system_prompt ne s'applique qu'aux systèmes sans RAG : les +rag gardent le prompt RAG de M1.
            systems[name] = rag_system.RagSystem(
                index, embedder, gen, r["retrieval"]["k"], g["max_tokens"], g["temperature"]
            )
        else:
            systems[name] = plain(gen)
    return systems
