import hashlib
import json
import random
import shlex
import sys
import time
from pathlib import Path

import yaml

import finetune.system as ft_system
import rag.system as rag_system
from common.config import is_int, load_config, merge_section
from common.jsonl import read_jsonl, read_qa, write_jsonl
from common.runs import new_run_dir
from evalkit.harness import evaluate
from evalkit.metrics import normalize
from evalkit.report import render_report
from finetune.data import to_messages
from rag.config import rag_settings
from rag.index import index_key, open_index
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


def leaked_ids(train_file, qa):
    """Questions d'évaluation déjà vues à l'entraînement : elles avantageraient `ft` pour de mauvaises raisons."""
    if not train_file:
        return []
    try:
        rows = read_jsonl(train_file)
    except OSError as e:
        raise ValueError(f"compare.train_file {train_file}: unreadable ({e.strerror or e})") from e
    seen = set()
    for n, row in enumerate(rows, 1):
        msgs = row.get("messages", []) if isinstance(row, dict) else None
        if not (isinstance(msgs, list) and all(isinstance(m, dict) for m in msgs)):
            raise ValueError(f"{train_file}: row {n} is not of the form {{\"messages\": [{{...}}]}}")
        for m in msgs:
            if m.get("role") == "user":
                if not isinstance(m.get("content"), str):
                    raise ValueError(f"{train_file}: row {n}: user 'content' must be a string")
                seen.add(normalize(m["content"]))
    return [r["id"] for r in qa if normalize(r["question"]) in seen]


def run_compare(systems, qa):
    metrics, results, latency = {}, {}, {}
    for name, system in systems.items():
        times = []

        def timed(question, system=system, times=times):
            t = time.perf_counter()
            out = system(question)
            times.append(time.perf_counter() - t)
            return out

        metrics[name], results[name] = evaluate(timed, qa)
        latency[name] = sum(times) / len(times) if times else None
    return metrics, results, latency


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _manifest(cfg):
    c, r = cfg["compare"], cfg["rag"]
    m = {"eval_set_sha256": _sha256(cfg["eval_set"]), "base_model": r["generation"]["model"],
         "adapter_config_sha256": None, "ft_data_sha256": None, "index_key": None}
    if c["adapter"]:
        conf = Path(c["adapter"]) / "adapter_config.json"
        if not conf.is_file():
            raise ValueError(f"compare.adapter : {conf} introuvable ; lancer d'abord `finetune.train` "
                             "et reporter le dossier `adapters` du run")
        m["adapter_config_sha256"] = _sha256(conf)
        train_metrics = Path(c["adapter"]).parent / "metrics.json"  # écrit par finetune.train
        if train_metrics.is_file():
            try:
                m["ft_data_sha256"] = json.loads(train_metrics.read_text(encoding="utf-8")).get("data_sha256")
            except (ValueError, AttributeError) as e:
                raise ValueError(f"{train_metrics}: invalid metrics file ({e})") from e
    if any(x.endswith("+rag") for x in c["systems"]):
        m["index_key"] = index_key(r, load_documents(r["docs_dir"]))
    return m


def main(argv):
    cfg = load_compare_config(argv[0])
    qa = read_qa(cfg["eval_set"])
    if not qa:
        raise ValueError(f"{cfg['eval_set']}: eval set is empty")
    manifest = _manifest(cfg)  # avant build_systems : un adaptateur illisible échoue sans charger de modèle
    leaks = leaked_ids(cfg["compare"]["train_file"], qa)  # aussi avant tout chargement de modèle
    warnings = [f"Fuite d'évaluation : {len(leaks)} question(s) vue(s) à l'entraînement ({', '.join(map(str, leaks))}) ; "
                "les résultats de `ft` sont optimistes."] if leaks else []
    notes = [] if cfg["compare"]["train_file"] else ["Aucune détection de fuite (`compare.train_file` non renseigné)."]
    random.seed(cfg["seed"])
    import mlx.core as mx

    mx.random.seed(cfg["seed"])
    systems = build_systems(cfg)
    metrics, results, latency = run_compare(systems, qa)
    command = f"uv run python -m evalkit.compare {shlex.quote(argv[0])}"
    report = render_report(cfg["name"], command, metrics, results, latency, cfg["compare"]["min_gap"], warnings, notes)
    run_dir = new_run_dir(cfg["name"], cfg.get("runs_dir", "runs"))  # après le rendu : pas de dossier vide si il échoue
    (run_dir / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (run_dir / "metrics.json").write_text(json.dumps(
        {"systems": {n: {**m, "latency_s": latency[n]} for n, m in metrics.items()}, "manifest": manifest},
        indent=2, ensure_ascii=False), encoding="utf-8")
    write_jsonl(run_dir / "outputs.jsonl", [{"system": n, **row} for n, rows in results.items() for row in rows])
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"run saved to {run_dir}")
    return metrics


if __name__ == "__main__":
    main(sys.argv[1:])
