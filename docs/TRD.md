# TRD — Labo IA : Fine-tuning de LLM et pipelines RAG

- **Statut :** Brouillon v0.1
- **Date :** 2026-10-09
- **Auteur :** Nicolas Lallier
- **Document source :** [PRD.md](PRD.md)

Ce document traduit le PRD en décisions techniques. Il dit **comment** construire, là où le PRD dit **quoi** et **pourquoi**. Les choix marqués ⚠️ sont des hypothèses à valider en M0 ; tout le reste est décidé.

## 1. Principes techniques

1. **Une seule abstraction : `answer()`.** Tout système évaluable est une fonction `answer(question) -> Answer`. `rag/` et `finetune/` ne s'importent jamais entre eux ; l'assemblage « fine-tuné + RAG » se fait par configuration, dans `eval/`.
2. **Fichiers plutôt que services.** JSONL, YAML, dossiers `runs/`. Pas de serveur, pas de base externe, pas de conteneur.
3. **Un seul runtime d'inférence : MLX.** Il charge nativement les adaptateurs LoRA qu'il a entraînés, sans conversion de format. Cela évite d'avoir à maintenir deux chemins (entraînement MLX, inférence autre).
4. **Config = vérité.** Une expérience est entièrement décrite par un fichier YAML + la version des données + la graine. Rien n'est codé en dur.
5. **Peu de dépendances.** Toute dépendance ajoutée est justifiée dans la section 9.

## 2. Environnement et stack

| Domaine | Choix | Justification |
|---|---|---|
| Matériel cible | Mac Apple Silicon, 24–36 Go de mémoire unifiée | Confirmé par l'utilisateur. |
| Langage | Python 3.12 | Version stable, supportée par MLX et sentence-transformers. |
| Dépendances | `uv` (`pyproject.toml` + `uv.lock` commité) | Imposé par le PRD ; verrouillage = reproductibilité. |
| Fine-tuning | `mlx-lm` (commande `mlx_lm.lora`, API Python pour le chargement) | Natif Apple Silicon, QLoRA supporté sur modèles quantifiés. |
| Inférence | `mlx-lm` | Voir principe 3. |
| Embeddings | `sentence-transformers` ⚠️ modèle multilingue : `BAAI/bge-m3` ou `intfloat/multilingual-e5-large` | Corpus et questions en français. À départager en M1 sur le recall@k. |
| Base vectorielle | LanceDB (embarquée, stockée dans `data/index/`) | Fichier local, recherche plein texte intégrée → la recherche hybride (M4) ne demande pas de nouvelle dépendance. Chroma reste l'alternative. |
| Config | YAML + validation par `pydantic` | Seule validation à la frontière : une faute de frappe dans un YAML doit échouer tôt, pas après 40 minutes d'entraînement. |
| CLI | `argparse` (stdlib) | Suffisant pour « une commande par étape ». |
| Tests | `pytest` | Standard. |
| Lint / format | `ruff` | Un seul outil. |

### Modèles candidats ⚠️

Contrainte : le français doit être correct. Candidats à comparer au début de M2 (1 heure de test chacun) :

- `Qwen2.5-3B-Instruct` (4 bits) — point de départ recommandé : rapide, bon multilingue.
- `Llama-3.2-3B-Instruct` (4 bits)
- Un modèle ~7–8B (4 bits) en M4 seulement, une fois la chaîne validée.

Les modèles sont référencés par identifiant Hugging Face dans la config ; aucun poids n'est commité.

## 3. Budget mémoire

La mémoire unifiée est partagée entre macOS, les outils ouverts et le GPU. Règle pratique : **viser ≤ 60 % de la RAM totale pour un entraînement**, car macOS limite la mémoire GPU « câblée » à une fraction de la RAM.

| Machine | Entraînement QLoRA confortable | Inférence |
|---|---|---|
| 24 Go | 1–3B, batch 1–4, séquence ≤ 2048 ; 7–8B possible mais serré | jusqu'à ~8B en 4 bits |
| 36 Go | 3B large ; 7–8B réaliste avec batch 1–2 | 8B en 4 bits + embeddings en parallèle |

