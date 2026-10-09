# M2 — Fine-tuning v1 (préparation, LoRA avec MLX, courbes, adaptateur rechargeable) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entraîner un adaptateur LoRA sur un modèle 1–3B (`uv run python -m finetune.train CONFIG`), voir la perte de validation baisser dans `runs/<date>-<nom>/`, puis recharger l'adaptateur et l'évaluer avec le harnais M0 (`uv run python -m evalkit.run CONFIG`).

**Architecture:** Un nouveau paquet `finetune/` (config, préparation des données, entraînement, courbes, système évaluable). L'entraînement appelle `mlx_lm.lora.run` en cours de processus avec un callback enregistré dans `mlx_lm.tuner.callbacks.SUPPORT_CALLBACK` qui écrit `train_log.jsonl` (parser la sortie texte de `mlx-lm` serait fragile : c'est une UI `rich`). Le système évaluable `finetune.system:build` est un callable `question -> {"answer", "sources": []}` branché sur le harnais M0, qui réutilise le `Generator` de `common/llm.py` (M1) et lui ajoute la vérification adaptateur ↔ modèle de base. Aucun test ne charge un vrai modèle sauf un test de fumée `slow`.

**Tech Stack:** Python 3.12, `uv`, `mlx-lm` (déjà là via M1), `matplotlib` (nouveau, courbes seulement — TRD §6.3), `pyyaml`, `pytest`.

