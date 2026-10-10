# PRD — Labo IA : Fine-tuning de LLM et pipelines RAG

- **Statut :** Brouillon v0.1
- **Date :** 2026-10-09
- **Auteur :** Nicolas Lallier

## 1. Contexte et vision

Ce repo est un laboratoire personnel pour apprendre, par la pratique, deux techniques centrales des LLM :

1. **Adapter un modèle** à une tâche ou un domaine (fine-tuning LoRA/QLoRA).
2. **Donner des connaissances externes à un modèle** (RAG : Retrieval-Augmented Generation).

Le fil conducteur est la **mesure**. Chaque technique est évaluée sur les mêmes données et les mêmes questions. On peut ainsi répondre à la question « qu'est-ce qui m'apporte quoi ? » au lieu de tester à l'aveugle.

### Non-objectifs

- Pas de **pré-entraînement from scratch** (hors de portée du matériel).
- Pas de **mise en production** : pas de haute disponibilité, d'authentification ni de multi-utilisateur.
- Pas de **framework générique** ni de système de plugins.
- Pas d'interface web au départ (CLI et notebooks suffisent).

## 2. Utilisateur et cas d'usage

**Utilisateur unique :** Nicolas, en apprentissage.

| # | Cas d'usage |
|---|---|
| U1 | Indexer mes propres documents (notes, PDF, code) et leur poser des questions avec des réponses citées. |
| U2 | Fine-tuner un petit modèle open source sur un jeu de données de mon choix. |
| U3 | Évaluer objectivement une variante (chunking, embeddings, hyperparamètres LoRA…). |
| U4 | Comparer base seule, base + RAG, fine-tuné, et fine-tuné + RAG sur les mêmes questions. |
| U5 | Rejouer n'importe quelle expérience passée à l'identique. |

## 3. Contraintes

- **Matériel :** Mac Apple Silicon. La **mémoire unifiée** est la limite principale, pas la puissance de calcul.
- **Modèles ciblés :** 1B à 8B de paramètres, quantifiés. Le fine-tuning se fait par adaptateurs (LoRA/QLoRA).
- **Local d'abord :** les données restent sur la machine. Le coût visé est proche de zéro.
- **Stack :** Python. Gestion des dépendances avec `uv`.

> Ces choix d'outils sont des hypothèses de départ, à confirmer en M0 : MLX / `mlx-lm` pour le fine-tuning, Ollama ou `mlx-lm` pour l'inférence, `sentence-transformers` pour les embeddings, une base vectorielle embarquée (LanceDB ou Chroma).

## 4. Exigences fonctionnelles

### 4.1 Socle commun (`data/`, `eval/`)

- **F1.** Un format de jeu de données unique (JSONL) pour les documents, les paires question/réponse et les exemples d'entraînement.
- **F2.** Un jeu d'évaluation de référence : un ensemble de questions avec réponses attendues et documents sources.
- **F3.** Un harnais d'évaluation unique qui prend en entrée « un système qui répond » et produit des métriques comparables (voir §5).
- **F4.** Chaque exécution enregistre sa configuration, ses résultats et la version des données.

### 4.2 Pipeline RAG (`rag/`)

