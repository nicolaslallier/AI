# M3 — Comparaison des quatre systèmes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une seule commande, `uv run python -m evalkit.compare configs/compare.yaml`, évalue `base`, `base+rag`, `ft`, `ft+rag` sur le même jeu de questions et écrit un dossier `runs/<date>-<nom>/` avec un `report.md` (verdict, tableau, écarts non concluants, cas parlants, commande de reproduction).

**Architecture:** Aucun nouveau contrat : les quatre systèmes sont des callables `question -> dict` déjà acceptés par `evalkit.harness.evaluate`. Un module `evalkit/compare.py` les **assemble** à partir de briques existantes (`finetune.system.make_generator` avec/sans adaptateur, `rag.system.RagSystem`, `rag.index.open_index`), les évalue l'un après l'autre avec `evaluate`, mesure la latence autour de chaque appel et sauvegarde le run. `evalkit/report.py` est une fonction pure `rows → texte Markdown`, testable sans modèle. Un seul `Generator` base est partagé par `base` et `base+rag`, un seul `Generator` adaptateur par `ft` et `ft+rag` (TRD §5.2), un seul embedder/index pour les deux systèmes RAG.

**Tech Stack:** Python 3.12, `uv`, `pytest`, `pyyaml`. **Aucune nouvelle dépendance.**

**Spec:** `docs/PRD.md` (F14, jalon M3), `docs/TRD.md` (§5.2, §5.4, §6.4, §11 « vérifier la comparabilité des empreintes »), `docs/UX.md` §6.3 (structure du rapport), `docs/APPFLOW.md` §3.4. **M0, M1, M2 sont fusionnés et priment sur les docs quand ils divergent** : paquet `evalkit` (pas `eval`), commande `python -m evalkit.compare CONFIG` (pas `eval compare`), run = `config.yaml` + `metrics.json` + `outputs.jsonl` (pas de `manifest.json`/`predictions.jsonl`), config = dict YAML validé avec `common.config.merge_section`.

## Global Constraints

- `rag/` et `finetune/` n'importent jamais `evalkit/` ; seul `evalkit/compare.py` importe les deux (c'est le point d'assemblage, M4+ y brancheront de nouveaux systèmes sans toucher au reste).
- Contrat système inchangé : `answer(question) -> {"answer": str, "sources": list[str], ...}` ; clés optionnelles `retrieved`, `citations`, `invalid_citations` (M1). **`evalkit/harness.py` et `evalkit/metrics.py` ne sont pas modifiés.**
- Même jeu de questions, même graine (`mx.random.seed(cfg["seed"])` une fois), température de la config pour les quatre systèmes ; le modèle de base est `rag.generation.model` et `check_adapter` (M2) garantit que l'adaptateur correspond.
- Un run est immuable : `common.runs.new_run_dir` (suffixe `-2` en cas de collision).
- Jugement par **règles uniquement** (`answer_correct`, M0) en v1 ; le rapport l'écrit explicitement (PRD §8, risque du LLM juge). Pas de LLM juge en M3 (YAGNI : décidé après lecture du premier rapport).
- Messages en français ; clés de config et identifiants en anglais. Rapport lisible à 80 colonnes, aucune information portée par la seule couleur.
- Aucune donnée personnelle commitée : seuls les exemples synthétiques de `data/examples/` sont versionnés.
- Tests rapides sans modèle ; le test réel est marqué `slow` (déjà configuré dans `pyproject.toml`).

## Review Focus

- **Fuite d'évaluation** : une question du jeu de comparaison présente dans `train.jsonl` du fine-tuning rend `ft` meilleur « pour de mauvaises raisons » → avertissement en tête du rapport, listant les `id` (Task 4).
- **Écart de 1–2 questions sur 20–50** : jamais présenté comme un gain ; marqué « non concluant » sous `min_gap` questions, avec l'effectif `k/n` à côté de chaque pourcentage (Task 3).
- **Système sans RAG** : `recall@k` et fidélité affichés `—`, jamais `0` ni crash ; `citation_validity` à `None` (aucune citation) aussi `—` (Task 3).
- **Config incomplète ou fautive** : `systems` avec un nom inconnu ou un doublon, `ft` demandé sans `adapter`, adaptateur entraîné sur un autre modèle, index RAG périmé → échec **avant** le premier appel au modèle, message qui nomme la clé ou la commande à lancer (Tasks 1, 2).
- **Jeu de questions vide**, ou un seul système demandé : pas de division par zéro ; le rapport se génère sans section « verdict » comparative (Tasks 3, 4).

---

### Task 1: Configuration de comparaison et jeu d'exemple

**Files:**
- Create: `evalkit/compare.py` (config seulement dans cette tâche)
- Create: `configs/compare-example.yaml`, `data/examples/compare_eval.jsonl`
- Test: `tests/test_compare_config.py`