**Spec:** `docs/PRD.md` (F10–F13, jalon M2), `docs/TRD.md` (§2 modèles, §3 mémoire, §4.4, §6.3, §7.1, §10), `docs/BACKEND_SCHEMA.md` (§2.3, §3.2 `train_log.jsonl` / `adapter/`), `docs/UX.md` (§3.2, §4.5). **M0 et M1 sont fusionnés (PR #6, #7) et priment sur les docs quand ils divergent** : paquet `evalkit`, jeu d'évaluation `{id, question, answer, sources}`, système = callable, config = dict YAML validé à la main (pas de `pydantic`), CLI à argument positionnel (`python -m finetune.train CONFIG`).

## Décisions prises par ce plan (questions ouvertes du PRD §8 / TRD §12)

- **Tâche de fine-tuning : le format de réponse, pas les faits.** Le jeu d'exemple apprend à répondre `Réponse : <capitale>.` à « Quelle est la capitale de … ? ». Le modèle de base connaît déjà les capitales ; seul le format change. C'est exactement ce que M3 doit montrer (le fine-tuning pour le style/format, le RAG pour les faits). Les vrais exemples de Nicolas remplaceront `ft_source.jsonl` sans changer le code : une ligne = `{id, question, answer, sources}`, le même format que le jeu d'évaluation M0 (`common.jsonl.read_qa`).
- **Modèle de départ : `mlx-community/Qwen2.5-3B-Instruct-4bit`** (TRD §2). Le choix définitif parmi les candidats se fait en Task 7, sur le jeu `valid` (jamais `test`).
- **`scale` et non `alpha`.** `mlx-lm` paramètre LoRA par `scale` (défaut 20.0), pas par `alpha` ; la config expose `lora.scale`.
- **Le journal de courbes est `train_log.jsonl`** (nom du BACKEND_SCHEMA §3.2), une ligne par rapport : `{"step", "train_loss", "it_per_sec", "peak_mem_gb"}` ou `{"step", "val_loss"}`. Le schéma d'une ligne unifiée `{step, train_loss, val_loss}` du BACKEND_SCHEMA ne tient pas : `mlx-lm` rapporte les deux à des itérations différentes.
- **Dossier d'adaptateur : `runs/<…>/adapters/`** (TRD §6.3) et non `adapter/` (BACKEND_SCHEMA §3.2).
- **Volontairement hors périmètre (YAGNI, à rouvrir si le besoin apparaît) :** `finetune chat` / `generate` interactifs (UX §3.2 étape 3 — `Generator(adapter_path=…)` couvre F13 pour l'évaluation), fusion `mlx_lm.fuse` (TRD §6.3 : optionnelle), `--resume` et estimation mémoire avant entraînement (UX §4.5 — le TRD §3 donne les leviers à la main), statistiques en tokens dans `prepare` (comptes et longueurs en caractères seulement), QLoRA explicite (un modèle `-4bit` rend l'entraînement QLoRA d'office).
- **Dette connue, non traitée ici :** `rag/config.py` garde sa propre copie de `_merge`/`_is_int` (des correctifs de revue de PR #7 touchent ce fichier ailleurs). `common.config.merge_section`/`is_int` en sont la version partagée ; dédupliquer `rag/config.py` dans un commit séparé une fois ces correctifs fusionnés.

## Global Constraints

- `finetune/` n'importe jamais `rag/` ni `evalkit/` ; il ne partage que `common/` et le contrat système M0 (`answer(question) -> {"answer": str, "sources": list[str]}`).
- Dépendances gérées avec `uv`, `uv.lock` commité ; Python 3.12. Une seule dépendance ajoutée : `matplotlib` (TRD §6.3).
- **Le jeu `test` ne sert jamais à choisir un hyperparamètre ni un modèle** (TRD §4.4). Les configs d'exemple pointent `eval_set` sur `valid_eval.jsonl` ; `test_eval.jsonl` n'est utilisé qu'une fois, pour conclure.
- Découpage train/valid/test **déterministe** : l'appartenance d'une ligne ne dépend que de `(seed, id)` — ajouter des lignes au source ne déplace jamais une ligne existante.
- Le format de chat est unique : `finetune.data.to_messages` sert à l'entraînement et à l'inférence (un prompt différent invalide l'adaptateur).
- Un adaptateur n'est valide que pour le modèle de base qui l'a produit : `Generator` le vérifie au chargement et échoue avant tout téléchargement.
- Un run est immuable : `runs/<date>-<nom>` n'est jamais réécrit ; collision → suffixe `-2`, `-3`… (`common.runs.new_run_dir`).
- Graine de la config propagée (`seed` à `mlx_lm.lora`, découpage, `mx.random.seed` à l'inférence). Température 0 par défaut.
- Aucun poids commité ; `data/` et `runs/` restent ignorés, seuls les exemples synthétiques de `data/examples/` sont versionnés.

## Review Focus

- Adaptateur entraîné sur le modèle A chargé avec le modèle B, ou chemin qui n'est pas un dossier d'adaptateur : erreur nommant les deux modèles / `adapter_config.json`, **avant** tout chargement de poids (Task 4).
- Source trop petit (une seule ligne) ou id dupliqué : `prepare` échoue en nommant le fichier et les effectifs, au lieu d'écrire un `valid.jsonl` vide qui supprimerait silencieusement la perte de validation (Task 2).
- Journal sans aucun point de validation (`iters < steps_per_eval`), vide, ou avec une perte `nan` : le résumé ne plante pas, `val_rising` n'est pas inventé ; perte de validation qui remonte de > 5 % au-dessus du meilleur point : avertissement affiché (Task 3).
- `finetune.train` lancé avant `finetune.prepare`, faute de frappe dans le YAML (`lroa:`), `iters: 0` : échec immédiat qui nomme la commande ou la clé, sans créer de dossier `runs/` (Tasks 1 et 5).
- Deuxième entraînement avec la même config le même jour : nouveau dossier, le premier adaptateur est intact (Tasks 3 et 5) ; prompt d'inférence différent du prompt d'entraînement (message système oublié) : un test pin l'égalité (Tasks 2 et 6).

---

### Task 1: Synchronisation, dépendance, configuration et données d'exemple

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`), `common/config.py`
- Create: `finetune/__init__.py`, `finetune/config.py`
- Create: `configs/ft-example.yaml`, `configs/ft-llama.yaml`, `data/examples/ft_source.jsonl`
- Create: `tests/ft_fakes.py`, `tests/test_ft_config.py`

**Interfaces:**
- Consumes: `common.config.load_config(path) -> dict` (M0).
- Produces: `common.config.is_int(v) -> bool` et `common.config.merge_section(schema: dict, given: dict, where: str) -> dict` (`None` = clé obligatoire, `dict` = sous-section ; clé inconnue ou obligatoire absente → `ValueError`).
- Produces: `finetune.config.ft_settings(cfg: dict) -> dict` (valide `cfg["finetune"]`, applique les défauts) et `finetune.config.load_ft_config(path) -> dict` (`load_config` + validation, `cfg["finetune"]` complété ; l'erreur est préfixée par le chemin du fichier). Clés : `source`, `data_dir`, `model`, `system_prompt` (`""`), `adapter` (`""` = pas d'adaptateur), `split{valid,test}`, `lora{rank,scale,dropout,num_layers}`, `train{batch_size,learning_rate,iters,steps_per_report,steps_per_eval,val_batches,max_seq_length,save_every,grad_checkpoint}`, `generation{max_tokens,temperature}`.
- Produces: `tests/ft_fakes.py` avec `make_ft_cfg(tmp_path, **ft_overrides) -> dict` (source = `data/examples/ft_source.jsonl`, `data_dir` dans `tmp_path`, `model="fake-model"`, `iters=20`) et `write_cfg(tmp_path, cfg) -> Path`.

- [ ] **Step 1: Se mettre à jour sur `main` (M1 est fusionné) et vérifier l'existant**

```bash
git fetch origin && git merge origin/main
ls common/llm.py rag/config.py .python-version
uv run pytest -q
```
Expected: les trois fichiers existent, tous les tests passent (101). Si `common/llm.py` manque, M1 n'est pas dans la branche : s'arrêter et le signaler.

- [ ] **Step 2: Ajouter matplotlib**

```bash
uv add matplotlib
uv run python -c "import matplotlib; print(matplotlib.__version__)"
```
Expected: une version s'affiche.

- [ ] **Step 3: Créer le jeu source synthétique**

`data/examples/ft_source.jsonl` (30 lignes, UTF-8) :
```jsonl
{"id": "cap01", "question": "Quelle est la capitale de la France ?", "answer": "Réponse : Paris.", "sources": []}
{"id": "cap02", "question": "Quelle est la capitale de l'Italie ?", "answer": "Réponse : Rome.", "sources": []}
{"id": "cap03", "question": "Quelle est la capitale de l'Espagne ?", "answer": "Réponse : Madrid.", "sources": []}
{"id": "cap04", "question": "Quelle est la capitale du Portugal ?", "answer": "Réponse : Lisbonne.", "sources": []}
{"id": "cap05", "question": "Quelle est la capitale de l'Allemagne ?", "answer": "Réponse : Berlin.", "sources": []}
{"id": "cap06", "question": "Quelle est la capitale de la Belgique ?", "answer": "Réponse : Bruxelles.", "sources": []}
{"id": "cap07", "question": "Quelle est la capitale des Pays-Bas ?", "answer": "Réponse : Amsterdam.", "sources": []}
{"id": "cap08", "question": "Quelle est la capitale de la Suisse ?", "answer": "Réponse : Berne.", "sources": []}
{"id": "cap09", "question": "Quelle est la capitale de l'Autriche ?", "answer": "Réponse : Vienne.", "sources": []}
{"id": "cap10", "question": "Quelle est la capitale de la Pologne ?", "answer": "Réponse : Varsovie.", "sources": []}
{"id": "cap11", "question": "Quelle est la capitale de la Grèce ?", "answer": "Réponse : Athènes.", "sources": []}
{"id": "cap12", "question": "Quelle est la capitale de la Suède ?", "answer": "Réponse : Stockholm.", "sources": []}
{"id": "cap13", "question": "Quelle est la capitale de la Norvège ?", "answer": "Réponse : Oslo.", "sources": []}
{"id": "cap14", "question": "Quelle est la capitale du Danemark ?", "answer": "Réponse : Copenhague.", "sources": []}
{"id": "cap15", "question": "Quelle est la capitale de la Finlande ?", "answer": "Réponse : Helsinki.", "sources": []}
{"id": "cap16", "question": "Quelle est la capitale de l'Irlande ?", "answer": "Réponse : Dublin.", "sources": []}
{"id": "cap17", "question": "Quelle est la capitale du Canada ?", "answer": "Réponse : Ottawa.", "sources": []}
{"id": "cap18", "question": "Quelle est la capitale du Japon ?", "answer": "Réponse : Tokyo.", "sources": []}
{"id": "cap19", "question": "Quelle est la capitale de l'Égypte ?", "answer": "Réponse : Le Caire.", "sources": []}
{"id": "cap20", "question": "Quelle est la capitale du Maroc ?", "answer": "Réponse : Rabat.", "sources": []}
{"id": "cap21", "question": "Quelle est la capitale du Kenya ?", "answer": "Réponse : Nairobi.", "sources": []}
{"id": "cap22", "question": "Quelle est la capitale de l'Argentine ?", "answer": "Réponse : Buenos Aires.", "sources": []}
{"id": "cap23", "question": "Quelle est la capitale du Pérou ?", "answer": "Réponse : Lima.", "sources": []}
{"id": "cap24", "question": "Quelle est la capitale du Chili ?", "answer": "Réponse : Santiago.", "sources": []}
{"id": "cap25", "question": "Quelle est la capitale de la Hongrie ?", "answer": "Réponse : Budapest.", "sources": []}
{"id": "cap26", "question": "Quelle est la capitale de la Roumanie ?", "answer": "Réponse : Bucarest.", "sources": []}
{"id": "cap27", "question": "Quelle est la capitale de la Croatie ?", "answer": "Réponse : Zagreb.", "sources": []}
{"id": "cap28", "question": "Quelle est la capitale de l'Islande ?", "answer": "Réponse : Reykjavik.", "sources": []}
{"id": "cap29", "question": "Quelle est la capitale de la Thaïlande ?", "answer": "Réponse : Bangkok.", "sources": []}
{"id": "cap30", "question": "Quelle est la capitale du Vietnam ?", "answer": "Réponse : Hanoï.", "sources": []}
```

- [ ] **Step 4: Écrire les fakes et les tests de configuration (échouent)**

`tests/ft_fakes.py`
```python
import yaml


def make_ft_cfg(tmp_path, **ft_overrides):
    ft = {
        "source": "data/examples/ft_source.jsonl",
        "data_dir": str(tmp_path / "data"),
        "model": "fake-model",
        "train": {"iters": 20, "steps_per_report": 5, "steps_per_eval": 10},
    }
    ft.update(ft_overrides)
    return {"name": "t", "seed": 0, "finetune": ft}


def write_cfg(tmp_path, cfg):
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path
```

`tests/test_ft_config.py`
```python
import pytest

from common.config import merge_section
from finetune.config import ft_settings, load_ft_config
from ft_fakes import make_ft_cfg, write_cfg


def test_merge_section_fills_defaults_and_rejects_unknown_keys():
    schema = {"a": None, "b": {"c": 1}}
    assert merge_section(schema, {"a": 5}, "x") == {"a": 5, "b": {"c": 1}}
    with pytest.raises(ValueError, match=r"unknown key\(s\) in 'x.b': \['cc'\]"):
        merge_section(schema, {"a": 5, "b": {"cc": 2}}, "x")
    with pytest.raises(ValueError, match="'x.a' is required"):
        merge_section(schema, {}, "x")


def test_example_config_loads_with_defaults():
    cfg = load_ft_config("configs/ft-example.yaml")
    s = cfg["finetune"]
    assert s["lora"]["rank"] == 8 and s["train"]["iters"] == 100 and s["adapter"] == ""


def test_typo_in_section_fails_with_the_key_name(tmp_path):
    cfg = make_ft_cfg(tmp_path, lroa={"rank": 4})
    with pytest.raises(ValueError, match="lroa"):
        ft_settings(cfg)
    path = write_cfg(tmp_path, cfg)
    with pytest.raises(ValueError, match=str(path)):
        load_ft_config(path)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"train": {"iters": 0}}, "finetune.train.iters"),
        ({"train": {"learning_rate": 0}}, "learning_rate"),
        ({"lora": {"rank": True}}, "finetune.lora.rank"),
        ({"split": {"valid": 0.6, "test": 0.5}}, "finetune.split"),
        ({"split": {"valid": 0, "test": 0.2}}, "finetune.split"),
        ({"generation": {"temperature": -1}}, "temperature"),
        ({"model": ""}, "finetune.model"),
    ],
)
def test_invalid_values_are_rejected(tmp_path, overrides, message):
    with pytest.raises(ValueError, match=message):
        ft_settings(make_ft_cfg(tmp_path, **overrides))


def test_missing_required_key(tmp_path):
    cfg = make_ft_cfg(tmp_path)
    del cfg["finetune"]["model"]
    with pytest.raises(ValueError, match="finetune.model' is required"):
        ft_settings(cfg)
```

- [ ] **Step 5: Lancer pour vérifier l'échec**

Run: `uv run pytest tests/test_ft_config.py -q`
Expected: FAIL — `ImportError: cannot import name 'merge_section' from 'common.config'`.

- [ ] **Step 6: Ajouter les helpers partagés à `common/config.py`**

Ajouter à la fin du fichier (sans toucher à `load_config`) :
```python
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
```

- [ ] **Step 7: Créer le paquet et la configuration**

`finetune/__init__.py` : fichier vide.

`finetune/config.py`
```python
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
```

`configs/ft-example.yaml`
```yaml
name: ft-example
seed: 0
eval_set: data/train/ft-example/valid_eval.jsonl
system: finetune.system:build
finetune:
  source: data/examples/ft_source.jsonl
  data_dir: data/train/ft-example
  model: mlx-community/Qwen2.5-3B-Instruct-4bit
  split: {valid: 0.15, test: 0.15}
  lora: {rank: 8, scale: 20.0, dropout: 0.0, num_layers: 16}
  train: {batch_size: 2, learning_rate: 1.0e-4, iters: 100, steps_per_eval: 20, max_seq_length: 512}
  generation: {max_tokens: 100, temperature: 0.0}
```

`configs/ft-llama.yaml` (candidat de la Task 7 : mêmes données, autre modèle)
```yaml
name: ft-llama
seed: 0
eval_set: data/train/ft-example/valid_eval.jsonl
system: finetune.system:build
finetune:
  source: data/examples/ft_source.jsonl
  data_dir: data/train/ft-example
  model: mlx-community/Llama-3.2-3B-Instruct-4bit
  split: {valid: 0.15, test: 0.15}
  lora: {rank: 8, scale: 20.0, dropout: 0.0, num_layers: 16}
  train: {batch_size: 2, learning_rate: 1.0e-4, iters: 100, steps_per_eval: 20, max_seq_length: 512}
  generation: {max_tokens: 100, temperature: 0.0}
```

- [ ] **Step 8: Lancer les tests**

Run: `uv run pytest -q`
Expected: PASS (tests M0/M1 inchangés + 11 nouveaux).

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock common/config.py finetune/__init__.py finetune/config.py configs/ft-example.yaml configs/ft-llama.yaml data/examples/ft_source.jsonl tests/ft_fakes.py tests/test_ft_config.py
git commit -m "feat(finetune): validated finetune config, shared merge_section, synthetic format dataset"
```

---

### Task 2: Préparation des données (`finetune.prepare`)

**Files:**
- Create: `finetune/data.py`, `finetune/prepare.py`
- Test: `tests/test_ft_prepare.py`

**Interfaces:**
- Consumes: `common.jsonl.read_qa`, `common.jsonl.write_jsonl` (M0) ; `finetune.config.ft_settings`, `load_ft_config` (Task 1) ; `tests/ft_fakes.make_ft_cfg`, `write_cfg`.
- Produces: `finetune.data.to_messages(question: str, system_prompt: str = "", answer: str | None = None) -> list[dict]` (messages de chat ; l'assistant n'est ajouté que si `answer` est fourni).
- Produces: `finetune.prepare.split_of(row_id, seed, valid, test) -> "train" | "valid" | "test"` ; `finetune.prepare.prepare(cfg) -> {"train": int, "valid": int, "test": int}` qui écrit dans `finetune.data_dir` : `train.jsonl`, `valid.jsonl`, `test.jsonl` (format `{"messages": […]}` attendu par `mlx-lm`) et `valid_eval.jsonl`, `test_eval.jsonl` (format harnais M0) ; `finetune.prepare.main(argv)` (CLI `python -m finetune.prepare CONFIG`).

- [ ] **Step 1: Écrire les tests (échouent)**

`tests/test_ft_prepare.py`
```python
import json

import pytest

from common.jsonl import read_jsonl, write_jsonl
from finetune.data import to_messages
from finetune.prepare import main, prepare, split_of
from ft_fakes import make_ft_cfg, write_cfg


def test_prepare_splits_example_source_without_overlap(tmp_path):
    counts = prepare(make_ft_cfg(tmp_path))
    assert sum(counts.values()) == 30 and all(counts.values())
    ids = {n: {r["id"] for r in read_jsonl(tmp_path / "data" / f"{n}_eval.jsonl")} for n in ("valid", "test")}
    assert not ids["valid"] & ids["test"]
    assert len(read_jsonl(tmp_path / "data" / "train.jsonl")) == counts["train"]


def test_chat_format_matches_inference_prompt(tmp_path):
    prepare(make_ft_cfg(tmp_path, system_prompt="Réponds brièvement."))
    row = read_jsonl(tmp_path / "data" / "valid.jsonl")[0]["messages"]
    assert [m["role"] for m in row] == ["system", "user", "assistant"]
    assert row[:2] == to_messages(row[1]["content"], "Réponds brièvement.")
    assert to_messages("q") == [{"role": "user", "content": "q"}]


def test_split_is_stable_when_rows_are_added():
    before = {i: split_of(f"id{i}", 0, 0.15, 0.15) for i in range(200)}
    after = {i: split_of(f"id{i}", 0, 0.15, 0.15) for i in range(400)}
    assert all(before[i] == after[i] for i in before)
    assert split_of("id1", 0, 0.15, 0.15) == split_of("id1", 0, 0.15, 0.15)
    assert {split_of(f"id{i}", 0, 0.15, 0.15) for i in range(200)} == {"train", "valid", "test"}


def test_seed_changes_the_split():
    a = [split_of(f"id{i}", 0, 0.15, 0.15) for i in range(100)]
    b = [split_of(f"id{i}", 1, 0.15, 0.15) for i in range(100)]
    assert a != b


def test_too_few_rows_gives_a_clear_error(tmp_path):
    src = tmp_path / "tiny.jsonl"
    write_jsonl(src, [{"id": "a", "question": "q", "answer": "r", "sources": []}])
    with pytest.raises(ValueError, match="empty split"):
        prepare(make_ft_cfg(tmp_path, source=str(src)))


def test_source_errors_name_the_file(tmp_path):
    src = tmp_path / "bad.jsonl"
    src.write_text(json.dumps({"id": "a", "question": "q"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing key 'answer'"):
        prepare(make_ft_cfg(tmp_path, source=str(src)))


def test_cli_prints_counts_and_next_step(tmp_path, capsys):
    path = write_cfg(tmp_path, make_ft_cfg(tmp_path))
    main([str(path)])
    out = capsys.readouterr().out
    assert "train" in out and "finetune.train" in out
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `uv run pytest tests/test_ft_prepare.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'finetune.data'`.

- [ ] **Step 3: Implémenter**

`finetune/data.py`
```python
def to_messages(question, system_prompt="", answer=None):
    """Format de chat unique : l'entraînement (avec `answer`) et l'inférence (sans) doivent coïncider."""
    msgs = [{"role": "system", "content": system_prompt}] if system_prompt else []
    msgs.append({"role": "user", "content": question})
    if answer is not None:
        msgs.append({"role": "assistant", "content": answer})
    return msgs
```

`finetune/prepare.py`
```python
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
        parts[split_of(r["id"], cfg["seed"], s["split"]["valid"], s["split"]["test"])].append(r)
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
```

- [ ] **Step 4: Lancer les tests**

Run: `uv run pytest tests/test_ft_prepare.py -q`
Expected: PASS (7 tests). Avec les 30 lignes d'exemple et `seed: 0`, le découpage donne 16 / 8 / 6.

- [ ] **Step 5: Essayer la CLI à la main**

```bash
uv run python -m finetune.prepare configs/ft-example.yaml
```
Expected: `train 16 · valid 8 · test 6 → data/train/ft-example` puis la commande suivante suggérée ; le dossier contient `train.jsonl valid.jsonl test.jsonl valid_eval.jsonl test_eval.jsonl`.

- [ ] **Step 6: Commit**

```bash
git add finetune/data.py finetune/prepare.py tests/test_ft_prepare.py
git commit -m "feat(finetune): deterministic train/valid/test split and chat-format preparation"
```

---

### Task 3: Dossier de run partagé et courbes

**Files:**
- Create: `common/runs.py`, `finetune/curves.py`
- Modify: `evalkit/runlog.py` (réutilise `new_run_dir`)
- Test: `tests/test_runs.py`, `tests/test_ft_curves.py` (les tests existants de `tests/test_runlog.py` servent de filet)

**Interfaces:**
- Produces: `common.runs.new_run_dir(name: str, root="runs") -> Path` (crée `root/<AAAA-MM-JJ>-<name>`, suffixe `-2`, `-3`… en cas de collision, jamais d'écrasement). `evalkit.runlog.save_run` garde la même signature et le même comportement.
- Produces: `finetune.curves.summarize(log: list[dict]) -> dict` (clés : `n_val_points` toujours ; `final_train_loss`, `peak_mem_gb`, `it_per_sec` s'il y a des lignes d'entraînement ; `first_val_loss`, `final_val_loss`, `best_val_loss`, `best_val_step`, `val_rising` s'il y a des points de validation finis), `finetune.curves.plot(log, path) -> None` (PNG matplotlib `Agg`), `finetune.curves.read_log(path) -> list[dict]` (`[]` si le fichier n'existe pas).

- [ ] **Step 1: Écrire les tests (échouent)**

`tests/test_runs.py`
```python
from common.runs import new_run_dir


def test_new_run_dir_never_reuses_a_directory(tmp_path):
    a = new_run_dir("exp", tmp_path)
    (a / "adapters").mkdir()
    b = new_run_dir("exp", tmp_path)
    c = new_run_dir("exp", tmp_path)
    assert len({a, b, c}) == 3
    assert b.name == f"{a.name}-2" and c.name == f"{a.name}-3"
    assert (a / "adapters").is_dir()
```

`tests/test_ft_curves.py`
```python
import math

from common.jsonl import write_jsonl
from finetune.curves import plot, read_log, summarize


def tr(step, loss):
    return {"step": step, "train_loss": loss, "it_per_sec": 2.0, "peak_mem_gb": 1.5}


def va(step, loss):
    return {"step": step, "val_loss": loss}


def test_summary_of_a_healthy_run():
    log = [va(0, 4.0), tr(10, 2.0), va(20, 1.0), tr(30, 0.8), va(40, 0.9)]
    s = summarize(log)
    assert s["first_val_loss"] == 4.0 and s["best_val_loss"] == 0.9 and s["best_val_step"] == 40
    assert s["final_val_loss"] == 0.9 and s["final_train_loss"] == 0.8
    assert s["peak_mem_gb"] == 1.5 and s["it_per_sec"] == 2.0 and s["n_val_points"] == 3
    assert s["val_rising"] is False


def test_rising_validation_loss_is_flagged():
    assert summarize([va(0, 4.0), va(20, 1.0), va(40, 1.5)])["val_rising"] is True


def test_log_without_validation_or_empty_does_not_crash():
    assert summarize([tr(10, 2.0)])["n_val_points"] == 0
    assert "best_val_loss" not in summarize([tr(10, 2.0)])
    assert summarize([]) == {"n_val_points": 0}


def test_nan_validation_loss_is_ignored():
    s = summarize([va(0, math.nan), va(20, 1.0)])
    assert s["first_val_loss"] == 1.0 and s["n_val_points"] == 1


def test_plot_writes_a_png_and_read_log_tolerates_missing_file(tmp_path):
    log = [va(0, 4.0), tr(10, 2.0), va(20, 1.0)]
    plot(log, tmp_path / "curves.png")
    assert (tmp_path / "curves.png").stat().st_size > 0
    plot([], tmp_path / "empty.png")
    write_jsonl(tmp_path / "log.jsonl", log)
    assert read_log(tmp_path / "log.jsonl") == log
    assert read_log(tmp_path / "nope.jsonl") == []
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `uv run pytest tests/test_runs.py tests/test_ft_curves.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'common.runs'`.

- [ ] **Step 3: Extraire `new_run_dir` et l'utiliser dans `evalkit`**

`common/runs.py`
```python
from datetime import date
from pathlib import Path


def new_run_dir(name, root="runs"):
    """Crée `runs/<date>-<name>` ; en cas de collision, un suffixe -2, -3… (un run n'est jamais écrasé)."""
    base = Path(root) / f"{date.today().isoformat()}-{name}"
    base.parent.mkdir(parents=True, exist_ok=True)
    run_dir, n = base, 2
    while True:
        try:
            run_dir.mkdir()
            return run_dir
        except FileExistsError:
            run_dir = Path(f"{base}-{n}")
            n += 1
```

`evalkit/runlog.py` (remplacer le fichier entier ; le comportement ne change pas)
```python
import json

import yaml

from common.jsonl import write_jsonl
from common.runs import new_run_dir


def save_run(cfg, data_sha256, metrics, results, root="runs"):
    run_dir = new_run_dir(cfg["name"], root)
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (run_dir / "metrics.json").write_text(
        json.dumps({**metrics, "data_sha256": data_sha256}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_jsonl(run_dir / "outputs.jsonl", results)
    return run_dir
```

- [ ] **Step 4: Implémenter les courbes**

`finetune/curves.py`
```python
import math
from pathlib import Path

from common.jsonl import read_jsonl


def summarize(log):
    """Agrège `train_log.jsonl` (une ligne par rapport : `step` + `train_loss` ou `val_loss`)."""
    train = [r for r in log if "train_loss" in r]
    val = [r for r in log if "val_loss" in r and math.isfinite(r["val_loss"])]
    out = {"n_val_points": len(val)}
    if train:
        out["final_train_loss"] = train[-1]["train_loss"]
        out["peak_mem_gb"] = max(r["peak_mem_gb"] for r in train)
        out["it_per_sec"] = sum(r["it_per_sec"] for r in train) / len(train)
    if val:
        best = min(val, key=lambda r: r["val_loss"])
        out.update(
            first_val_loss=val[0]["val_loss"],
            final_val_loss=val[-1]["val_loss"],
            best_val_loss=best["val_loss"],
            best_val_step=best["step"],
            # 5 % de tolérance : un léger bruit n'est pas du sur-apprentissage
            val_rising=val[-1]["val_loss"] > 1.05 * best["val_loss"],
        )
    return out


def plot(log, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    for key, label in (("train_loss", "train"), ("val_loss", "validation")):
        pts = [(r["step"], r[key]) for r in log if key in r and math.isfinite(r[key])]
        if pts:
            ax.plot(*zip(*pts), marker="o" if key == "val_loss" else None, label=label)
    ax.set_xlabel("itération")
    ax.set_ylabel("perte")
    if ax.lines:
        ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def read_log(path):
    return read_jsonl(path) if Path(path).exists() else []
```

- [ ] **Step 5: Lancer toute la suite**

Run: `uv run pytest -q`
Expected: PASS — notamment `tests/test_runlog.py` (le refactor ne change pas `save_run`) et les 6 nouveaux tests.

- [ ] **Step 6: Commit**

```bash
git add common/runs.py evalkit/runlog.py finetune/curves.py tests/test_runs.py tests/test_ft_curves.py
git commit -m "feat(finetune): shared never-overwrite run dir and loss-curve summary/plot"
```

---

### Task 4: Vérification adaptateur ↔ modèle de base

**Files:**
- Modify: `common/llm.py`
- Test: `tests/test_llm_adapter.py`

**Interfaces:**
- Consumes: `common.llm.Generator(model, adapter_path=None)` (M1).
- Produces: `common.llm.check_adapter(model: str, adapter_path) -> None` (lève `ValueError` si `adapter_config.json` est absent ou si son champ `model` — écrit par `mlx_lm.lora` — diffère de `model`). `Generator.__init__` l'appelle **avant** d'importer `mlx_lm` quand `adapter_path` est fourni.

- [ ] **Step 1: Écrire les tests (échouent)**

`tests/test_llm_adapter.py`
```python
import json

import pytest

from common.llm import Generator, check_adapter


def make_adapter(tmp_path, model="base-a"):
    d = tmp_path / "adapters"
    d.mkdir()
    (d / "adapter_config.json").write_text(json.dumps({"model": model}), encoding="utf-8")
    return d


def test_matching_adapter_passes(tmp_path):
    check_adapter("base-a", make_adapter(tmp_path))


def test_adapter_for_another_base_model_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="trained on 'base-a', not 'base-b'"):
        check_adapter("base-b", make_adapter(tmp_path))


def test_missing_or_wrong_directory_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="no adapter_config.json"):
        check_adapter("base-a", tmp_path / "nowhere")


def test_generator_checks_before_loading_any_weights(tmp_path):
    # Si la vérification n'avait pas lieu en premier, mlx_lm tenterait de télécharger « base-b ».
    with pytest.raises(ValueError, match="trained on"):
        Generator("base-b", adapter_path=make_adapter(tmp_path))
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `uv run pytest tests/test_llm_adapter.py -q`
Expected: FAIL — `ImportError: cannot import name 'check_adapter' from 'common.llm'`.

- [ ] **Step 3: Implémenter**

Dans `common/llm.py`, ajouter en tête du fichier (avant `class Generator`) :
```python
import json
from pathlib import Path


def check_adapter(model, adapter_path):
    """Un adaptateur LoRA n'est valide que pour le modèle de base qui l'a produit (TRD §6.3)."""
    cfg_file = Path(adapter_path) / "adapter_config.json"
    if not cfg_file.is_file():
        raise ValueError(f"{adapter_path}: no adapter_config.json (is this an adapter directory?)")
    trained_on = json.loads(cfg_file.read_text(encoding="utf-8")).get("model")
    if trained_on != model:
        raise ValueError(f"adapter {adapter_path} was trained on {trained_on!r}, not {model!r}")
```

et dans `Generator.__init__`, juste après la ligne `def __init__(self, model, adapter_path=None):`, insérer :
```python
        if adapter_path:
            check_adapter(model, adapter_path)
```
(le `from mlx_lm import load` qui suit reste inchangé).

- [ ] **Step 4: Lancer toute la suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/llm.py tests/test_llm_adapter.py
git commit -m "feat(common): refuse an adapter trained for a different base model"
```

---

### Task 5: Entraînement (`finetune.train`)

**Files:**
- Create: `finetune/train.py`
- Test: `tests/test_ft_train.py`

**Interfaces:**
- Consumes: `finetune.config.ft_settings`, `load_ft_config` ; `finetune.curves.read_log`, `summarize`, `plot` ; `common.runs.new_run_dir` ; `finetune.prepare.prepare` (dans les tests) ; `tests/ft_fakes.make_ft_cfg`.
- Produces: `finetune.train.mlx_args(s: dict, seed: int, adapter_dir) -> dict` (arguments `mlx_lm.lora`), `finetune.train.JsonlCallback(project_name, log_dir, config, wrapped_callback=None)` (écrit `train_log.jsonl` dans le **parent** de `log_dir`), `finetune.train.run_mlx_lora(args: dict) -> None` (seul point qui touche à `mlx-lm`, remplacé dans les tests), `finetune.train.train(cfg, root="runs") -> (Path, dict)` (dossier du run + métriques), `finetune.train.main(argv)`.
- Layout produit : `runs/<date>-<name>/{config.yaml, train_log.jsonl, metrics.json, curves.png, adapters/{adapter_config.json, adapters.safetensors}}`.

- [ ] **Step 1: Écrire les tests (échouent)**

`tests/test_ft_train.py`
```python
import json

import pytest

import finetune.train as ft_train
from common.jsonl import read_jsonl
from finetune.config import ft_settings
from finetune.prepare import prepare
from ft_fakes import make_ft_cfg


def fake_mlx(calls):
    def run(args):
        calls.append(args)
        cb = ft_train.JsonlCallback(None, args["adapter_path"], args)
        cb.on_val_loss_report({"iteration": 0, "val_loss": 4.0, "val_time": 0.1})
        cb.on_train_loss_report(
            {"iteration": 5, "train_loss": 2.0, "iterations_per_second": 3.0, "peak_memory": 1.2, "learning_rate": 1e-4}
        )
        cb.on_val_loss_report({"iteration": 9, "val_loss": 1.0, "val_time": 0.1})

    return run


def test_mlx_args_map_the_config(tmp_path):
    s = ft_settings(make_ft_cfg(tmp_path, lora={"rank": 4}, train={"iters": 7, "learning_rate": 5e-5}))
    a = ft_train.mlx_args(s, 3, tmp_path / "ad")
    assert a["model"] == "fake-model" and a["seed"] == 3 and a["train"] is True
    assert a["lora_parameters"] == {"rank": 4, "scale": 20.0, "dropout": 0.0}
    assert a["iters"] == 7 and a["learning_rate"] == 5e-5 and a["adapter_path"] == str(tmp_path / "ad")
    assert a["data"] == s["data_dir"] and a["report_to"] == ft_train.CALLBACK_NAME


def test_train_writes_run_dir_with_log_metrics_and_curves(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ft_train, "run_mlx_lora", fake_mlx(calls))
    cfg = make_ft_cfg(tmp_path)
    prepare(cfg)
    run_dir, m = ft_train.train(cfg, root=tmp_path / "runs")
    assert calls[0]["adapter_path"] == str(run_dir / "adapters")
    assert read_jsonl(run_dir / "train_log.jsonl")[1] == {
        "step": 5, "train_loss": 2.0, "it_per_sec": 3.0, "peak_mem_gb": 1.2,
    }
    saved = json.loads((run_dir / "metrics.json").read_text())
    assert saved == m and m["best_val_loss"] == 1.0 and m["first_val_loss"] == 4.0
    assert len(m["data_sha256"]) == 64 and (run_dir / "curves.png").exists()
    assert (run_dir / "config.yaml").exists()


def test_second_training_never_overwrites_the_first(tmp_path, monkeypatch):
    monkeypatch.setattr(ft_train, "run_mlx_lora", fake_mlx([]))
    cfg = make_ft_cfg(tmp_path)
    prepare(cfg)
    first, _ = ft_train.train(cfg, root=tmp_path / "runs")
    second, _ = ft_train.train(cfg, root=tmp_path / "runs")
    assert first != second and (first / "metrics.json").exists()
    assert len(read_jsonl(first / "train_log.jsonl")) == 3


def test_train_before_prepare_names_the_command(tmp_path, monkeypatch):
    monkeypatch.setattr(ft_train, "run_mlx_lora", fake_mlx([]))
    with pytest.raises(ValueError, match="finetune.prepare"):
        ft_train.train(make_ft_cfg(tmp_path), root=tmp_path / "runs")
    assert not (tmp_path / "runs").exists()
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `uv run pytest tests/test_ft_train.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'finetune.train'`.

- [ ] **Step 3: Implémenter**

`finetune/train.py`
```python
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

from common.runs import new_run_dir
from finetune.config import ft_settings, load_ft_config
from finetune.curves import plot, read_log, summarize

CALLBACK_NAME = "ailab-jsonl"
LOG_NAME = "train_log.jsonl"


class JsonlCallback:
    """Callback `mlx-lm` : une ligne JSON par rapport. `log_dir` = le dossier d'adaptateurs ; le journal
    est écrit à côté (dans le dossier du run), pas dedans."""

    def __init__(self, project_name, log_dir, config, wrapped_callback=None):
        self.path = Path(log_dir).parent / LOG_NAME

    def _write(self, row):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def on_train_loss_report(self, info):
        self._write(
            {
                "step": info["iteration"],
                "train_loss": info["train_loss"],
                "it_per_sec": info["iterations_per_second"],
                "peak_mem_gb": info["peak_memory"],
            }
        )

    def on_val_loss_report(self, info):
        self._write({"step": info["iteration"], "val_loss": info["val_loss"]})


def mlx_args(s, seed, adapter_dir):
    """Traduit la section `finetune` en arguments `mlx_lm.lora` (les autres gardent les défauts de mlx-lm)."""
    t, lora = s["train"], s["lora"]
    return {
        "model": s["model"],
        "train": True,
        "data": s["data_dir"],
        "seed": seed,
        "adapter_path": str(adapter_dir),
        "num_layers": lora["num_layers"],
        "lora_parameters": {"rank": lora["rank"], "scale": lora["scale"], "dropout": lora["dropout"]},
        "batch_size": t["batch_size"],
        "iters": t["iters"],
        "learning_rate": t["learning_rate"],
        "steps_per_report": t["steps_per_report"],
        "steps_per_eval": t["steps_per_eval"],
        "val_batches": t["val_batches"],
        "max_seq_length": t["max_seq_length"],
        "save_every": t["save_every"],
        "grad_checkpoint": t["grad_checkpoint"],
        "report_to": CALLBACK_NAME,
    }


def run_mlx_lora(args):
    from mlx_lm.lora import CONFIG_DEFAULTS, run
    from mlx_lm.tuner.callbacks import SUPPORT_CALLBACK

    # `run()` ignore tout callback passé en paramètre et n'utilise que `report_to` :
    # on enregistre donc le nôtre dans la table de mlx-lm.
    SUPPORT_CALLBACK[CALLBACK_NAME] = JsonlCallback
    run(SimpleNamespace(**{**CONFIG_DEFAULTS, **args}))


def data_sha256(data_dir):
    h = hashlib.sha256()
    for name in ("train", "valid", "test"):
        h.update((Path(data_dir) / f"{name}.jsonl").read_bytes())
    return h.hexdigest()


def train(cfg, root="runs"):
    s = ft_settings(cfg)
    missing = [n for n in ("train", "valid") if not (Path(s["data_dir"]) / f"{n}.jsonl").is_file()]
    if missing:
        raise ValueError(
            f"{s['data_dir']}: missing {missing[0]}.jsonl — run: uv run python -m finetune.prepare <config>"
        )
    run_dir = new_run_dir(cfg["name"], root)
    (run_dir / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    run_mlx_lora(mlx_args(s, cfg["seed"], run_dir / "adapters"))
    log = read_log(run_dir / LOG_NAME)
    metrics = {**summarize(log), "iters": s["train"]["iters"], "data_sha256": data_sha256(s["data_dir"])}
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    plot(log, run_dir / "curves.png")
    return run_dir, metrics


def main(argv):
    cfg = load_ft_config(argv[0])
    run_dir, m = train(cfg)
    print(json.dumps(m, indent=2))
    if m.get("val_rising"):
        print("⚠ la perte de validation remonte : sur-apprentissage probable (moins d'itérations, rang plus faible).")
    print(f"run saved to {run_dir}")
    print(f"Suite : mettre finetune.adapter: {run_dir}/adapters puis uv run python -m evalkit.run {argv[0]}")
    return m


if __name__ == "__main__":
    main(sys.argv[1:])
```

Pourquoi `SUPPORT_CALLBACK` : dans `mlx-lm` 0.32, `mlx_lm.lora.run()` écrase son paramètre `training_callback` par `get_reporting_callbacks(args.report_to, …)` ; la seule façon d'injecter un callback en cours de processus est donc de l'enregistrer sous un nom et de passer `report_to` (vérifié dans `.venv/…/mlx_lm/lora.py`). Si une mise à jour de `mlx-lm` casse ce point, `uv.lock` limite la casse et le test de fumée de la Task 7 la détecte.

- [ ] **Step 4: Lancer toute la suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add finetune/train.py tests/test_ft_train.py
git commit -m "feat(finetune): LoRA training via mlx-lm with train_log.jsonl, metrics and curves"
```

---

### Task 6: Système évaluable (`finetune.system`)

**Files:**
- Create: `finetune/system.py`
- Test: `tests/test_ft_system.py`

**Interfaces:**
- Consumes: `common.llm.Generator(model, adapter_path=None)` (Task 4 : vérifie l'adaptateur) ; `finetune.data.to_messages` ; `finetune.config.ft_settings` ; `evalkit.harness.evaluate(system, qa)` (dans les tests).
- Produces: `finetune.system.make_generator(s: dict) -> Generator` (adaptateur transmis seulement si `s["adapter"]` est non vide ; remplacé dans les tests) et `finetune.system.build(cfg) -> callable` (`question -> {"answer": str, "sources": []}`), utilisable comme `system: finetune.system:build` dans une config `evalkit.run`. `adapter: ""` évalue le modèle de base avec le même prompt : c'est la ligne de base du fine-tuning.

- [ ] **Step 1: Écrire les tests (échouent)**

`tests/test_ft_system.py`
```python
import finetune.system as ft_system
from common.jsonl import read_jsonl
from evalkit.harness import evaluate
from finetune.data import to_messages
from finetune.prepare import prepare
from ft_fakes import make_ft_cfg


class FormatGenerator:
    """Imite un modèle qui a appris le format : « Réponse : <capitale>. »"""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def generate(self, messages, max_tokens=400, temperature=0.0):
        self.calls.append((messages, max_tokens, temperature))
        return self.answers[messages[-1]["content"]]


def test_system_uses_the_training_prompt_and_feeds_the_harness(tmp_path, monkeypatch):
    cfg = make_ft_cfg(tmp_path, system_prompt="Réponds brièvement.", generation={"max_tokens": 50})
    prepare(cfg)
    qa = read_jsonl(tmp_path / "data" / "valid_eval.jsonl")
    gen = FormatGenerator({r["question"]: r["answer"] for r in qa})
    monkeypatch.setattr(ft_system, "make_generator", lambda s: gen)
    answer = ft_system.build(cfg)
    metrics, results = evaluate(answer, qa)
    assert metrics["accuracy"] == 1.0 and metrics["n"] == len(qa)
    assert gen.calls[0][0] == to_messages(qa[0]["question"], "Réponds brièvement.")
    assert gen.calls[0][1:] == (50, 0.0)
    assert results[0]["sources"] == []


def test_generator_receives_the_adapter_only_when_configured(tmp_path, monkeypatch):
    seen = []

    class Spy:
        def __init__(self, model, adapter_path=None):
            seen.append((model, adapter_path))

    monkeypatch.setattr("common.llm.Generator", Spy)
    from finetune.config import ft_settings

    ft_system.make_generator(ft_settings(make_ft_cfg(tmp_path)))
    ft_system.make_generator(ft_settings(make_ft_cfg(tmp_path, adapter="runs/x/adapters")))
    assert seen == [("fake-model", None), ("fake-model", "runs/x/adapters")]
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `uv run pytest tests/test_ft_system.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'finetune.system'`.

- [ ] **Step 3: Implémenter**

`finetune/system.py`
```python
from finetune.config import ft_settings
from finetune.data import to_messages


def make_generator(s):
    from common.llm import Generator

    return Generator(s["model"], adapter_path=s["adapter"] or None)


def build(cfg):
    import mlx.core as mx

    mx.random.seed(cfg["seed"])
    s = ft_settings(cfg)
    gen, g = make_generator(s), s["generation"]

    def answer(question):
        text = gen.generate(
            to_messages(question, s["system_prompt"]), max_tokens=g["max_tokens"], temperature=g["temperature"]
        )
        return {"answer": text, "sources": []}

    return answer
```

- [ ] **Step 4: Lancer toute la suite**

Run: `uv run pytest -q`
Expected: PASS (≈ 135 tests, aucun ne charge de modèle).

- [ ] **Step 5: Commit**

```bash
git add finetune/system.py tests/test_ft_system.py
git commit -m "feat(finetune): fine-tuned system pluggable into the M0 eval harness"
```

---

### Task 7: Test de fumée, choix du modèle de base et critère de réussite M2

**Files:**
- Modify: `pyproject.toml` (marqueur `slow`), `docs/TRD.md` (§12 point 3 : décision)
- Create: `tests/test_ft_smoke.py`

**Interfaces:**
- Consumes: `finetune.prepare.prepare`, `finetune.train.train`, `common.llm.Generator`, `tests/ft_fakes.make_ft_cfg`.
- Produces: marqueur pytest `slow` (exclu par défaut via `addopts = "-m 'not slow'"`, lancé avec `-m slow`).

- [ ] **Step 1: Ajouter le marqueur `slow`**

Dans `pyproject.toml`, sous `[tool.pytest.ini_options]`, ajouter après `testpaths = ["tests"]` :
```toml
addopts = "-m 'not slow'"
markers = ["slow: charge un vrai modèle (lancer avec -m slow)"]
```

- [ ] **Step 2: Écrire le test de fumée**

`tests/test_ft_smoke.py`
```python
import pytest

from common.jsonl import read_jsonl
from common.llm import Generator
from finetune.prepare import prepare
from finetune.train import train
from ft_fakes import make_ft_cfg

TINY = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"


@pytest.mark.slow
def test_train_reload_generate_on_a_tiny_model(tmp_path):
    cfg = make_ft_cfg(tmp_path, model=TINY, train={"iters": 20, "steps_per_report": 5, "steps_per_eval": 10, "max_seq_length": 256})
    prepare(cfg)
    run_dir, m = train(cfg, root=tmp_path / "runs")
    assert m["best_val_loss"] < m["first_val_loss"]
    assert any("val_loss" in r for r in read_jsonl(run_dir / "train_log.jsonl"))
    gen = Generator(TINY, adapter_path=run_dir / "adapters")
    assert isinstance(gen.generate([{"role": "user", "content": "Capitale de la France ?"}], max_tokens=10), str)
```

- [ ] **Step 3: Vérifier que la suite rapide l'ignore, puis lancer la fumée**

```bash
uv run pytest -q
uv run pytest -m slow -q
```
Expected: la première → tous les tests rapides passent, `1 deselected`. La seconde → `1 passed` (télécharge ≈ 300 Mo la première fois ; ≈ 10 s ensuite). Si elle échoue sur `SUPPORT_CALLBACK` ou `CONFIG_DEFAULTS`, la signature de `mlx_lm.lora` a changé : corriger `run_mlx_lora` (Task 5) avant de continuer.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml tests/test_ft_smoke.py
git commit -m "test(finetune): slow smoke test — train, reload adapter, generate on a tiny model"
```

- [ ] **Step 5: Choisir le modèle de base (manuel, ≈ 1 h par candidat — TRD §2)**

Même données, deux modèles (`configs/ft-example.yaml` = Qwen2.5-3B, `configs/ft-llama.yaml` = Llama-3.2-3B). Pour chaque config `X` :
```bash
uv run python -m finetune.prepare configs/X.yaml
uv run python -m finetune.train configs/X.yaml
```
Noter dans `runs/<…>/metrics.json` : `it_per_sec`, `peak_mem_gb` (doit rester ≤ 60 % de la RAM, TRD §3), `best_val_loss`. **Ne pas comparer les pertes entre modèles** (tokenizers différents) : comparer l'exactitude sur `valid_eval.jsonl`. Pour chaque candidat, copier la config en `configs/X-eval.yaml`, y ajouter sous `finetune:` la ligne `adapter: runs/<date>-X/adapters`, puis :
```bash
uv run python -m evalkit.run configs/X-eval.yaml
```
Lancer aussi une fois la config avec `adapter: ""` (ligne de base du même modèle). Retenir le modèle qui a la meilleure exactitude `valid`, à égalité celui qui est le plus rapide ; rappel TRD §7.4 : avec 8 questions, un écart de 1 réponse n'est pas un signal. Les `X-eval.yaml` sont des fichiers de travail : ne pas les commiter.

- [ ] **Step 6: Vérifier le critère de réussite du PRD (« adaptateur entraîné et rechargeable, perte de validation qui baisse »)**

Sur le run retenu : `metrics.json` a `best_val_loss < first_val_loss`, `curves.png` montre la courbe de validation qui descend, `val_rising` est `false` (sinon réduire `iters`), et l'évaluation avec adaptateur bat strictement la ligne de base sur `valid_eval.jsonl`. Pour conclure une seule fois : `sed 's/valid_eval/test_eval/' configs/X-eval.yaml > configs/X-final.yaml`, puis `uv run python -m evalkit.run configs/X-final.yaml` (non commité).

- [ ] **Step 7: Consigner la décision**

Dans `docs/TRD.md` §12, remplacer le point 3 (« **Modèle de base** — §2, à trancher en début de M2. ») par la décision réelle, par exemple : `3. **Modèle de base** — tranché en M2 : <modèle retenu> (exactitude valid <a>/8 contre <b>/8 pour <autre>, <it/s> it/s, <mém> Go de pic).` Remplacer aussi le point 2 si la tâche de fine-tuning réelle a changé de celle de l'exemple.

```bash
git add docs/TRD.md
git commit -m "docs: record the M2 base-model decision"
```

---

## Self-Review (faite à l'écriture du plan)

**Couverture du spec.** F10 → Tasks 1–2 (`prepare`, découpage déterministe, rapport de comptes). F11 → Tasks 1, 5 (hyperparamètres en config, `mlx_lm.lora`). F12 → Tasks 3, 5 (`train_log.jsonl`, `curves.png`, adaptateur + `config.yaml` + modèle dans `adapter_config.json`, perte de validation qui remonte signalée). F13 → Tasks 4, 6 (`Generator(adapter_path=…)` avec vérification modèle/adaptateur ; fusion hors périmètre, justifié en tête). Critère M2 du PRD → Task 7 step 6. TRD §11 « choisir le modèle de base » → Task 7 step 5. Exclusions assumées : `chat`, `--resume`, estimation mémoire, tokens dans `prepare`.

**Placeholders.** Aucun « TBD » ; chaque étape de code contient le code complet (extrait du code exécuté dans une copie de travail jetable basée sur `main` + M1 : 135 tests rapides verts, test `slow` vert sur `Qwen2.5-0.5B-Instruct-4bit`, base 0/8 contre adaptateur 2/8 après 40 itérations seulement).

**Cohérence des types.** `merge_section`/`is_int` (Task 1) → `ft_settings` (Task 1) → `prepare`/`train`/`system` ; `to_messages(question, system_prompt, answer)` identique en Tasks 2 et 6 ; `new_run_dir(name, root)` (Task 3) → Task 5 ; `summarize/plot/read_log` (Task 3) → Task 5 ; `check_adapter` (Task 4) → `Generator` → Task 6 ; clés du journal `step/train_loss/val_loss/it_per_sec/peak_mem_gb` identiques dans `JsonlCallback`, `summarize` et les tests.

**Review Focus.** Chaque ligne a son test : adaptateur ↔ modèle (`test_llm_adapter.py`), source trop petit (`test_too_few_rows_gives_a_clear_error`), journal vide/`nan`/validation qui remonte (`test_ft_curves.py`), train avant prepare + typo YAML + `iters: 0` (`test_train_before_prepare_names_the_command`, `test_typo_in_section_fails_with_the_key_name`, `test_invalid_values_are_rejected`), deux entraînements et prompt identique (`test_second_training_never_overwrites_the_first`, `test_chat_format_matches_inference_prompt`, `test_system_uses_the_training_prompt_and_feeds_the_harness`).