Leviers si ça sature, par ordre d'application : réduire la longueur de séquence → réduire le batch → activer `grad_checkpoint` → réduire le rang LoRA ou le nombre de couches adaptées → changer de modèle.

**Règle de séquencement :** ne jamais charger simultanément le modèle de génération, le modèle juge et le modèle d'embedding sans l'avoir mesuré. Les étapes d'`eval` s'exécutent en phases (embeddings → génération → jugement), chaque modèle étant libéré avant le suivant.

## 4. Formats de données

Tous les fichiers sont en JSONL UTF-8, une entité par ligne, champ `id` stable. Schémas validés par `pydantic` dans `common/schemas.py`.

### 4.1 Document (`data/docs/*.jsonl`)

```json
{"id": "notes-2026-001", "source": "notes/archi.md", "text": "...", "meta": {"type": "markdown"}}
```

### 4.2 Chunk (produit par `rag/ingest`)

```json
{"id": "notes-2026-001#3", "doc_id": "notes-2026-001", "text": "...", "start": 1200, "end": 1800}
```

L'ID du chunk dérive de `doc_id` + position : un chunk reste identifiable d'une réindexation à l'autre tant que le découpage ne change pas, ce qui permet de calculer le recall@k sur des IDs de document plutôt que sur du texte.

### 4.3 Jeu d'évaluation (`data/eval/ref.jsonl`)

```json
{"id": "q-017", "question": "...", "expected": "...", "source_doc_ids": ["notes-2026-001"], "tags": ["factuel"]}
```

`source_doc_ids` est la vérité terrain du recall@k. `tags` permet de ventiler les résultats (factuel / style / format…), utile pour la lecture RAG vs fine-tuning.

### 4.4 Exemple d'entraînement (`data/train/*.jsonl`)

Format « chat » attendu par `mlx-lm` :

```json
{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

`finetune/prepare` produit `train.jsonl`, `valid.jsonl` et `test.jsonl` à partir de la source, avec un **découpage déterministe** (hash de l'`id` + graine) pour qu'un exemple ne migre jamais d'un jeu à l'autre. **Le jeu de test n'est jamais utilisé pour choisir des hyperparamètres.**

### 4.5 Versionnage des données

`data/` est ignoré par git. Chaque run enregistre une **empreinte** (SHA-256) de chaque fichier de données utilisé dans `runs/<…>/manifest.json`. Deux runs sont comparables si et seulement si leurs empreintes de `ref.jsonl` sont identiques ; `eval/report` refuse de comparer sinon.

## 5. Interfaces et contrats

### 5.1 Contrat d'évaluation (`common/types.py`)

```python
@dataclass
class Answer:
    text: str
    sources: list[str]          # doc_id des passages cités, ordre de citation
    retrieved: list[str] = []   # doc_id des passages récupérés (pour recall@k), vide si pas de RAG
    meta: dict = {}             # latence, tokens, etc.

class System(Protocol):
    name: str
    def answer(self, question: str) -> Answer: ...
