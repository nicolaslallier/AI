# M4 — Variantes de récupération (hybride + reranking) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Brancher la recherche hybride (dense + BM25/FTS fusionnés par RRF) et le reranking (cross-encoder) derrière le contrat existant du RAG, et pouvoir mesurer leur recall@k **sans LLM** pour décider si ça vaut le coup.

**Architecture:** Un nouveau module `rag/retrieve.py` porte `rrf`, `CrossEncoderReranker` et `Retriever` (`retriever(query) -> list[passage]`). `RagSystem` l'appelle à la place de `index.search(...)` ; `Answer` ne change pas, donc harnais, `rag.ask` et M3 (`compare`) continuent de fonctionner. Un index LanceDB reçoit toujours un index plein texte (FTS) à la construction. Une commande `rag.recall` compare les modes `dense / hybrid / ±rerank` sur le jeu d'évaluation en ne chargeant que l'embedder et le reranker.

**Tech Stack:** LanceDB 0.40 (FTS natif, `create_fts_index(..., use_tantivy=False, language="French")`), `sentence-transformers` (`CrossEncoder`, déjà installé), pytest. **Aucune nouvelle dépendance.**

**Spec:** `docs/TRD.md` §6.2 « Récupération (F7) » (« `hybrid` … et `rerank` … en M4, derrière la même interface »), `docs/PRD.md` §7 (M4+), `docs/APPFLOW.md` l.195 et l.210. Dépend de **M3** (`evalkit/compare.py`, PR #9) : brancher cette branche sur `main` **après** le merge de #9, ou rebaser dessus.

## Global Constraints

- Python 3.12, `uv` ; pas de nouvelle dépendance (`pyproject.toml` inchangé).
- Même interface : l'étape de récupération renvoie des passages `{id, doc_id, text, start, end, score}` triés par score décroissant, au plus `k`.
- Les clés de config inconnues échouent tôt (`rag.config._merge`) ; les défauts conservent le comportement M1 (`mode: dense`, pas de reranker).
- Un changement qui rend un index existant incompatible doit échouer **clairement** avec la commande à lancer (TRD F9), jamais silencieusement.
- Tests rapides sans modèle (fakes de `tests/fakes.py`) ; un seul test réel marqué `slow`, comme M2.
- Hors périmètre (YAGNI) : LLM juge, modèle 7–8B (= changer `rag.generation.model` dans le YAML, zéro code), nouvelles tâches de fine-tuning, seuil « rien trouvé », `--show-context`.

## Review Focus

- Requête composée uniquement de mots vides ou vide (« la de ») : FTS renvoie `[]` → `hybrid` doit retomber sur le dense, pas planter ni renvoyer 0 passage.
- Requête avec caractères spéciaux (`"`, `:`, `*`, `-`, parenthèses) : ne doit jamais lever d'exception côté FTS.
- Moins de `candidates` chunks dans l'index, ou `candidates < k` : `k` plus grand que le nombre de chunks ne doit pas planter ; `candidates < k` est refusé à la validation de config.
- Même chunk remonté par le dense et le FTS : un seul passage (pas de doublon dans le prompt, numérotation `[n]` intacte).
- Ancien index (M1, sans FTS) rouvert en mode `hybrid` : erreur claire nommant `rag.index`, pas un crash LanceDB.

---

## File Structure

| Fichier | Rôle |
|---|---|
| `rag/config.py` (modif) | clés `retrieval.mode`, `retrieval.candidates`, `retrieval.rerank` + validation |
| `rag/index.py` (modif) | FTS construit avec l'index, `fts` dans `index_key`, `Index.search_text` |
| `rag/retrieve.py` (nouveau) | `rrf`, `CrossEncoderReranker`, `Retriever`, `make_retriever` |
| `rag/system.py` (modif) | `RagSystem` utilise un `Retriever` ; `build` le construit |
| `evalkit/compare.py` (modif, M3) | `build_systems` passe le même retriever aux systèmes `+rag` |
| `rag/recall.py` (nouveau) | commande `python -m rag.recall CONFIG` : recall@k par mode |
| `configs/rag-hybrid.yaml` (nouveau) | exemple hybride + rerank |
| `tests/fakes.py` (modif) | `OverlapReranker` |
| `tests/test_rag_config.py`, `test_index.py`, `test_retrieve.py`, `test_rag_system.py`, `test_recall.py` | tests |

---

### Task 1: Config de récupération

**Files:**
- Modify: `rag/config.py` (SCHEMA l.9, validation l.45-46)
- Test: `tests/test_rag_config.py`

**Interfaces:**
- Produces: `rag_settings(cfg)["retrieval"] == {"mode": "dense"|"hybrid", "k": int, "candidates": int, "rerank": str}` (`rerank == ""` = pas de reranker). Défauts : `mode="dense"`, `k=5`, `candidates=20`, `rerank=""`.

- [ ] **Step 1: Write the failing tests** (ajouter à `tests/test_rag_config.py`; réutilise les imports existants du fichier, ajouter `from fakes import make_cfg` si absent)

```python
import pytest

from fakes import make_cfg
from rag.config import rag_settings


def test_retrieval_defaults_keep_m1_behaviour(tmp_path):
    r = rag_settings(make_cfg(tmp_path))["retrieval"]
    assert r == {"mode": "dense", "k": 2, "candidates": 20, "rerank": ""}


@pytest.mark.parametrize(
    "retrieval, msg",
    [
        ({"mode": "bm25"}, "rag.retrieval.mode"),
        ({"k": 5, "candidates": 3}, "candidates"),
        ({"candidates": 0}, "candidates"),
        ({"rerank": 3}, "rag.retrieval.rerank"),
    ],
)
def test_retrieval_rejects_bad_values(tmp_path, retrieval, msg):
    with pytest.raises(ValueError, match=msg):
        rag_settings(make_cfg(tmp_path, retrieval=retrieval))


def test_hybrid_and_rerank_are_accepted(tmp_path):
    r = rag_settings(make_cfg(tmp_path, retrieval={"k": 3, "mode": "hybrid", "rerank": "some/model"}))["retrieval"]
    assert (r["mode"], r["rerank"], r["candidates"]) == ("hybrid", "some/model", 20)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_rag_config.py -q`
Expected: FAIL (`unknown key(s) in 'rag.retrieval'`).

- [ ] **Step 3: Implement** — dans `rag/config.py` remplacer la ligne `"retrieval": {"k": 5},` par :

```python
    "retrieval": {"mode": "dense", "k": 5, "candidates": 20, "rerank": ""},
```

et, après la validation de `k`, ajouter :

```python
    r = s["retrieval"]
    if r["mode"] not in ("dense", "hybrid"):
        raise ValueError("rag.retrieval.mode must be 'dense' or 'hybrid'")
    if not isinstance(r["rerank"], str):
        raise ValueError("rag.retrieval.rerank must be a string (model id, or '' for none)")
    if not (_is_int(r["candidates"]) and r["candidates"] >= r["k"]):
        raise ValueError("rag.retrieval.candidates must be an integer >= k")
```

(Le test `({"candidates": 0}, ...)` passe car `0 < k`.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_rag_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rag/config.py tests/test_rag_config.py
git commit -m "feat(rag): retrieval.mode/candidates/rerank config keys"
```

---

### Task 2: Index plein texte (FTS)

**Files:**
- Modify: `rag/index.py` (`index_key`, `build_index`, `Index`)
- Test: `tests/test_index.py`

**Interfaces:**
- Consumes: `rag_settings` (Task 1 non requis ici).
- Produces: `Index.search_text(query: str, n: int) -> list[passage]` — même forme que `Index.search` (`id, doc_id, text, start, end, score`), `score` = score BM25, `[]` si aucun mot ne correspond. Les index existants ont un autre `index_key` (clé `fts` ajoutée) → `open_index` échoue avec le message `rag.index` existant et force la réindexation.

- [ ] **Step 1: Write the failing tests** (ajouter à `tests/test_index.py`)

```python
def test_search_text_is_lexical_and_french_stemmed(setup):
    s, docs = setup
    build_index(s, docs, HashEmbedder())
    hits = open_index(s, docs).search_text("capitales de France", 3)
    assert hits and hits[0]["doc_id"] == "geo.md"
    assert {"id", "text", "start", "end", "score"} <= set(hits[0])


@pytest.mark.parametrize("q", ["", "la de", '"capitale', "(a OR b) AND:", "C++ -France", "capitale:*"])
def test_search_text_never_raises(setup, q):
    s, docs = setup
    build_index(s, docs, HashEmbedder())
    assert isinstance(open_index(s, docs).search_text(q, 3), list)


def test_search_text_n_larger_than_corpus(setup):
    s, docs = setup
    build_index(s, docs, HashEmbedder())
    assert len(open_index(s, docs).search_text("France", 1000)) <= 1000
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_index.py -q`
Expected: FAIL (`AttributeError: 'Index' object has no attribute 'search_text'`).

- [ ] **Step 3: Implement** — dans `rag/index.py` :

`index_key` : ajouter `"fts": "french-v1",` dans le dict `payload` (invalide les index M1 ; changer la valeur si les paramètres FTS changent).

`build_index` : remplacer l'unique ligne `lancedb.connect(str(tmp)).create_table(...)` par

```python
    table = lancedb.connect(str(tmp)).create_table(TABLE, data=[{**ch, "vector": v} for ch, v in zip(chunks, vectors)])
    table.create_fts_index("text", use_tantivy=False, language="French", replace=True)
```

`Index` : factoriser la conversion de ligne et ajouter la recherche texte :

```python
_FIELDS = ("id", "doc_id", "text", "start", "end")


class Index:
    def __init__(self, path):
        self._table = lancedb.connect(str(path)).open_table(TABLE)

    def search(self, query_vec, k):
        rows = self._table.search(query_vec).metric("cosine").limit(k).to_list()
        return [{**{f: r[f] for f in _FIELDS}, "score": 1.0 - r["_distance"]} for r in rows]

    def search_text(self, query, n):
        rows = self._table.search(query, query_type="fts").limit(n).to_list()
        return [{**{f: r[f] for f in _FIELDS}, "score": r["_score"]} for r in rows]
```

(`create_fts_index` émet un `DeprecatedWarning` en 0.40 ; l'alternative `create_index(config=FTS(...))` n'a pas été vérifiée — ne migrer que si le warning gêne.)

- [ ] **Step 4: Run to verify pass (tout le fichier : la clé a changé)**

Run: `uv run pytest tests/test_index.py tests/test_rag_system.py tests/test_ask.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rag/index.py tests/test_index.py
git commit -m "feat(rag): build a French FTS index alongside vectors; Index.search_text"
```

---

### Task 3: `Retriever` (RRF + rerank) branché dans `RagSystem`

**Files:**
- Create: `rag/retrieve.py`
- Modify: `rag/system.py`, `tests/fakes.py`, `evalkit/compare.py` (`build_systems`, branche M3)
- Test: `tests/test_retrieve.py`, `tests/test_rag_system.py`

**Interfaces:**
- Consumes: `Index.search`, `Index.search_text` (Task 2) ; `rag_settings(...)["retrieval"]` (Task 1).
- Produces:
  - `rrf(rankings: list[list[str]], c: int = 60) -> list[tuple[str, float]]` — ids triés par score RRF décroissant (égalité : ordre d'apparition).
  - `CrossEncoderReranker(model: str)` avec `.score(query: str, texts: list[str]) -> list[float]`.
  - `Retriever(index, embedder, mode: str, k: int, candidates: int, reranker=None)`, appelable : `retriever(query) -> list[passage]` (≤ k, score décroissant, ids uniques).
  - `make_retriever(settings, index, embedder) -> Retriever` (instancie `CrossEncoderReranker` si `retrieval.rerank` non vide).
  - `RagSystem(index, embedder, generator, k, max_tokens, temperature, retriever=None)` — `retriever` défaut = `Retriever(index, embedder, "dense", k, k)` : les appelants M1/M3 existants ne cassent pas.
  - `tests/fakes.py::OverlapReranker` avec `.score(query, texts)` = nombre de mots de `query` présents dans chaque texte.

- [ ] **Step 1: Write the failing tests** — `tests/test_retrieve.py`

```python
import pytest

from fakes import HashEmbedder, OverlapReranker, make_cfg
from rag.config import rag_settings
from rag.index import build_index, open_index
from rag.ingest import load_documents
from rag.retrieve import Retriever, rrf


def test_rrf_orders_by_fused_rank_and_dedups():
    out = rrf([["a", "b", "c"], ["b", "d"]])
    assert [i for i, _ in out] == ["b", "a", "d", "c"]
    assert len({i for i, _ in out}) == 4
    assert out[0][1] > out[1][1]


def test_rrf_empty_ranking_is_identity():
    assert [i for i, _ in rrf([["a", "b"], []])] == ["a", "b"]
    assert rrf([[], []]) == []


@pytest.fixture
def idx(tmp_path):
    s = rag_settings(make_cfg(tmp_path))
    docs = load_documents(s["docs_dir"])
    build_index(s, docs, HashEmbedder())
    return open_index(s, docs), HashEmbedder()


def test_dense_mode_matches_index_search(idx):
    index, emb = idx
    got = Retriever(index, emb, "dense", 2, 2)("capitale de la France")
    assert [p["id"] for p in got] == [p["id"] for p in index.search(emb.embed_query("capitale de la France"), 2)]


def test_hybrid_has_unique_ids_and_at_most_k(idx):
    index, emb = idx
    got = Retriever(index, emb, "hybrid", 3, 10)("capitale de la France")
    ids = [p["id"] for p in got]
    assert len(ids) == len(set(ids)) and len(ids) <= 3
    assert [p["score"] for p in got] == sorted((p["score"] for p in got), reverse=True)


@pytest.mark.parametrize("q", ["la de", "", '"(:*'])
def test_hybrid_falls_back_to_dense_when_fts_is_empty(idx, q):
    index, emb = idx
    got = Retriever(index, emb, "hybrid", 2, 10)(q)
    assert len(got) == 2  # le dense répond toujours


def test_k_larger_than_corpus_does_not_crash(idx):
    index, emb = idx
    assert Retriever(index, emb, "hybrid", 500, 500)("France")


def test_rerank_reorders_and_replaces_score(idx):
    index, emb = idx
    q = "capitale de la France"
    got = Retriever(index, emb, "dense", 2, 10, reranker=OverlapReranker())(q)
    assert len(got) == 2
    assert got[0]["score"] >= got[1]["score"]
    texts = [p["text"] for p in got]
    assert OverlapReranker().score(q, texts) == [p["score"] for p in got]
```

Ajouter à `tests/fakes.py` :

```python
class OverlapReranker:
    """Score = nombre de mots de la requête présents dans le texte. Déterministe, sans modèle."""

    def score(self, query, texts):
        q = set(re.findall(r"\w+", query.casefold()))
        return [float(len(q & set(re.findall(r"\w+", t.casefold())))) for t in texts]
```

Ajouter à `tests/test_rag_system.py` :

```python
def test_hybrid_rerank_system_keeps_answer_contract(tmp_path, monkeypatch):
    cfg, _ = prepare(tmp_path, monkeypatch)
    cfg["rag"]["retrieval"] = {"k": 2, "mode": "hybrid", "rerank": "fake"}
    s = rag_settings(cfg)
    build_index(s, load_documents(s["docs_dir"]), HashEmbedder())
    from fakes import OverlapReranker
    monkeypatch.setattr("rag.retrieve.CrossEncoderReranker", lambda model: OverlapReranker())
    out = rs.build(cfg)("Quelle est la capitale de la France ?")
    assert len(out["retrieved"]) == 2 and out["sources"] == ["geo.md"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_retrieve.py tests/test_rag_system.py -q`
Expected: FAIL (`ModuleNotFoundError: rag.retrieve`).

- [ ] **Step 3: Implement** — `rag/retrieve.py`

```python
def rrf(rankings, c=60):
    """Reciprocal Rank Fusion : score(id) = somme de 1 / (c + rang). Ne dépend pas de l'échelle des scores."""
    scores = {}
    for ranking in rankings:
        for rank, id_ in enumerate(ranking, 1):
            scores[id_] = scores.get(id_, 0.0) + 1.0 / (c + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])  # tri stable : égalité = ordre d'apparition


class CrossEncoderReranker:
    def __init__(self, model):
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model)

    def score(self, query, texts):
        return [float(s) for s in self._model.predict([(query, t) for t in texts], show_progress_bar=False)]


class Retriever:
    """dense | hybrid (dense + FTS par RRF), puis reranking optionnel des `candidates` premiers → top-k."""

    def __init__(self, index, embedder, mode, k, candidates, reranker=None):
        self.index, self.embedder, self.mode = index, embedder, mode
        self.k, self.candidates, self.reranker = k, candidates, reranker

    def __call__(self, query):
        n = self.candidates if (self.mode == "hybrid" or self.reranker) else self.k
        passages = self.index.search(self.embedder.embed_query(query), n)
        if self.mode == "hybrid":
            lexical = self.index.search_text(query, n)  # [] si requête vide / mots vides → retombe sur le dense
            by_id = {p["id"]: p for p in lexical} | {p["id"]: p for p in passages}
            passages = [
                {**by_id[i], "score": s} for i, s in rrf([[p["id"] for p in passages], [p["id"] for p in lexical]])
            ]
        if self.reranker:
            scores = self.reranker.score(query, [p["text"] for p in passages])
            passages = sorted(({**p, "score": s} for p, s in zip(passages, scores)), key=lambda p: -p["score"])
        return passages[: self.k]


def make_retriever(settings, index, embedder):
    r = settings["retrieval"]
    reranker = CrossEncoderReranker(r["rerank"]) if r["rerank"] else None
    return Retriever(index, embedder, r["mode"], r["k"], r["candidates"], reranker)
```

`rag/system.py` — import et `RagSystem` :

```python
from rag.retrieve import Retriever, make_retriever
```

```python
class RagSystem:
    def __init__(self, index, embedder, generator, k, max_tokens, temperature, retriever=None):
        self.index, self.embedder, self.generator = index, embedder, generator
        self.k, self.max_tokens, self.temperature = k, max_tokens, temperature
        self.retriever = retriever or Retriever(index, embedder, "dense", k, k)

    def __call__(self, question):
        passages = self.retriever(question)
```

(supprimer l'ancienne ligne `passages = self.index.search(...)`). Dans `build`, construire l'embedder une fois :

```python
    index = open_index(s, load_documents(s["docs_dir"]))
    embedder = make_embedder(s)
    g = s["generation"]
    return RagSystem(index, embedder, make_generator(s), s["retrieval"]["k"], g["max_tokens"], g["temperature"],
                     retriever=make_retriever(s, index, embedder))
```

`make_retriever` appelle `CrossEncoderReranker` via le module `rag.retrieve` ; le test le remplace en patchant `rag.retrieve.CrossEncoderReranker`. `evalkit/compare.py::build_systems` : dans la branche `+rag`, passer `retriever=rag_system.make_retriever(r, index, embedder)` (construit **une fois** avant la boucle, à côté de `index`/`embedder`, pour que `base+rag` et `ft+rag` partagent le reranker en mémoire) ; adapter les fakes de `tests/test_compare_build.py` si elles monkeypatchent `RagSystem`.

- [ ] **Step 4: Run to verify pass (suite complète)**

Run: `uv run pytest -q`
Expected: PASS (suite M3 incluse).

- [ ] **Step 5: Commit**

```bash
git add rag/retrieve.py rag/system.py evalkit/compare.py tests
git commit -m "feat(rag): hybrid (RRF) and cross-encoder rerank behind the retriever interface"
```

---

### Task 4: `rag.recall` — comparer les modes sans LLM

**Files:**
- Create: `rag/recall.py`, `configs/rag-hybrid.yaml`
- Test: `tests/test_recall.py`

**Interfaces:**
- Consumes: `Retriever`, `make_retriever` (Task 3), `rag.index.open_index`, `common.jsonl.read_qa`, `evalkit.metrics.source_hit`.
- Produces: `recall_table(qa, retrievers: dict[str, callable]) -> dict[str, float | None]` (nom → recall@k sur les questions qui ont des sources attendues ; `None` si aucune) ; CLI `uv run python -m rag.recall CONFIG` qui affiche un tableau Markdown pour `dense`, `hybrid`, et, si `retrieval.rerank` est défini, `dense+rerank`, `hybrid+rerank`.

- [ ] **Step 1: Write the failing test** — `tests/test_recall.py`

```python
from rag.recall import recall_table

QA = [
    {"id": "1", "question": "q1", "answer": "x", "sources": ["a.md"]},
    {"id": "2", "question": "q2", "answer": "x", "sources": ["b.md"]},
    {"id": "3", "question": "q3", "answer": "x", "sources": []},  # sans source attendue : ignorée
]


def fake(mapping):
    return lambda q: [{"doc_id": d} for d in mapping[q]]


def test_recall_table_counts_only_questions_with_sources():
    r = recall_table(QA, {"good": fake({"q1": ["a.md"], "q2": ["b.md"], "q3": []}),
                          "half": fake({"q1": ["a.md"], "q2": ["z.md"], "q3": []})})
    assert r == {"good": 1.0, "half": 0.5}


def test_recall_table_none_when_no_expected_sources():
    assert recall_table(QA[2:], {"x": fake({"q3": []})}) == {"x": None}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_recall.py -q`
Expected: FAIL (`ModuleNotFoundError: rag.recall`).

- [ ] **Step 3: Implement** — `rag/recall.py`

```python
import argparse

from common.jsonl import read_qa
from evalkit.metrics import source_hit
from rag.config import load_rag_config
from rag.index import open_index
from rag.ingest import load_documents
from rag.retrieve import CrossEncoderReranker, Retriever


def recall_table(qa, retrievers):
    rows = [r for r in qa if r["sources"]]
    return {
        name: (sum(source_hit([p["doc_id"] for p in ret(r["question"])], r["sources"]) for r in rows) / len(rows)
               if rows else None)
        for name, ret in retrievers.items()
    }


def main(argv):
    from rag.system import make_embedder

    ap = argparse.ArgumentParser(prog="rag.recall", description="recall@k per retrieval mode, no LLM loaded.")
    ap.add_argument("config")
    args = ap.parse_args(argv)
    cfg = load_rag_config(args.config)
    s = cfg["rag"]
    r = s["retrieval"]
    index, emb = open_index(s, load_documents(s["docs_dir"])), make_embedder(s)
    reranker = CrossEncoderReranker(r["rerank"]) if r["rerank"] else None
    retrievers = {m: Retriever(index, emb, m, r["k"], r["candidates"]) for m in ("dense", "hybrid")}
    if reranker:
        retrievers |= {f"{m}+rerank": Retriever(index, emb, m, r["k"], r["candidates"], reranker) for m in ("dense", "hybrid")}
    qa = read_qa(cfg["eval_set"])
    print(f"| mode | recall@{r['k']} (n={sum(bool(q['sources']) for q in qa)}) |\n|---|---|")
    for name, v in recall_table(qa, retrievers).items():
        print(f"| {name} | {'—' if v is None else f'{v:.2f}'.replace('.', ',')} |")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
```

`configs/rag-hybrid.yaml` : copie de `configs/rag-example.yaml` avec

```yaml
  retrieval: {mode: hybrid, k: 5, candidates: 20, rerank: BAAI/bge-reranker-v2-m3}
```

Vérifier la signature réelle de `read_qa` dans `common/jsonl.py` avant d'écrire l'appel (elle est utilisée par `evalkit/run.py`).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_recall.py -q && uv run ruff check . && uv run pytest -q`
Expected: PASS, ruff propre.

- [ ] **Step 5: Commit**

```bash
git add rag/recall.py configs/rag-hybrid.yaml tests/test_recall.py
git commit -m "feat(rag): rag.recall compares retrieval modes by recall@k without an LLM"
```

---

### Task 5: Validation réelle et décision (manuelle, pas de code)

**Files:**
- Modify: `docs/PRD.md` §7 (ligne M4+), `docs/TRD.md` §6.2 (une phrase : modes disponibles, clé `fts`)
- Test: `tests/test_rag_real_smoke.py` (marqué `slow`, calqué sur `tests/test_ft_smoke.py`)

- [ ] **Step 1: Smoke lent** — un test `@pytest.mark.slow` qui indexe `data/examples/docs` avec `BAAI/bge-m3`, construit `make_retriever` avec `rerank: BAAI/bge-reranker-v2-m3` en `hybrid`, et vérifie que `retriever("Quelle est la capitale de la France ?")[0]["doc_id"] == "geo.md"`. Copier le style de marqueur/skip de `test_ft_smoke.py`.

- [ ] **Step 2: Lancer sur de vrais documents**

```bash
uv run python -m rag.index configs/rag-hybrid.yaml
uv run python -m rag.recall configs/rag-hybrid.yaml
```

Expected : un tableau à 4 lignes. Noter dans `docs/PRD.md` (ligne M4+) quel mode gagne et de combien ; si l'écart est < 1 question sur le jeu d'évaluation, le dire (jeu trop petit : voir risque PRD §8) plutôt que conclure.

- [ ] **Step 3: Comparaison complète (M3) avec le meilleur mode**

```bash
uv run python -m evalkit.compare configs/compare-example.yaml   # avec rag.retrieval du config gagnant
```

Expected : rapport 4 systèmes ; comparer `base+rag` / `ft+rag` à la run M3 dense. Un modèle plus gros = changer `rag.generation.model` et relancer, sans code.

- [ ] **Step 4: Commit**

```bash
git add docs tests/test_rag_real_smoke.py
git commit -m "docs(m4): record retrieval-mode results; slow real-model smoke"
```

---

## Self-Review

- **Couverture spec :** hybride + RRF (T2, T3), rerank (T3), même interface `retrieve(query)->passages` (T3), pas de nouvelle dépendance (FTS LanceDB, `CrossEncoder` déjà là), index périmé → erreur claire via `index_key` (T2), « décider selon ce que M3 révèle » → `rag.recall` + T5. « Modèles plus gros » : volontairement config seule.
- **Placeholders :** aucun ; seul point à vérifier à l'exécution est la signature de `read_qa` (signalé en T4) et les fakes de `test_compare_build.py` (signalé en T3).
- **Cohérence des noms :** `Retriever`, `make_retriever`, `rrf`, `CrossEncoderReranker`, `search_text`, `OverlapReranker` identiques partout ; `RagSystem(..., retriever=None)` garde la signature M3.
- **Review Focus :** requêtes vides/mots vides (T3), caractères spéciaux (T2), k > corpus (T3), doublons (T3 rrf), ancien index (T2 via clé).
