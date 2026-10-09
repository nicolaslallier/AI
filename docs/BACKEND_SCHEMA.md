# Schéma backend — Labo IA

- **Statut :** Brouillon v0.1 (dérivé de [PRD.md](PRD.md) v0.1)
- **Date :** 2026-10-09

Pas de serveur ni de base relationnelle (PRD §1, non-objectifs). Le « backend » est composé de :
fichiers JSONL (données), YAML (configuration), dossier `runs/` (résultats) et un index vectoriel embarqué.
Ce document fixe les formats. Il sert de contrat entre `common/`, `rag/`, `finetune/` et `eval/`.

## 1. Conventions

- Encodage UTF-8, un objet JSON par ligne (JSONL), clés en `snake_case`.
- Les `id` sont des chaînes stables et déterministes (jamais d'UUID aléatoire), pour permettre le rejeu (U5).
  - `doc_id` : chemin relatif normalisé du fichier source, ex. `notes/lora.md`.
  - `chunk_id` : `<doc_id>#<n>` où `n` est le rang du chunk dans le document, ex. `notes/lora.md#3`.
  - `question_id` : `q001`, `q002`…
- Champ `schema_version` (entier, actuellement `1`) dans chaque fichier de config et de run. Les JSONL de données en sont dispensés : la version est portée par le nom du dataset (§2.5).

## 2. Données (`data/`)

### 2.1 Document — `data/<dataset>/documents.jsonl` (F1, F5)

| Champ | Type | Obligatoire | Note |
|---|---|---|---|
| `doc_id` | string | oui | voir §1 |
| `source_type` | `md` \| `pdf` \| `txt` \| `code` | oui | |
| `title` | string | non | |
| `text` | string | oui | texte nettoyé |
| `meta` | object | non | libre (auteur, date, langage…) |

### 2.2 Question d'évaluation — `data/<dataset>/eval.jsonl` (F2)

| Champ | Type | Obligatoire | Note |
|---|---|---|---|
| `question_id` | string | oui | |
| `question` | string | oui | |
| `expected_answer` | string | oui | réponse de référence |
| `source_doc_ids` | string[] | oui | documents contenant la réponse (base du recall@k) ; `[]` si la question n'a pas de source |
| `match` | `exact` \| `contains` \| `judge` | oui | méthode de notation (PRD §5) |
| `split` | `dev` \| `test` | oui | `test` n'est jamais utilisé pour régler une variante |

### 2.3 Exemple d'entraînement — `data/<dataset>/train.jsonl`, `val.jsonl` (F10)

Format « messages » (compatible `mlx-lm`) :

```json
{"messages": [
  {"role": "system", "content": "…"},
  {"role": "user", "content": "…"},
  {"role": "assistant", "content": "…"}
]}
```

`system` est optionnel. Le découpage train/val est fait par `finetune/` avec une graine fixée ; les questions `split: test` de §2.2 n'apparaissent jamais ici.

### 2.4 Chunk — index vectoriel (F5, F6)

Stocké dans la base vectorielle (LanceDB ou Chroma, à confirmer en M0), pas dans un fichier versionné.

| Champ | Type | Note |
|---|---|---|
| `chunk_id` | string | voir §1 |
| `doc_id` | string | |
| `text` | string | |
| `vector` | float[] | dimension = celle du modèle d'embedding |
| `start`, `end` | int | offsets de caractères dans `Document.text`, pour la citation |

L'index est rattaché à une configuration : le dossier d'index s'appelle `data/<dataset>/index/<hash>/`, où `<hash>` est le hash de `{chunking, embedding}` (§4). Changer le chunking ou le modèle d'embedding crée un nouvel index, jamais une mise à jour silencieuse.

### 2.5 Versionnage des données (F4)

`data/<dataset>/MANIFEST.json` : `{"dataset": "...", "version": "...", "files": {"documents.jsonl": "<sha256>", ...}}`.
Le run en copie le contenu dans `run.json` (§3). `data/` est ignoré par git, seuls les exemples synthétiques sous `data/examples/` sont commités.

## 3. Contrat d'évaluation (`eval/`)

### 3.1 Contrat système (PRD §6)

```
answer(question: str) -> Answer
```

```json
{
  "answer": "string",
  "sources": [
    {"chunk_id": "notes/lora.md#3", "doc_id": "notes/lora.md", "score": 0.82}
  ]
}
```

`sources` est une liste vide pour les systèmes sans RAG (base seule, fine-tuné). Les `sources` sont classées par pertinence décroissante.

### 3.2 Dossier de run — `runs/<AAAA-MM-JJ>-<nom>/` (F4, U5)

| Fichier | Contenu |
|---|---|
| `config.yaml` | copie exacte de la config utilisée (§4) |
| `run.json` | métadonnées (voir ci-dessous) |
| `outputs.jsonl` | une ligne par question : sortie brute et notation (§3.3) |
| `metrics.json` | métriques agrégées (§3.4) |
| `train_log.jsonl` | fine-tuning seulement : `{"step", "train_loss", "val_loss"}` (F12) |
| `adapter/` | fine-tuning seulement : adaptateur LoRA + `adapter_config` (F12) |

`run.json` :

```json
{
  "schema_version": 1,
  "run_id": "2026-10-09-rag-baseline",
  "started_at": "2026-10-09T14:03:00Z",
  "seed": 42,
  "git_commit": "60d0acc",
  "git_dirty": false,
  "dataset": {"name": "notes", "version": "v1", "manifest_sha256": "…"},
  "system": "base+rag"
}
```

`system` ∈ `base` \| `base+rag` \| `finetuned` \| `finetuned+rag` (F14).

### 3.3 Sortie par question — `outputs.jsonl`

| Champ | Type | Note |
|---|---|---|
| `question_id` | string | |
| `answer` | string | |
| `sources` | Source[] | voir §3.1 |
| `correct` | bool \| null | `null` si non noté |
| `judge_notes` | string | non obligatoire, présent si `match: judge` |
| `latency_ms` | int | |
| `error` | string \| null | une erreur n'interrompt pas le run |

### 3.4 Métriques — `metrics.json`

```json
{
  "n_questions": 40,
  "accuracy": 0.55,
  "recall_at_k": {"k": 5, "value": 0.80},
  "faithfulness": 0.71,
  "val_loss": 1.12
}
```

Les clés qui ne s'appliquent pas au système (ex. `recall_at_k` pour `base`) sont omises, pas mises à `null`. Le rapport de comparaison (F14) lit les `metrics.json` de plusieurs runs sur le **même** `dataset.manifest_sha256` et refuse de comparer des runs de données différentes.

## 4. Configuration — `configs/<nom>.yaml` (F9, F11)

```yaml
schema_version: 1
seed: 42
dataset: notes@v1

system: base+rag            # base | base+rag | finetuned | finetuned+rag

generation:
  model: <id du modèle de base>
  adapter: null             # chemin vers runs/.../adapter si finetuned
  merge_adapter: false      # F13
  temperature: 0.0
  max_tokens: 512

rag:                        # ignoré si system n'utilise pas le RAG
  chunking: {size: 512, overlap: 64}
  embedding: {model: <id du modèle d'embedding>}
  retrieval: {mode: vector, k: 5}   # mode: vector | hybrid ; rerank: null | <modèle>
  prompt: default           # nom du gabarit de prompt

finetune:                   # ignoré hors entraînement
  base_model: <id du modèle>
  lora: {rank: 16, alpha: 32, dropout: 0.05, quantize: true}   # quantize: true = QLoRA
  train: {batch_size: 2, lr: 1.0e-4, iters: 600, val_split: 0.1}

eval:
  split: dev                # dev | test
  judge_model: null         # requis si une question a match: judge
```

Règles de validation (faites au chargement dans `common/`) :
- clé inconnue = erreur (évite les fautes de frappe silencieuses) ;
- `system` avec RAG exige la section `rag`, `finetuned*` exige `generation.adapter` ;
- `eval.split: test` est refusé tant que la config n'a pas `confirm_test: true`, pour protéger le jeu de test.

## 5. Hors périmètre

Pas d'authentification, de multi-utilisateur, de migrations ni d'API HTTP (PRD non-objectifs). Si une interface web arrive plus tard, elle lira ces mêmes fichiers.
