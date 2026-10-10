# Labo IA — Fine-tuning de LLM et RAG

Laboratoire personnel pour apprendre, par la pratique, deux techniques des LLM : le **fine-tuning LoRA** et le **RAG** (Retrieval-Augmented Generation). Le fil conducteur est la **mesure** : les deux techniques sont évaluées sur les mêmes questions, ce qui permet de comparer quatre systèmes : `base`, `base+rag`, `ft` (fine-tuné) et `ft+rag`.

Tout tourne en local sur Mac Apple Silicon (MLX), sans service externe.

## Prérequis

- Mac Apple Silicon (la mémoire unifiée est la vraie limite)
- Python ≥ 3.11 et [`uv`](https://docs.astral.sh/uv/)

```bash
uv sync
uv run pytest        # tests rapides (les tests « slow » chargent un vrai modèle : -m slow)
```

## Structure

| Dossier | Rôle |
|---|---|
| `common/` | Config YAML, JSONL, adaptateur LLM, enregistrement des runs |
| `evalkit/` | Harnais d'évaluation, métriques, rapport, comparaison des 4 systèmes |
| `rag/` | Ingestion, chunking, embeddings, index LanceDB, génération avec citations |
| `finetune/` | Préparation des données, entraînement LoRA (`mlx-lm`), courbes |
| `configs/` | Exemples de configuration (`*-example.yaml`) |
| `data/examples/` | Documents et jeux de questions d'exemple |
| `docs/` | PRD, TRD, UX, flux applicatifs, schéma des données |

## Utilisation

Chaque commande prend un fichier de configuration YAML. Les résultats sont enregistrés dans `runs/` avec leur config et le hash du jeu de données.

**Évaluation de bout en bout (système trivial)**

```bash
uv run python -m evalkit.run configs/trivial.yaml
```

**RAG** : ingérer, indexer, poser une question

```bash
uv run python -m rag.ingest configs/rag-example.yaml      # aperçu du chunking
uv run python -m rag.index configs/rag-example.yaml       # embeddings + index
uv run python -m rag.ask configs/rag-example.yaml "Ma question ?"
uv run python -m evalkit.run configs/rag-example.yaml     # recall@k et métriques
```

**Fine-tuning**

```bash
uv run python -m finetune.prepare configs/ft-example.yaml  # split train/valid/test
uv run python -m finetune.train configs/ft-example.yaml    # adaptateur dans runs/<id>/adapters
```

**Comparaison des quatre systèmes** (une seule commande)

Renseigner `compare.adapter` dans `configs/compare-example.yaml` avec l'adaptateur produit ci-dessus, puis :

```bash
uv run python -m evalkit.compare configs/compare-example.yaml
```

Le run produit un `report.md` comparatif, un manifeste de reproduction et une **alerte de fuite** si des questions d'évaluation figurent dans les données d'entraînement (`compare.train_file`).

## Jalons

- [x] **M0** Socle et harnais d'évaluation
- [x] **M1** RAG v1 avec citations
- [x] **M2** Fine-tuning LoRA v1
- [x] **M3** Rapport comparatif des quatre systèmes
- [ ] **M4** Variantes : recherche hybride, reranking (PR en cours)

## Documentation

[Guide utilisateur](docs/USERGUIDE.md) · [PRD](docs/PRD.md) · [TRD](docs/TRD.md) · [UX](docs/UX.md) · [Flux applicatifs](docs/APPFLOW.md) · [Schéma des données](docs/BACKEND_SCHEMA.md)