**Interfaces:**
- Produces: `evalkit.compare.SYSTEMS = ("base", "base+rag", "ft", "ft+rag")`.
- Produces: `evalkit.compare.compare_settings(cfg: dict) -> dict` — valide `cfg["compare"]` et renvoie la section complétée : `systems: list[str]` (défaut les 4), `adapter: str` (défaut `""`), `system_prompt: str` (défaut `""`), `train_file: str` (défaut `""`, active la détection de fuite), `min_gap: int` (défaut `2`, ≥ 1).
- Produces: `evalkit.compare.load_compare_config(path) -> dict` — `load_config` + `compare_settings` + `rag_settings` ; renvoie `cfg` avec `cfg["compare"]` et `cfg["rag"]` complétés ; exige `eval_set` (str). Les erreurs sont préfixées par le chemin du fichier.
- Consumes: `common.config.load_config`, `merge_section`, `is_int` ; `rag.config.rag_settings`.

- [ ] **Step 1: Écrire le jeu d'exemple** (questions répondables par `data/examples/docs/`, **absentes** de `data/examples/ft_source.jsonl`)

`data/examples/compare_eval.jsonl`
```jsonl
{"id": "c1", "question": "Quel est le plus grand océan du monde ?", "answer": "Pacifique", "sources": ["geo.md"]}
{"id": "c2", "question": "Quel rang utilise LoRA par défaut ?", "answer": "8", "sources": ["lora.md"]}
{"id": "c3", "question": "Comment le RAG fournit-il des passages au modèle ?", "answer": "index vectoriel", "sources": ["rag.md"]}
```
`c1` est volontairement différent de `rag_eval.jsonl` : « capitale de la France » figure déjà dans `ft_source.jsonl` (fuite). Invariant testé en Task 4 : aucune question de `compare_eval.jsonl` dans `ft_source.jsonl`. Nicolas remplacera ce jeu par un vrai jeu tenu à l'écart (voir « Étapes manuelles »).

- [ ] **Step 2: Écrire les tests qui échouent**

`tests/test_compare_config.py`
```python
import pytest

from evalkit.compare import SYSTEMS, compare_settings, load_compare_config
from fakes import make_cfg
from ft_fakes import write_cfg


def cfg_with(tmp_path, **compare):
    cfg = make_cfg(tmp_path)
    cfg.update(eval_set="data/examples/compare_eval.jsonl", compare=compare)
    return cfg


def test_defaults(tmp_path):
    c = compare_settings(cfg_with(tmp_path, adapter="runs/x/adapters"))
    assert c["systems"] == list(SYSTEMS) and c["min_gap"] == 2 and c["train_file"] == ""


@pytest.mark.parametrize(
    "compare, msg",
    [
        ({"systems": ["base", "gpt"], "adapter": "a"}, "compare.systems"),
        ({"systems": ["base", "base"]}, "compare.systems"),
        ({"systems": []}, "compare.systems"),
        ({"systems": ["ft"]}, "compare.adapter"),
        ({"systems": ["ft+rag"], "adapter": ""}, "compare.adapter"),
        ({"min_gap": 0, "adapter": "a"}, "compare.min_gap"),
        ({"adaptor": "a"}, "unknown key"),
    ],
)
def test_invalid(tmp_path, compare, msg):
    with pytest.raises(ValueError, match=msg):
        compare_settings(cfg_with(tmp_path, **compare))


def test_base_only_needs_no_adapter(tmp_path):
    assert compare_settings(cfg_with(tmp_path, systems=["base", "base+rag"]))["adapter"] == ""


def test_load_prefixes_path_and_requires_eval_set(tmp_path):
    cfg = cfg_with(tmp_path, systems=["ft"])
    path = write_cfg(tmp_path, cfg)
    with pytest.raises(ValueError, match=r"cfg\.yaml.*compare\.adapter"):
        load_compare_config(path)
    del cfg["eval_set"]
    cfg["compare"] = {"systems": ["base"]}
    with pytest.raises(ValueError, match="eval_set"):
        load_compare_config(write_cfg(tmp_path, cfg))
```

- [ ] **Step 3: Lancer pour voir l'échec**

Run: `uv run pytest tests/test_compare_config.py -v`
Expected: FAIL (`ModuleNotFoundError: evalkit.compare`).

- [ ] **Step 4: Implémenter**

`evalkit/compare.py`
```python
from common.config import is_int, load_config, merge_section
from rag.config import rag_settings

SYSTEMS = ("base", "base+rag", "ft", "ft+rag")
SCHEMA = {"systems": list(SYSTEMS), "adapter": "", "system_prompt": "", "train_file": "", "min_gap": 2}


def compare_settings(cfg):
    c = merge_section(SCHEMA, cfg.get("compare", {}), "compare")
    s = c["systems"]
    if not (isinstance(s, list) and s and len(set(s)) == len(s) and all(x in SYSTEMS for x in s)):
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
```

