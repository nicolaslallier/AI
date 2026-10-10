# Guide utilisateur — Labo IA

Ce guide explique, pas à pas, comment utiliser le labo : évaluer un système, interroger vos documents (RAG), fine-tuner un modèle, puis comparer les quatre systèmes. Pour une vue d'ensemble, voir le [README](../README.md).

## 1. Principes

- **Une commande par étape.** Chaque étape se lance, se relance et se comprend isolément.
- **Tout passe par un fichier YAML.** La config est copiée dans le dossier du run : tout run est rejouable.
- **On mesure.** Chaque système est évalué sur le même jeu de questions.
- **Un run n'est jamais écrasé.** Les résultats vont dans `runs/<date>-<nom>/` (suffixe `-2`, `-3`… en cas de collision).

## 2. Installation

Prérequis : Mac Apple Silicon, Python ≥ 3.11, [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
```

Au premier lancement d'un RAG ou d'un fine-tuning, les modèles (embeddings, génération) sont téléchargés depuis Hugging Face. Prévoir plusieurs Go de disque et un peu de patience.

## 3. Vos données

Tous les jeux de questions sont des fichiers **JSONL** (un objet JSON par ligne) :

```json
{"id": "r2", "question": "Quel rang utilise LoRA par défaut ?", "answer": "8", "sources": ["lora.md"]}
```

| Champ | Rôle |
|---|---|
| `id` | Identifiant unique de la question |
| `question` | Texte posé au système |
| `answer` | Réponse attendue (courte : elle est cherchée dans la réponse du modèle) |
| `sources` | Fichiers qui contiennent la réponse (`[]` si aucune) |

Des exemples se trouvent dans `data/examples/`. Pour vos propres documents du RAG, déposez des fichiers dans un dossier et pointez `rag.docs_dir` dessus.

## 4. Parcours A — Vérifier le socle

```bash
uv run python -m evalkit.run configs/trivial.yaml
```

Évalue un système trivial sur `data/examples/eval.jsonl`. C'est le test de bon fonctionnement de l'installation : il affiche les métriques et le dossier du run.

## 5. Parcours B — Interroger mes documents (RAG)

1. Copiez `configs/rag-example.yaml` et réglez `rag.docs_dir` sur votre dossier de documents.
2. Aperçu du découpage :
   ```bash
   uv run python -m rag.ingest configs/rag-example.yaml
   ```
3. Calcul des embeddings et écriture de l'index :
   ```bash
   uv run python -m rag.index configs/rag-example.yaml
   ```
4. Poser une question, réponse avec citations des sources :
   ```bash
   uv run python -m rag.ask configs/rag-example.yaml "Quel rang utilise LoRA par défaut ?"
   ```
5. Mesurer sur un jeu de questions :
   ```bash
   uv run python -m evalkit.run configs/rag-example.yaml
   ```

Si vous modifiez les documents ou le chunking, relancez `rag.index` : une comparaison avec un index périmé est refusée.

### Paramètres `rag`

| Clé | Défaut | Effet |
|---|---|---|
| `docs_dir` | obligatoire | Dossier des documents |
| `index_dir` | `data/index` | Emplacement de l'index vectoriel |
| `chunking.size` / `overlap` | 800 / 100 | Taille des chunks et chevauchement (`0 ≤ overlap < size`) |
| `embedding.model` | obligatoire | Modèle d'embeddings (ex. `BAAI/bge-m3`) |
| `embedding.batch_size` | 16 | Réduire en cas de manque de mémoire |
| `retrieval.k` | 5 | Nombre de passages récupérés |
| `generation.model` | obligatoire | Modèle MLX qui répond |
| `generation.max_tokens` / `temperature` | 400 / 0.0 | Longueur et variabilité de la réponse |

## 6. Parcours C — Fine-tuner un modèle (LoRA)

1. Préparez un fichier source JSONL (voir `data/examples/ft_source.jsonl`) : questions et réponses souhaitées.
2. Copiez `configs/ft-example.yaml` et renseignez `finetune.source`, `finetune.data_dir`, `finetune.model`.
3. Découpage train / valid / test :
   ```bash
   uv run python -m finetune.prepare configs/ft-example.yaml
   ```
4. Entraînement :
   ```bash
   uv run python -m finetune.train configs/ft-example.yaml
   ```
   L'adaptateur est écrit dans `runs/<date>-<nom>/adapters`, avec les courbes de perte.
5. Évaluer l'adaptateur : reportez le chemin dans `finetune.adapter`, puis
   ```bash
   uv run python -m evalkit.run configs/ft-example.yaml
   ```

### Paramètres `finetune` utiles

| Clé | Défaut | Effet |
|---|---|---|
| `split.valid` / `test` | 0.15 / 0.15 | Parts de validation et de test (somme < 1) |
| `lora.rank` / `num_layers` | 8 / 16 | Capacité de l'adaptateur |
| `train.iters` | 600 | Nombre d'itérations |
| `train.batch_size` | 2 | Baisser si la mémoire manque |
| `train.max_seq_length` | 1024 | Longueur max des exemples |
| `train.grad_checkpoint` | `false` | Passer à `true` pour économiser de la mémoire |
| `system_prompt` | vide | À reprendre à l'identique dans la comparaison |

Repère : la perte de **validation** doit baisser. Si elle remonte alors que celle d'entraînement baisse, c'est du surapprentissage : réduisez `iters`.

## 7. Parcours D — Comparer les quatre systèmes

1. Dans `configs/compare-example.yaml` (ou une copie), renseignez :
   - `compare.adapter` : le dossier `adapters` de votre run d'entraînement ;
   - `compare.train_file` : le `train.jsonl` utilisé, pour activer l'alerte de fuite ;
   - `compare.system_prompt` : le même que `finetune.system_prompt` ;
   - `eval_set` et la section `rag`.
2. Lancer :
   ```bash
   uv run python -m evalkit.compare configs/compare-example.yaml
   ```

Les systèmes comparés sont `base`, `base+rag`, `ft`, `ft+rag` (liste modifiable dans `compare.systems`).

### Lire le rapport

Le rapport (`report.md`) est affiché et sauvegardé. Il contient :

- un **tableau** par système : exactitude, taux de bonne source, recall@k, validité des citations, latence moyenne ;
- un **verdict** : l'écart de chaque système par rapport au premier, en points et en nombre de questions. Si l'écart est inférieur à `compare.min_gap` question(s), il est marqué *non concluant* : sur un petit jeu, quelques questions de différence ne prouvent rien ;
- des **avertissements** : le plus important est la *fuite d'évaluation*, quand des questions d'évaluation figurent dans les données d'entraînement. Les résultats de `ft` sont alors optimistes ;
- des **notes** : par exemple l'absence de détection de fuite si `train_file` est vide.

### Métriques

| Métrique | Signification |
|---|---|
| `accuracy` | Part des réponses contenant la réponse attendue (insensible à la casse et aux accents) |
| `source_hit_rate` | Part des questions où une source attendue est citée |
| `recall_at_k` | Part des questions où une source attendue figure parmi les k passages récupérés |
| `citation_validity` | Part des citations qui pointent vers un passage réellement fourni |
| `latency_s` | Temps moyen de réponse par question |

## 8. Que contient un dossier de run ?

| Fichier | Contenu |
|---|---|
| `config.yaml` | Config exacte utilisée |
| `metrics.json` | Métriques, empreinte SHA-256 des données ; pour une comparaison, aussi le manifeste (modèle, adaptateur, clé d'index) |
| `outputs.jsonl` | Réponse de chaque système à chaque question |
| `report.md` | Rapport (comparaison uniquement) |

Pour rejouer un run : relancez la commande avec le `config.yaml` du dossier.

## 9. Dépannage

| Symptôme | Piste |
|---|---|
| `compare.adapter : … introuvable` | Lancer `finetune.train`, puis reporter le dossier `adapters` du run |
| Erreur d'adaptateur étranger | L'adaptateur a été entraîné avec un autre modèle que `rag.generation.model` |
| Index périmé | Relancer `rag.index` après changement de documents ou de chunking |
| Manque de mémoire | Réduire `embedding.batch_size`, `train.batch_size`, `train.max_seq_length`, ou activer `grad_checkpoint` |
| `missing train.jsonl — run: …finetune.prepare` | Lancer d'abord `finetune.prepare` |
| `unknown key(s) in …` | Faute de frappe dans le YAML : les clés inconnues sont refusées |
| « Fuite d'évaluation » | Retirer ces questions du jeu d'évaluation, ou de la source d'entraînement |

## 10. Pour aller plus loin

[PRD](PRD.md) · [TRD](TRD.md) · [UX](UX.md) · [Flux applicatifs](APPFLOW.md) · [Schéma des données](BACKEND_SCHEMA.md)