```

`retrieved` est distinct de `sources` : le recall@k mesure ce que la récupération a trouvé, la fidélité mesure ce que le modèle a effectivement cité.

### 5.2 Les quatre systèmes (F14)

| Système | Composition |
|---|---|
| `base` | `Generator(base)` |
| `base+rag` | `RagSystem(retriever, Generator(base))` |
| `ft` | `Generator(base + adaptateur)` |
| `ft+rag` | `RagSystem(retriever, Generator(base + adaptateur))` |

Un seul `Generator` (dans `common/llm.py`) enveloppe `mlx-lm` : `generate(messages, **params)`, avec un paramètre optionnel `adapter_path`. `rag/` reçoit un `Generator` en argument et ignore s'il est fine-tuné. C'est ce qui garde les deux pipelines indépendants.

### 5.3 Configuration d'expérience (`configs/*.yaml`)

```yaml
name: rag-v1-bge-k5
seed: 42
data:
  docs: data/docs/
  eval: data/eval/ref.jsonl
rag:
  chunking: {strategy: recursive, size: 800, overlap: 100}
  embedding: {model: BAAI/bge-m3, batch_size: 16}
  retrieval: {mode: dense, k: 5}
  generation: {model: mlx-community/Qwen2.5-3B-Instruct-4bit, max_tokens: 400, temperature: 0.0}
```

Règles : un YAML par expérience, pas d'héritage ni de templating (YAGNI). Les valeurs par défaut vivent dans les modèles `pydantic`. Température 0 par défaut pour l'évaluation (voir §8).

### 5.4 Dossier de run

```
runs/2026-10-09-rag-v1-bge-k5/
├── config.yaml       # copie exacte de la config utilisée
├── manifest.json     # empreintes des données, versions (git SHA, uv.lock hash, mlx-lm), graine, machine
├── predictions.jsonl # une ligne par question : Answer + métriques par question
├── metrics.json      # agrégats
└── logs.txt
```

Un run est **immuable** : on ne réécrit pas un dossier existant, on en crée un nouveau (suffixe incrémental en cas de collision de nom).

### 5.5 Commandes (une par étape)

```
uv run python -m rag.ingest   --config configs/X.yaml
uv run python -m rag.index    --config configs/X.yaml
uv run python -m rag.ask      --config configs/X.yaml "question"
uv run python -m finetune.prepare --config configs/Y.yaml
uv run python -m finetune.train   --config configs/Y.yaml
uv run python -m eval.run     --config configs/Z.yaml   # évalue un système
uv run python -m eval.report  runs/A runs/B runs/C runs/D   # tableau comparatif (M3)
```

## 6. Conception des modules

### 6.1 `common/`

- `config.py` : chargement YAML → modèles `pydantic`.
- `schemas.py` : schémas des §4.1–4.4, lecture/écriture JSONL.
- `types.py` : `Answer`, `System`.
- `llm.py` : `Generator` (chargement du modèle et de l'adaptateur, génération).
- `runs.py` : création du dossier de run, `manifest.json`, empreintes.

### 6.2 `rag/` (F5–F9)

Chaîne : **ingest → index → retrieve → generate**.

- **Ingestion (F5).** Chargeurs par extension (Markdown, texte, code : lecture directe ; PDF : `pypdf` ⚠️ — à remplacer seulement si l'extraction se révèle illisible sur tes PDF). Nettoyage minimal (espaces, en-têtes/pieds répétés). Découpage récursif par séparateurs (titres → paragraphes → phrases) avec taille et recouvrement en caractères, configurables. Variantes ajoutées plus tard comme valeurs de `chunking.strategy`, pas comme nouvelles classes par défaut.
- **Indexation (F6).** Embeddings par lots, vecteurs normalisés, stockés dans une table LanceDB avec `id`, `doc_id`, `text`. Les modèles E5 exigent des préfixes `query:` / `passage:` — le préfixe est un paramètre du modèle d'embedding dans la config, pas une logique éparpillée.
- **Récupération (F7).** `dense` en v1 (top-k par similarité cosinus). `hybrid` (BM25/FTS de LanceDB fusionné avec le dense par RRF) et `rerank` (cross-encoder) en M4, derrière la même interface `retrieve(query, k) -> list[Chunk]`. Réglés par `rag.retrieval.mode` (`dense`|`hybrid`), `candidates` (taille du lot avant fusion/rerank) et `rerank` (id du cross-encoder, `""` = aucun) ; l'index porte un marqueur `fts` dans son hash, qui force une réindexation quand les paramètres FTS changent ; `python -m rag.recall <config>` compare les modes par recall@k.
- **Génération (F8).** Le prompt numérote les passages `[1] … [2] …` et impose de répondre **uniquement** à partir d'eux, en citant `[n]`, et de dire « je ne sais pas » si l'information est absente. Le parseur extrait les `[n]` de la réponse et les convertit en `doc_id` → `Answer.sources`. Une citation vers un numéro inexistant est comptée comme **citation invalide** (métrique) et non ignorée silencieusement.
- **Remplaçabilité (F9).** Chaque étape lit sa section de la config ; changer d'embedding ou de `k` = changer le YAML. Un changement de chunking ou d'embedding impose de réindexer ; l'index porte un hash de la config d'ingestion/embedding et `rag.ask` échoue clairement s'il ne correspond pas.

### 6.3 `finetune/` (F10–F13)

- **Préparation (F10).** Convertit les données sources vers le §4.4 ; découpage train/valid/test déterministe. Écrit un rapport de comptage (nb d'exemples, longueur moyenne/maximale en tokens, nb tronqués).
- **Entraînement (F11).** Génère la configuration attendue par `mlx_lm.lora` à partir du YAML et l'appelle. Hyperparamètres de départ ⚠️ : rang 8, alpha 16, 16 dernières couches, learning rate 1e-5 à 1e-4, séquence 1024–2048, 600–1000 itérations, validation toutes les 50–100 itérations. À régler empiriquement.
- **Suivi (F12).** Les pertes train/validation sont parsées depuis la sortie de `mlx-lm` vers `metrics.jsonl` (une ligne par point), et `finetune` produit `curves.png` (matplotlib, seule utilisation). Adaptateur sauvegardé dans `runs/<…>/adapters/` avec le `config.yaml` et le nom exact du modèle de base — **un adaptateur n'est valide que pour le modèle de base qui l'a produit** ; `Generator` vérifie cette correspondance au chargement.
- **Chargement (F13).** `Generator(adapter_path=…)` applique l'adaptateur à la volée. La fusion (`mlx_lm.fuse`) est une commande optionnelle séparée, utile seulement pour exporter ; elle n'est pas nécessaire pour l'évaluation.

### 6.4 `eval/` (F3, F14)

- `run.py` : charge `ref.jsonl`, construit le `System` demandé par la config, appelle `answer()` sur chaque question, écrit `predictions.jsonl` puis calcule les métriques.
- `metrics.py` : fonctions pures, testables sans modèle (voir §7).
- `judge.py` : LLM juge (§7.3).
- `report.py` : lit plusieurs dossiers de runs, vérifie que les empreintes de `ref.jsonl` coïncident, produit un tableau Markdown (`runs/…/report.md`) : une ligne par système, colonnes = métriques, plus la ventilation par `tag`.

## 7. Évaluation

### 7.1 Métriques

| Métrique | Définition | Où |
|---|---|---|
| `recall@k` | Part des questions dont au moins un `source_doc_ids` figure dans `Answer.retrieved[:k]` | RAG |
| `citation_validity` | Part des citations qui pointent vers un passage réellement fourni | RAG |
| `faithfulness` | Jugement : la réponse est-elle entièrement soutenue par les passages cités ? (0/1) | RAG, via juge |
| `val_loss` | Perte de validation finale et meilleure | Fine-tuning |
| `test_accuracy` | Exactitude sur `test.jsonl` | Fine-tuning |
| `accuracy` | Exactitude de la réponse vs `expected` | Comparaison (§7.2) |
| `latency_p50`, `tokens` | Coût d'usage | Tous |

### 7.2 Exactitude : règles d'abord, juge ensuite

1. **Règles** (déterministes, prioritaires quand applicables) : correspondance exacte normalisée, présence de mots-clés attendus, validation de format (JSON valide, etc.). Chaque question de `ref.jsonl` peut porter un champ `check` optionnel désignant la règle.
2. **LLM juge** pour les réponses libres, avec grille fermée (« correct / partiel / incorrect ») et sortie JSON stricte.

### 7.3 LLM juge

- **Local**, via `mlx-lm`. ⚠️ Tester d'abord un modèle de taille supérieure au système évalué (par ex. ~7–8B 4 bits pour juger un 3B) ; un juge de même taille que le système évalué est peu fiable.
- Température 0, prompt versionné dans le repo, **verdict + justification courte** conservés dans `predictions.jsonl`.
- **Calibration :** relire à la main un échantillon (≥ 20 réponses) et calculer l'accord juge/humain. Si l'accord est trop faible, on retombe sur les règles ou on change de juge — la décision est documentée dans le §9.
- Le juge n'est jamais le même modèle (ni le même adaptateur) que le système évalué.

### 7.4 Bruit et déterminisme

La génération à température 0 est quasi déterministe mais pas garantie bit à bit (noyaux GPU, version de MLX). Les versions sont donc enregistrées dans `manifest.json`, et une différence inférieure à la taille d'un petit nombre de questions n'est pas interprétée comme un signal. Avec 20–50 questions, un écart de 1–2 points n'est pas significatif : le rapport affiche les effectifs bruts (« 31/40 »), pas seulement des pourcentages.

## 8. Reproductibilité

- Graine unique `seed` propagée : découpage des données, ordre d'entraînement, génération.
- `uv.lock` commité ; `manifest.json` enregistre le SHA git (et signale si l'arbre est « sale »), les versions de `mlx`, `mlx-lm`, `sentence-transformers`, et la machine.
- Modèles référencés par identifiant ; ⚠️ épingler la **révision** Hugging Face dans la config pour les comparaisons importantes.
- U5 (rejouer à l'identique) = `eval.run --config runs/<run>/config.yaml` ; l'écart résiduel est borné par §7.4.

## 9. Décisions et alternatives écartées

| # | Décision | Alternatives | Pourquoi |
|---|---|---|---|
| D1 | MLX pour entraînement **et** inférence | Ollama / llama.cpp pour l'inférence | Les adaptateurs LoRA MLX se chargent directement ; Ollama imposerait fusion + conversion GGUF pour chaque expérience. |
| D2 | LanceDB | Chroma, FAISS, pgvector | Embarqué, fichier local, FTS intégré pour la recherche hybride, aucun serveur. |
| D3 | `pydantic` pour config et schémas | `dataclasses` + validation manuelle | Dépendance justifiée : erreurs claires aux frontières (YAML, JSONL). |
| D4 | Dossier `runs/` + JSON | MLflow, W&B | Suffisant au départ, conformément au PRD ; reconsidérer si la comparaison manuelle devient pénible. |
| D5 | `argparse` | Typer / Click | Stdlib suffit. |
| D6 | Pas de framework RAG (LangChain, LlamaIndex) | LangChain, LlamaIndex | Le but est d'apprendre les étapes ; ~200 lignes par étape sont plus lisibles que l'abstraction d'un framework. |
| D7 | Évaluation par phases (un modèle chargé à la fois) | Tout en mémoire | Tient dans 24 Go sans surprise. |

## 10. Stratégie de test

Tester ce qui peut casser silencieusement, pas tout. Aucun test ne charge un vrai modèle.

- **Unitaires (rapides, sans modèle) :** découpage en chunks (bornes, recouvrement), IDs stables, parseur de citations (`[n]` valides/invalides), calcul de recall@k, règles d'exactitude, découpage train/valid/test déterministe, empreintes de données, validation des configs.
- **Contrat :** un `System` trivial (réponse fixe) qui traverse `eval.run` de bout en bout — c'est le critère de réussite de M0.
- **Fumée (manuelle ou marquée `slow`) :** un mini-entraînement de quelques itérations sur un modèle minuscule pour vérifier que la chaîne prépare → entraîne → recharge fonctionne ; une mini-indexation sur 3 documents synthétiques.
- Les exemples synthétiques versionnés (voir PRD §5, Données) servent de fixtures.

## 11. Alignement avec les jalons

| Jalon | Livrables techniques | Validation de ce TRD |
|---|---|---|
| M0 | `pyproject.toml` + `uv.lock`, `common/` complet, `eval/run` + `metrics`, `ref.jsonl` initial, système trivial | Confirmer ⚠️ : embeddings, juge, PDF |
| M1 | `rag/*`, `retrieval: dense`, citations, recall@k | Choisir l'embedding sur recall@k |
| M2 | `finetune/*`, courbes, rechargement d'adaptateur | Choisir le modèle de base parmi les candidats |
| M3 | `eval/report`, 4 systèmes assemblés par config | Vérifier la comparabilité des empreintes |

## 12. Questions ouvertes

Reprises du PRD, avec l'impact technique :

1. **Documents à indexer en premier** — détermine les chargeurs à écrire (PDF ou pas) et le jeu d'évaluation.
2. **Tâche de fine-tuning** — détermine le format des exemples (§4.4) et la métrique `test_accuracy` (règle ou juge). Piste cohérente avec le PRD : style/format de réponse, pas l'injection de faits.
3. **Modèle de base** — §2, à trancher en début de M2.
4. **Juge** — modèle et seuil d'accord humain à fixer en M1, avant d'interpréter les premiers chiffres.