- **F5.** Ingestion : chargement (Markdown, PDF, texte, code), nettoyage, découpage en chunks configurable.
- **F6.** Indexation : calcul des embeddings et stockage dans une base vectorielle locale.
- **F7.** Récupération : recherche par similarité, avec top-k réglable. Recherche hybride (mots-clés + vecteurs) et reranking ajoutés ensuite comme variantes.
- **F8.** Génération : prompt composé des passages récupérés, réponse avec **citations des sources**.
- **F9.** Chaque étape est remplaçable par une variante via la configuration (chunking, modèle d'embedding, k, modèle de génération).

### 4.3 Pipeline de fine-tuning (`finetune/`)

- **F10.** Préparation des données : conversion vers le format d'entraînement, découpage train/validation.
- **F11.** Entraînement LoRA/QLoRA d'un modèle de base choisi, hyperparamètres en configuration.
- **F12.** Suivi des courbes de perte (train et validation) et sauvegarde des adaptateurs avec leur configuration.
- **F13.** Chargement d'un adaptateur pour l'inférence, avec ou sans fusion dans le modèle de base.

### 4.4 Comparaison (`eval/`)

- **F14.** Un rapport qui évalue quatre systèmes sur le même jeu de questions : base seule, base + RAG, fine-tuné, fine-tuné + RAG.

## 5. Exigences non fonctionnelles

- **Reproductibilité :** graines fixées, versions des dépendances verrouillées, configuration versionnée dans le repo.
- **Suivi d'expériences :** un dossier `runs/<date>-<nom>/` par exécution, avec configuration, métriques et sorties. Un outil dédié (MLflow, W&B) n'est ajouté que si ce format devient pénible.
- **Évaluation (métriques de départ) :**
  - RAG : taux de présence de la bonne source dans le top-k (recall@k) et fidélité de la réponse aux passages cités.
  - Fine-tuning : perte de validation et exactitude sur un jeu de test tenu à l'écart.
  - Comparaison : exactitude des réponses sur le jeu de référence, évaluée par règles ou par un LLM juge.
- **Simplicité :** peu de dépendances, une commande par étape, chaque module compréhensible isolément.
- **Données :** aucun document personnel n'est commité. `data/` est ignoré par git, seuls des exemples synthétiques sont versionnés.

## 6. Architecture et structure du repo

```
AI/
├── docs/            # PRD, notes, décisions
├── data/            # jeux de données (ignoré par git, sauf exemples)
├── common/          # chargement de config, format JSONL, utilitaires partagés
├── rag/             # ingestion, index, récupération, génération
├── finetune/        # préparation, entraînement, chargement d'adaptateurs
├── eval/            # harnais, métriques, rapport de comparaison
├── configs/         # fichiers YAML des expériences
├── runs/            # résultats des exécutions (ignoré par git)
└── pyproject.toml
```

**Principe de conception :** `rag/` et `finetune/` ne dépendent pas l'un de l'autre. Ils ne partagent que `common/` et le contrat d'`eval/` : un système expose une fonction `answer(question) -> {réponse, sources}`.

## 7. Jalons

| Jalon | Contenu | Critère de réussite |
|---|---|---|
| **M0 — Socle** | Repo Python avec `uv`, structure, format de données, harnais d'évaluation minimal, premier jeu d'évaluation (20 à 50 questions) | `uv run` lance une évaluation de bout en bout sur un « système » trivial. |
| **M1 — RAG v1** | Ingestion, index, récupération, génération avec citations | Réponses citées sur mes documents, recall@k mesuré. |
| **M2 — Fine-tuning v1** | LoRA sur un modèle de 1 à 3B avec MLX, suivi des courbes | Un adaptateur entraîné et rechargeable, perte de validation qui baisse. |
| **M3 — Comparaison** | Rapport des quatre systèmes | Un tableau comparatif reproductible à partir d'une seule commande. |
| **M4+ — Variantes** | Recherche hybride, reranking, modèles plus gros, autres tâches | Construit : recherche hybride (dense + FTS fusionnés par RRF), reranking cross-encoder, et `python -m rag.recall` (recall@k par mode, sans LLM). **À renseigner** : mode gagnant et écarts de recall, après exécution de `rag.recall` sur de vrais documents (si l'écart est < 1 question, jeu trop petit pour conclure). Modèles plus gros / autres tâches : à définir selon ce que M3 révèle. |

M1 et M2 sont indépendants et peuvent avancer en parallèle une fois M0 terminé.

## 8. Risques et questions ouvertes

| Risque / question | Impact | Piste |
|---|---|---|
| Mémoire insuffisante pour le modèle visé | Entraînement impossible ou très lent | Commencer à 1–3B, QLoRA, batch réduit. |
| Jeu d'évaluation trop petit ou biaisé | Comparaisons peu fiables | Le construire à partir de vrais documents, le faire grandir au fil des échecs. |
| LLM juge peu fiable | Métriques bruitées | Compléter par des règles simples et une relecture manuelle d'un échantillon. |
| Fine-tuning pour injecter des faits | Résultat décevant, ce n'est pas son rôle | Le fine-tuning vise le style, le format et la tâche. Les faits vont dans le RAG. C'est justement ce que M3 doit illustrer. |
| **Ouvert :** quels documents indexer en premier ? | Définit le jeu d'évaluation | À choisir au démarrage de M0. |
| **Ouvert :** quelle tâche pour le fine-tuning ? | Définit les données d'entraînement | À choisir avant M2. |
| **Ouvert :** modèle de base de départ | Détermine la mémoire et la vitesse | Comparer 2 ou 3 candidats en début de M2. |