`configs/compare-example.yaml`
```yaml
name: compare-example
seed: 0
eval_set: data/examples/compare_eval.jsonl
compare:
  systems: [base, base+rag, ft, ft+rag]
  adapter: runs/CHANGE-ME/adapters        # produit par: uv run python -m finetune.train configs/ft-example.yaml
  system_prompt: ""                       # le même que finetune.system_prompt de l'entraînement
  train_file: data/train/ft-example/train.jsonl   # active l'alerte de fuite (questions déjà vues à l'entraînement)
  min_gap: 2
rag:
  docs_dir: data/examples/docs
  index_dir: data/index
  chunking: {size: 800, overlap: 100}
  embedding: {model: BAAI/bge-m3, batch_size: 16}
  retrieval: {k: 5}
  generation: {model: mlx-community/Qwen2.5-3B-Instruct-4bit, max_tokens: 400, temperature: 0.0}
```

- [ ] **Step 5: Vérifier, commiter**

Run: `uv run pytest tests/test_compare_config.py -v` → PASS.
```bash
git add evalkit/compare.py configs/compare-example.yaml data/examples/compare_eval.jsonl tests/test_compare_config.py
git commit -m "feat(compare): validated comparison config and example eval set"
```

---

### Task 2: Assemblage des quatre systèmes

**Files:**
- Modify: `evalkit/compare.py`
- Test: `tests/test_compare_build.py`

**Interfaces:**
- Consumes: `compare_settings` / config de la Task 1 ; `finetune.system.make_generator(s)` (`s = {"model", "adapter"}`, `adapter` vide = base) ; `rag.system.make_embedder(settings)` et `rag.system.RagSystem(index, embedder, generator, k, max_tokens, temperature)` ; `rag.index.open_index(settings, docs)` ; `rag.ingest.load_documents(dir)` ; `finetune.data.to_messages(question, system_prompt)`.
- Produces: `evalkit.compare.build_systems(cfg) -> dict[str, Callable]` — clés = `cfg["compare"]["systems"]` dans l'ordre. Charge les ressources **toutes d'abord** (échec précoce) : un `Generator` base si `base`/`base+rag`, un `Generator` adaptateur si `ft`/`ft+rag`, index + embedder si un `+rag`. Les systèmes sans RAG renvoient `{"answer": text, "sources": []}`.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/test_compare_build.py`
```python
import pytest

import finetune.system as ft_system
import rag.system as rag_system
from evalkit.compare import build_systems
from fakes import HashEmbedder, ScriptedGenerator, make_cfg
from rag.index import build_index
from rag.ingest import load_documents


def setup(tmp_path, monkeypatch, index=True, **compare):
    cfg = make_cfg(tmp_path)
    cfg["compare"] = {"adapter": "runs/x/adapters", **compare}
    from evalkit.compare import compare_settings
    from rag.config import rag_settings

    cfg["compare"], cfg["rag"] = compare_settings(cfg), rag_settings(cfg)
    if index:
        build_index(cfg["rag"], load_documents(cfg["rag"]["docs_dir"]), HashEmbedder())
    made = []
    gens = {"": ScriptedGenerator("base [1]"), "runs/x/adapters": ScriptedGenerator("ft [1]")}

    def fake_make_generator(s):
        made.append((s["model"], s["adapter"]))
        return gens[s["adapter"]]

    monkeypatch.setattr(ft_system, "make_generator", fake_make_generator)
    monkeypatch.setattr(rag_system, "make_embedder", lambda s: HashEmbedder())
    return cfg, gens, made


def test_four_systems_share_two_generators(tmp_path, monkeypatch):
    cfg, gens, made = setup(tmp_path, monkeypatch)
    systems = build_systems(cfg)
    assert list(systems) == ["base", "base+rag", "ft", "ft+rag"]
    assert made == [("fake", ""), ("fake", "runs/x/adapters")]  # un chargement par modèle, pas par système
    q = "Quelle est la capitale de la France ?"
    assert systems["base"](q) == {"answer": "base [1]", "sources": []}
    assert systems["ft"](q)["answer"] == "ft [1]"
    out = systems["base+rag"](q)
    assert out["retrieved"][0] == "geo.md" and out["sources"] == ["geo.md"]
    assert systems["ft+rag"](q)["answer"] == "ft [1]"
    assert len(gens[""].calls) == 2 and len(gens["runs/x/adapters"].calls) == 2


def test_plain_systems_use_the_training_system_prompt(tmp_path, monkeypatch):
    cfg, gens, _ = setup(tmp_path, monkeypatch, systems=["base"], system_prompt="Sois bref.")
    build_systems(cfg)["base"]("Q ?")
    assert gens[""].calls[0] == [{"role": "system", "content": "Sois bref."}, {"role": "user", "content": "Q ?"}]


def test_only_what_is_needed_is_loaded(tmp_path, monkeypatch):
    cfg, _, made = setup(tmp_path, monkeypatch, index=False, systems=["base"])
    build_systems(cfg)  # pas d'index requis, pas d'adaptateur chargé
    assert made == [("fake", "")]


def test_stale_index_fails_before_any_generation(tmp_path, monkeypatch):
    cfg, gens, _ = setup(tmp_path, monkeypatch, index=False, systems=["base+rag"])
    with pytest.raises(ValueError, match="rag.index"):
        build_systems(cfg)
    assert gens[""].calls == []
```

- [ ] **Step 2: Lancer pour voir l'échec**

Run: `uv run pytest tests/test_compare_build.py -v`
Expected: FAIL (`cannot import name 'build_systems'`).

- [ ] **Step 3: Implémenter** (ajouter à `evalkit/compare.py`)

```python
import finetune.system as ft_system
import rag.system as rag_system
from finetune.data import to_messages
from rag.index import open_index
from rag.ingest import load_documents


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
            systems[name] = rag_system.RagSystem(
                index, embedder, gen, r["retrieval"]["k"], g["max_tokens"], g["temperature"]
            )
        else:
            systems[name] = plain(gen)
    return systems
```
Déplacer les `import` en tête de fichier (groupés avec ceux de la Task 1).

Note de conception (à garder en commentaire d'une ligne dans le code) : `system_prompt` ne s'applique qu'aux systèmes sans RAG ; les `+rag` utilisent le prompt RAG de M1 (c'est un fait de comparaison, signalé dans le rapport, Task 3).

- [ ] **Step 4: Vérifier, commiter**

Run: `uv run pytest tests/test_compare_build.py tests/test_compare_config.py -v` → PASS.
```bash
git add evalkit/compare.py tests/test_compare_build.py
git commit -m "feat(compare): assemble base, base+rag, ft, ft+rag from shared generators"
```

---

### Task 3: Rendu du rapport (fonction pure)

**Files:**
- Create: `evalkit/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Produces: `evalkit.report.render_report(name, command, metrics, results, latency, min_gap, warnings=(), notes=()) -> str` où
  - `metrics: dict[str, dict]` — sortie de `evaluate` par système (clés `n`, `accuracy`, éventuellement `recall_at_k`, `citation_validity`) ; l'ordre du dict = ordre des lignes ; le **premier** système est la référence du verdict ;
  - `results: dict[str, list[dict]]` — lignes de `evaluate` par système (`id`, `question`, `expected`, `answer`, `correct`), alignées sur les mêmes questions ;
  - `latency: dict[str, float | None]` — secondes moyennes par question ;
  - `command: str` — commande exacte de reproduction ; `warnings` — lignes affichées en tête (fuite, etc.) ; `notes` — lignes de la section « Limites ».
- Produces: `evalkit.report.fmt_rate(correct: int, n: int) -> str` → `"0,62 (31/50)"` (virgule décimale, 2 décimales).
- Sections, dans l'ordre : `# Comparaison — <name>`, avertissements, `## Verdict`, `## Tableau`, `## Cas parlants`, `## Limites`, `## Reproduire`.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/test_report.py`
```python
from evalkit.report import fmt_rate, render_report


def rows(correct):
    return [
        {"id": f"q{i}", "question": f"Q{i} ?", "expected": "x", "answer": f"rép{i}", "correct": c}
        for i, c in enumerate(correct)
    ]


def make(base, rag, n_extra=0):
    results = {"base": rows(base), "base+rag": rows(rag)}
    metrics = {
        "base": {"n": len(base), "accuracy": sum(base) / len(base)},
        "base+rag": {"n": len(rag), "accuracy": sum(rag) / len(rag), "recall_at_k": 0.5, "citation_validity": None},
    }
    return metrics, results


def render(metrics, results, **kw):
    return render_report("t", "uv run python -m evalkit.compare c.yaml", metrics, results,
                         {"base": 1.234, "base+rag": None}, min_gap=kw.pop("min_gap", 2), **kw)


def test_fmt_rate():
    assert fmt_rate(31, 50) == "0,62 (31/50)"
    assert fmt_rate(0, 0) == "—"


def test_table_shows_counts_and_dashes_for_missing_metrics():
    metrics, results = make([True] * 3 + [False] * 7, [True] * 8 + [False] * 2)
    out = render(metrics, results)
    base_line = next(l for l in out.splitlines() if l.startswith("| base |"))
    assert "0,30 (3/10)" in base_line and base_line.count("—") >= 2 and "1,2 s" in base_line
    rag_line = next(l for l in out.splitlines() if l.startswith("| base+rag |"))
    assert "0,80 (8/10)" in rag_line and "0,50" in rag_line and "—" in rag_line  # latence et fidélité None


def test_verdict_flags_small_gaps_as_inconclusive():
    metrics, results = make([True] * 5 + [False] * 5, [True] * 6 + [False] * 4)  # +1 question, min_gap=2
    out = render(metrics, results)
    assert "non concluant" in out.split("## Tableau")[0]
    metrics, results = make([True] * 3 + [False] * 7, [True] * 8 + [False] * 2)  # +5 questions
    verdict = render(metrics, results).split("## Tableau")[0]
    assert "non concluant" not in verdict and "+50 points" in verdict


def test_judge_and_prompt_caveats_are_always_stated():
    out = render(*make([True, False], [True, True]))
    assert "règles" in out.split("## Limites")[1]


def test_cas_parlants_picks_questions_where_systems_disagree_and_skips_when_none():
    metrics, results = make([True, False, True, False], [True, True, True, True])
    out = render(metrics, results)
    parlants = out.split("## Cas parlants")[1].split("## Limites")[0]
    assert "Q1 ?" in parlants and "Q3 ?" in parlants and "Q0 ?" not in parlants
    metrics, results = make([True, True], [True, True])
    assert "Aucune divergence" in render(metrics, results).split("## Cas parlants")[1]


def test_warnings_come_first_and_single_system_has_no_comparative_verdict():
    metrics, results = make([True, False], [True, True])
    out = render(metrics, results, warnings=["Fuite : q1"])
    assert out.index("Fuite : q1") < out.index("## Verdict")
    one = render({"base": metrics["base"]}, {"base": results["base"]})
    assert "un seul système" in one.split("## Tableau")[0].lower()


def test_reproduction_command_is_verbatim():
    assert "uv run python -m evalkit.compare c.yaml" in render(*make([True], [True]))
```

- [ ] **Step 2: Lancer pour voir l'échec**

Run: `uv run pytest tests/test_report.py -v`
Expected: FAIL (`ModuleNotFoundError: evalkit.report`).

- [ ] **Step 3: Implémenter**

`evalkit/report.py`
```python
DASH = "—"


def fmt_rate(correct, n):
    return f"{correct / n:.2f} ({correct}/{n})".replace(".", ",") if n else DASH


def _ratio(v):
    return DASH if v is None else f"{v:.2f}".replace(".", ",")


def _seconds(v):
    return DASH if v is None else f"{v:.1f} s".replace(".", ",")


def _correct(m):
    return round(m["accuracy"] * m["n"])


def _verdict(metrics, min_gap):
    names = list(metrics)
    if len(names) < 2:
        return "Un seul système évalué : pas de comparaison."
    ref, parts = names[0], []
    for name in names[1:]:
        gap = _correct(metrics[name]) - _correct(metrics[ref])
        pts = round(100 * (metrics[name]["accuracy"] - metrics[ref]["accuracy"]))
        tail = " (écart non concluant)" if abs(gap) < min_gap else ""
        parts.append(f"{name} {pts:+d} points ({gap:+d} question(s)){tail}")
    n = metrics[ref]["n"]
    return f"Exactitude par rapport à `{ref}` sur {n} questions : " + " ; ".join(parts) + "."


def _divergent(results, limit=3):
    names = list(results)
    scored = []
    for i, base_row in enumerate(results[names[0]]):
        ok = [results[n][i]["correct"] for n in names]
        if 0 < sum(ok) < len(ok):
            scored.append((abs(sum(ok) - len(ok) / 2), i))  # plus proche d'un partage moitié/moitié d'abord
    return [i for _, i in sorted(scored)[:limit]]


def render_report(name, command, metrics, results, latency, min_gap, warnings=(), notes=()):
    out = [f"# Comparaison — {name}", ""]
    out += [f"> ⚠ {w}" for w in warnings] + ([""] if warnings else [])
    out += ["## Verdict", "", _verdict(metrics, min_gap), ""]
    out += ["## Tableau", "", "| Système | Exactitude | Recall@k | Fidélité | Latence |", "|---|---|---|---|---|"]
    for n, m in metrics.items():
        out.append(
            f"| {n} | {fmt_rate(_correct(m), m['n'])} | {_ratio(m.get('recall_at_k'))} "
            f"| {_ratio(m.get('citation_validity'))} | {_seconds(latency.get(n))} |"
        )
    out += ["", "## Cas parlants", ""]
    picks = _divergent(results)
    if not picks:
        out.append("Aucune divergence : tous les systèmes ont le même verdict sur chaque question.")
    for i in picks:
        first = results[next(iter(results))][i]
        out += [f"**{first['id']} — {first['question']}** (attendu : `{first['expected']}`)", ""]
        out += [f"- {n} {'✔' if results[n][i]['correct'] else '✘'} : {results[n][i]['answer']!r}" for n in results]
        out.append("")
    out += ["## Limites", ""]
    out += [
        "- Verdict fondé sur des **règles** (la réponse attendue figure dans la réponse), pas sur un LLM juge ; "
        "relire à la main un échantillon de `outputs.jsonl`.",
        "- Les systèmes `+rag` utilisent le prompt RAG (passages numérotés + citations) ; `system_prompt` ne "
        "s'applique qu'aux systèmes sans RAG.",
        f"- Un écart inférieur à {min_gap} question(s) n'est pas interprétable à cet effectif.",
        *[f"- {n}" for n in notes],
        "",
        "## Reproduire",
        "",
        f"```bash\n{command}\n```",
        "",
    ]
    return "\n".join(out)
```
Rappel : la ligne « Un seul système » du verdict doit contenir la sous-chaîne `un seul système` en minuscules après `.lower()` — c'est le cas (« Un seul système évalué »).

- [ ] **Step 4: Vérifier, commiter**

Run: `uv run pytest tests/test_report.py -v` → PASS.
```bash
git add evalkit/report.py tests/test_report.py
git commit -m "feat(report): four-system comparison report with counts and inconclusive gaps"
```

---

### Task 4: Exécution, sauvegarde du run, CLI, fuite d'évaluation

**Files:**
- Modify: `evalkit/compare.py`
- Modify: `tests/test_ft_smoke.py` (nouveau test `slow`) — ou Create: `tests/test_compare_smoke.py`
- Test: `tests/test_compare_run.py`

**Interfaces:**
- Consumes: `build_systems` (Task 2), `render_report` (Task 3), `evalkit.harness.evaluate`, `evalkit.metrics.normalize`, `common.jsonl.read_qa/read_jsonl/write_jsonl`, `common.runs.new_run_dir`.
- Produces: `leaked_ids(train_file: str, qa: list[dict]) -> list` — `id` des questions dont le texte normalisé figure comme message `user` dans `train_file` (format `{"messages": [...]}` de `finetune.prepare`) ; `[]` si `train_file` vide.
- Produces: `run_compare(systems, qa) -> (metrics, results, latency)` — dicts par système, mêmes clés/ordre que `systems` ; `latency[name]` = moyenne des `time.perf_counter()` autour de chaque appel.
- Produces: `main(argv) -> dict` — `python -m evalkit.compare CONFIG`. Écrit dans `runs/<date>-<name>/` : `config.yaml` (copie), `metrics.json` = `{"systems": {name: metrics + latency_s}, "manifest": {...}}`, `outputs.jsonl` (une ligne par couple système × question : `{"system": name, **row}`), `report.md`. `manifest` : `eval_set_sha256`, `base_model`, `adapter_config_sha256` et `ft_data_sha256` (lu dans `<dossier de l'adaptateur>/../metrics.json` s'il existe, sinon `None`), `index_key` si RAG. Affiche le rapport et `run saved to <dir>`.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/test_compare_run.py`
```python
import json

import pytest

import evalkit.compare as cmp
from common.jsonl import read_jsonl, read_qa, write_jsonl
from evalkit.compare import leaked_ids, main, run_compare
from fakes import make_cfg
from ft_fakes import write_cfg

QA = [
    {"id": "a", "question": "Capitale de la France ?", "answer": "Paris", "sources": ["geo.md"]},
    {"id": "b", "question": "Rang LoRA ?", "answer": "8", "sources": []},
]


def test_leak_detection_is_normalized_and_optional(tmp_path):
    train = tmp_path / "train.jsonl"
    write_jsonl(train, [{"messages": [{"role": "user", "content": "  capitale de la FRANCE ? "},
                                       {"role": "assistant", "content": "Paris"}]}])
    assert leaked_ids(str(train), QA) == ["a"]
    assert leaked_ids("", QA) == []


def test_example_eval_set_does_not_leak_into_example_ft_source():
    qs = {r["question"] for r in read_qa("data/examples/compare_eval.jsonl")}
    assert not qs & {r["question"] for r in read_qa("data/examples/ft_source.jsonl")}


def test_run_compare_measures_latency_and_keeps_order():
    systems = {
        "x": lambda q: {"answer": "Paris" if "France" in q else "?", "sources": []},
        "y": lambda q: {"answer": "Paris 8", "sources": []},
    }
    metrics, results, latency = run_compare(systems, QA)
    assert list(metrics) == ["x", "y"] and metrics["x"]["accuracy"] == 0.5 and metrics["y"]["accuracy"] == 1.0
    assert all(latency[n] >= 0 for n in systems) and len(results["x"]) == 2


def test_main_writes_an_immutable_run_with_report_and_manifest(tmp_path, monkeypatch, capsys):
    cfg = make_cfg(tmp_path)
    eval_path = tmp_path / "eval.jsonl"
    write_jsonl(eval_path, QA)
    adapter = tmp_path / "ftrun" / "adapters"
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text(json.dumps({"model": "fake"}), encoding="utf-8")
    (tmp_path / "ftrun" / "metrics.json").write_text(json.dumps({"data_sha256": "abc"}), encoding="utf-8")
    cfg.update(eval_set=str(eval_path), runs_dir=str(tmp_path / "runs"),
               compare={"systems": ["base", "ft"], "adapter": str(adapter)})
    monkeypatch.setattr(cmp, "build_systems", lambda c: {
        "base": lambda q: {"answer": "Paris", "sources": []},
        "ft": lambda q: {"answer": "Paris 8", "sources": []}})
    path = write_cfg(tmp_path, cfg)
    main([str(path)])
    main([str(path)])  # deuxième run le même jour: nouveau dossier, jamais d'écrasement
    runs = sorted((tmp_path / "runs").iterdir())
    assert len(runs) == 2 and runs[1].name.endswith("-2")
    run = runs[0]
    assert {p.name for p in run.iterdir()} == {"config.yaml", "metrics.json", "outputs.jsonl", "report.md"}
    m = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    assert m["systems"]["ft"]["accuracy"] == 1.0 and m["systems"]["base"]["accuracy"] == 0.5
    assert m["manifest"]["ft_data_sha256"] == "abc" and m["manifest"]["base_model"] == "fake"
    assert len(m["manifest"]["eval_set_sha256"]) == 64 and len(m["manifest"]["adapter_config_sha256"]) == 64
    assert len(read_jsonl(run / "outputs.jsonl")) == 4
    assert "## Verdict" in (run / "report.md").read_text(encoding="utf-8")
    assert "run saved to" in capsys.readouterr().out


def test_main_reports_leaks_and_rejects_empty_eval(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    eval_path, train = tmp_path / "eval.jsonl", tmp_path / "train.jsonl"
    write_jsonl(eval_path, QA)
    write_jsonl(train, [{"messages": [{"role": "user", "content": "Rang LoRA ?"}]}])
    cfg.update(eval_set=str(eval_path), runs_dir=str(tmp_path / "runs"),
               compare={"systems": ["base"], "train_file": str(train)})
    monkeypatch.setattr(cmp, "build_systems", lambda c: {"base": lambda q: {"answer": "Paris", "sources": []}})
    main([str(write_cfg(tmp_path, cfg))])
    report = (next((tmp_path / "runs").iterdir()) / "report.md").read_text(encoding="utf-8")
    assert "b" in report.split("## Verdict")[0] and "entraînement" in report.split("## Verdict")[0]

    write_jsonl(eval_path, [])
    with pytest.raises(ValueError, match="empty"):
        main([str(write_cfg(tmp_path, cfg))])
```

- [ ] **Step 2: Lancer pour voir l'échec**

Run: `uv run pytest tests/test_compare_run.py -v`
Expected: FAIL (`cannot import name 'leaked_ids'`).

- [ ] **Step 3: Implémenter** (ajouter à `evalkit/compare.py` ; imports en tête)

```python
import hashlib
import json
import random
import shlex
import sys
import time
from pathlib import Path

import yaml

from common.jsonl import read_jsonl, read_qa, write_jsonl
from common.runs import new_run_dir
from evalkit.harness import evaluate
from evalkit.metrics import normalize
from evalkit.report import render_report
from rag.index import index_key


def leaked_ids(train_file, qa):
    """Questions d'évaluation déjà vues à l'entraînement : elles avantageraient `ft` pour de mauvaises raisons."""
    if not train_file:
        return []
    seen = {
        normalize(m["content"])
        for row in read_jsonl(train_file)
        for m in row.get("messages", [])
        if m.get("role") == "user"
    }
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
        m["adapter_config_sha256"] = _sha256(Path(c["adapter"]) / "adapter_config.json")
        train_metrics = Path(c["adapter"]).parent / "metrics.json"  # écrit par finetune.train
        if train_metrics.is_file():
            m["ft_data_sha256"] = json.loads(train_metrics.read_text(encoding="utf-8")).get("data_sha256")
    if any(x.endswith("+rag") for x in c["systems"]):
        m["index_key"] = index_key(r, load_documents(r["docs_dir"]))
    return m


def main(argv):
    cfg = load_compare_config(argv[0])
    qa = read_qa(cfg["eval_set"])
    if not qa:
        raise ValueError(f"{cfg['eval_set']}: eval set is empty")
    manifest = _manifest(cfg)  # avant build_systems : un adaptateur illisible échoue sans charger de modèle
    random.seed(cfg["seed"])
    import mlx.core as mx

    mx.random.seed(cfg["seed"])
    systems = build_systems(cfg)
    metrics, results, latency = run_compare(systems, qa)
    leaks = leaked_ids(cfg["compare"]["train_file"], qa)
    warnings = [f"Fuite d'évaluation : {len(leaks)} question(s) vue(s) à l'entraînement ({', '.join(map(str, leaks))}) ; "
                "les résultats de `ft` sont optimistes."] if leaks else []
    notes = [] if cfg["compare"]["train_file"] else ["Aucune détection de fuite (`compare.train_file` non renseigné)."]
    command = f"uv run python -m evalkit.compare {shlex.quote(argv[0])}"
    run_dir = new_run_dir(cfg["name"], cfg.get("runs_dir", "runs"))
    report = render_report(cfg["name"], command, metrics, results, latency, cfg["compare"]["min_gap"], warnings, notes)
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
```
Note pour l'implémenteur : le test `test_main_*` remplace `build_systems` par un faux ; `import mlx.core` y est quand même exécuté (Apple Silicon, dépendance déjà installée par `mlx-lm`). Si l'import pose problème en CI, le mettre derrière `try/except ImportError` — pas avant d'avoir vu l'erreur.

- [ ] **Step 4: Test de fumée `slow` (vrais modèles, minuscule)**

`tests/test_compare_smoke.py` — calquer sur `tests/test_ft_smoke.py` (lire ce fichier d'abord pour réutiliser son modèle minuscule et sa fabrique d'adaptateur) : entraîner 5–10 itérations, puis `main()` sur une config à `systems: [base, ft]` (pas de RAG : évite de télécharger bge-m3), et vérifier que `report.md` existe avec les deux lignes de tableau. Marqueur `@pytest.mark.slow`.

Run: `uv run pytest tests/test_compare_smoke.py -m slow -v` → PASS (si le modèle minuscule n'est pas disponible hors ligne, le noter et laisser l'étape à Nicolas, comme M2).

- [ ] **Step 5: Tout vérifier, commiter**

Run: `uv run pytest -q` → tous les tests rapides passent (≈ 142 existants + ~25 nouveaux).
```bash
git add evalkit/compare.py tests/test_compare_run.py tests/test_compare_smoke.py
git commit -m "feat(compare): one-command four-system run with report, manifest and leak warning"
```

---

## Étapes manuelles (Nicolas, après la Task 4)

1. Écrire un **vrai jeu tenu à l'écart** (20–50 questions) mélangeant faits des documents (où le RAG doit gagner) et questions de format/tâche (où le fine-tuning doit aider) ; ne pas le mettre dans `ft_source.jsonl`.
2. `uv run python -m rag.index configs/compare.yaml` (index à jour), `uv run python -m finetune.train <config ft>` ; reporter le chemin `runs/<…>/adapters` dans `compare.adapter` et le `system_prompt` d'entraînement.
3. `uv run python -m evalkit.compare configs/compare.yaml`, lire `report.md`, relire à la main ~10 lignes de `outputs.jsonl` (juge = règles).
4. Décider M4+ selon le verdict (PRD §5) : recall bas → hybride/reranking ; fine-tuning sans effet sur les faits → attendu (PRD §8).

## Hors périmètre (YAGNI, à rouvrir si le besoin apparaît)

- `eval report runs/A runs/B …` sur des runs existants et `eval replay` : la commande unique couvre le critère M3 ; un run `compare` contient déjà config + empreintes pour être rejoué à la main.
- LLM juge, intervalles de confiance, mémoire pic par système, graphiques : le tableau `k/n` + seuil `min_gap` suffit à 20–50 questions.
- Prompt RAG adapté au format fine-tuné pour `ft+rag` : un `ft` entraîné au format « Réponse : X. » verra le prompt RAG de M1 ; si `ft+rag` déçoit, c'est la première piste (signalé dans « Limites » du rapport).

## Self-Review

- **Couverture du spec** : F14 / critère M3 (« une commande, un tableau reproductible ») → Tasks 2–4 ; structure UX §6.3 (verdict, tableau avec `k/n`, non concluant, cas parlants, reproduction, part du juge) → Task 3 ; comparabilité des empreintes (TRD §11) → `manifest` Task 4 + même `eval_set_sha256` pour tous les systèmes par construction ; risque « juge » → section Limites. Écarts assumés : pas de colonne mémoire, pas de lien vers un échantillon à relire (instruction manuelle à la place).
- **Placeholders** : aucun ; seule consigne à compléter à l'exécution : le modèle minuscule du smoke test (à lire dans `test_ft_smoke.py`).
- **Cohérence des types** : `build_systems(cfg) -> dict` (Task 2) consommé par `run_compare(systems, qa)` ; `render_report(name, command, metrics, results, latency, min_gap, warnings, notes)` appelé avec les mêmes noms en Task 4 ; `compare_settings`/`load_compare_config` (Task 1) fournissent `cfg["compare"]` et `cfg["rag"]` lus partout.
