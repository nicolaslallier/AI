# UX Design — Labo IA : Fine-tuning de LLM et pipelines RAG

- **Statut :** Brouillon v0.1
- **Date :** 2026-10-09
- **Auteur :** Nicolas Lallier
- **Réf. :** [PRD v0.1](PRD.md)

## 1. Périmètre

Le PRD exclut toute interface web au départ : l'expérience utilisateur est celle d'un **développeur seul dans son terminal et ses notebooks**. Ce document définit donc l'UX de quatre surfaces :

1. la **CLI** (une commande par étape),
2. les **fichiers de configuration** YAML,
3. le **dossier de run** `runs/<date>-<nom>/` et le **rapport de comparaison**,
4. les **notebooks** d'exploration.

Il couvre aussi les messages d'erreur et les retours d'état, qui sont l'« interface » principale d'un outil sans écran.

## 2. Principes directeurs

| # | Principe | Conséquence concrète |
|---|---|---|
| P1 | **Mesurer avant de ressentir** | Toute commande qui produit un système finit par un chiffre ou un chemin vers un chiffre. Pas de « ça a l'air de marcher ». |
| P2 | **Une commande par étape** (PRD §5) | Pas de commande fourre-tout ; chaque étape se lance, se relance et se comprend isolément. |
| P3 | **Rejouable à l'identique** (U5) | Tout ce qui influence un résultat est dans la config, et la config est copiée dans le run. |
| P4 | **Le défaut est le bon choix** | `uv run <cmd>` sans option doit faire quelque chose d'utile avec la config par défaut. |
| P5 | **Échouer tôt, dire quoi faire** | Les erreurs de mémoire, de config ou de données sont détectées avant l'étape longue, avec une action corrective. |
| P6 | **Apprendre en lisant** | Les sorties expliquent ce qui se passe (étapes, tailles, durées) : c'est un labo d'apprentissage, pas une boîte noire. |

## 3. Parcours utilisateur

Les parcours suivent les cas d'usage U1 à U5 et les jalons M0 à M3.

```
 M0 Socle            M1 RAG                 M2 Fine-tuning          M3 Comparaison
 ─────────           ─────────              ───────────────         ──────────────
 init données   →    ingest → index    →    prepare → train    →    compare
 eval trivial        ask → eval             chat → eval             rapport 4 systèmes
        └──────────── runs/<date>-<nom>/ : trace de chaque étape ────────────┘
```

### 3.1 Parcours A — Interroger mes documents (U1)

1. Je dépose mes documents dans `data/docs/`.
2. `uv run rag ingest` : charge, nettoie, découpe. Affiche le nombre de documents, de chunks et la taille médiane.
3. `uv run rag index` : calcule les embeddings, remplit la base. Affiche une barre de progression et la durée.
4. `uv run rag ask "ma question"` : réponse **avec citations** `[1] fichier.md §3`, puis liste des sources en pied.
5. Je mesure : `uv run eval run --system rag`.

### 3.2 Parcours B — Fine-tuner un modèle (U2)

1. `uv run finetune prepare` : conversion + découpage train/validation, avec compte des exemples et exemple affiché.
2. `uv run finetune train` : estimation mémoire d'abord, puis entraînement avec courbe de perte en direct.
3. `uv run finetune chat` : discussion avec le modèle + adaptateur, pour un contrôle qualitatif rapide.
4. `uv run eval run --system finetuned`.

### 3.3 Parcours C — Évaluer une variante (U3, U5)

1. Je copie une config : `configs/rag-base.yaml` → `configs/rag-chunk-256.yaml`, je change une valeur.
2. `uv run eval run --config configs/rag-chunk-256.yaml`.
3. `uv run eval diff <run-a> <run-b>` : écart de métriques et de config, côte à côte.
4. Pour rejouer : `uv run eval run --from runs/2026-10-09-rag-chunk-256/`.

### 3.4 Parcours D — Comparer les quatre systèmes (U4)

1. `uv run eval compare` : lance (ou réutilise) les quatre systèmes sur le même jeu de questions.
2. Un rapport `report.md` est écrit et son résumé s'affiche dans le terminal.

## 4. Conception de la CLI

### 4.1 Structure des commandes

Une commande racine par module, cohérente avec la structure du repo (PRD §6) :

| Commande | Rôle | Exigence |
|---|---|---|
| `rag ingest` / `index` / `ask` | Pipeline RAG | F5–F8 |
| `finetune prepare` / `train` / `chat` | Pipeline fine-tuning | F10–F13 |
| `eval run` / `diff` / `compare` | Évaluation et comparaison | F3, F14 |
| `runs list` / `show` | Parcourir l'historique | F4 |

Règles de nommage : verbes courts en minuscules, un seul niveau de sous-commande, mêmes noms d'options partout (`--config`, `--name`, `--seed`, `--verbose`).

### 4.2 Options communes

| Option | Effet | Défaut |
|---|---|---|
| `--config PATH` | Fichier YAML de l'expérience | `configs/default.yaml` |
| `--name TEXT` | Suffixe du dossier de run | nom de la config |
| `--set clé=valeur` | Surcharge ponctuelle d'une valeur de config (répétable) | aucune |
| `--seed INT` | Graine | valeur de la config |
| `--dry-run` | Valide la config, estime coût et mémoire, n'exécute pas | désactivé |
| `-v / -q` | Plus / moins de détail | normal |

`--set` sert aux essais rapides ; la surcharge est **toujours écrite dans la config copiée du run**, pour que P3 reste vrai.

### 4.3 Forme des sorties

Trois niveaux, toujours dans cet ordre :

1. **En-tête** (1–3 lignes) : ce qui va être fait, avec la config effective et le dossier de run.
2. **Progression** : une ligne par étape avec durée ; barre de progression pour les boucles longues ; sur une sortie non interactive (pipe, CI), lignes de log simples sans barre.
3. **Bilan** : résultat clé, chemin des artefacts, **prochaine commande suggérée**.

Exemple :

```
$ uv run rag index
▶ rag index · config=configs/default.yaml · run=runs/2026-10-09-default/
  embeddings : sentence-transformers/all-MiniLM-L6-v2 · chunks : 1 284
  ██████████████████████████████ 1284/1284  00:42
✔ Index écrit : data/index/ (1 284 vecteurs, 4,1 Mo) en 43 s
  Suite : uv run rag ask "…"   ou   uv run eval run --system rag
```

Règles :

- **Couleur et symboles** (`▶ ✔ ⚠ ✖`) en renfort seulement : le texte seul doit rester compréhensible. Couleurs désactivées si `NO_COLOR` est défini ou si la sortie n'est pas un terminal.
- **Nombres lisibles** : unités explicites (Mo, s), séparateur de milliers, pas plus de 3 chiffres significatifs pour les métriques.
- **Aucune sortie silencieuse** : une étape de plus de ~2 s affiche un signe de vie.
- **Code de sortie** : 0 succès, 1 échec d'exécution, 2 erreur d'usage ou de config.

### 4.4 Réponse du RAG (`rag ask`)

La lisibilité des citations est le cœur de l'UX du RAG (F8).

```
Q : Quelle est la politique de sauvegarde des notes ?

Les notes sont sauvegardées chaque nuit sur le NAS [1], avec une rétention
de 30 jours [2].

Sources
  [1] notes/infra.md · §Sauvegardes          (score 0,82)
  [2] notes/infra.md · §Rétention            (score 0,77)

⚠ Aucune source ne couvre « chiffrement » — cette partie de la question reste sans réponse.
```

- Chaque affirmation porte un marqueur `[n]` ; chaque marqueur renvoie à un fichier **et** une section ou ligne.
- Si la récupération ne trouve rien au-dessus d'un seuil, la réponse est « Je n'ai pas trouvé d'information dans les documents indexés » plutôt qu'une invention.
- `--show-context` affiche les passages bruts envoyés au modèle, pour comprendre pourquoi une réponse est mauvaise (P6).

### 4.5 Suivi de l'entraînement (`finetune train`)

- **Avant** : estimation de la mémoire requise vs disponible. Si ça ne rentre pas, arrêt avec une suggestion chiffrée (voir §7).
- **Pendant** : une ligne mise à jour toutes les N itérations : `iter 120/600 · train 1,84 · val 1,92 · 0,9 it/s · reste 9 min`.
- **Après** : courbe train/validation écrite en image dans le run (`loss.png`) ; message d'avertissement si la perte de validation remonte (sur-apprentissage).
- Interruption `Ctrl-C` : sauvegarde du dernier point de contrôle et indication de reprise (`--resume`).

## 5. Fichiers de configuration

La config est l'interface principale pour expérimenter (F9). Elle doit se lire comme une fiche d'expérience.

### 5.1 Principes

- **Un fichier YAML = une expérience complète**, lisible de haut en bas sans consulter le code.
- **Sections alignées sur les modules** : `data`, `rag`, `finetune`, `eval`.
- **Pas de valeur magique cachée dans le code** : tout paramètre qui influence un résultat figure dans le YAML, même s'il a une valeur par défaut.
- **Validation immédiate** au chargement : clé inconnue, type erroné ou chemin absent → erreur citant la ligne et la valeur attendue. Une faute de frappe ne doit jamais être ignorée silencieusement.
- **Héritage minimal** : un seul niveau (`extends: rag-base.yaml`), pour qu'une variante ne contienne que son écart.

### 5.2 Exemple

```yaml
# configs/rag-chunk-256.yaml — variante : chunks plus petits
extends: rag-base.yaml

name: rag-chunk-256
seed: 42

rag:
  chunking:
    size: 256        # tokens ; base = 512
    overlap: 32
  retrieval:
    top_k: 5
```

### 5.3 Conventions

- Noms de fichiers : `<module>-<variante>.yaml` (`rag-base`, `finetune-lora-r8`).
- Un commentaire en tête résume **l'hypothèse testée** : c'est ce qui rend l'historique des runs parlant.
- Les unités sont dans le commentaire ou le nom de la clé (`size_tokens`).

## 6. Dossier de run et rapport

### 6.1 Structure d'un run

```
runs/2026-10-09-rag-chunk-256/
├── config.yaml      # config effective après héritage et surcharges
├── meta.json        # versions (code, dépendances, données), graine, machine, durée
├── metrics.json     # métriques machine-lisibles
├── outputs.jsonl    # question, réponse, sources, verdict — une ligne par question
├── report.md        # résumé lisible
└── log.txt          # sortie complète de la commande
```

Le nom de dossier `<date>-<nom>` est lisible et trié chronologiquement. En cas de collision, suffixe `-2`.

### 6.2 `runs list` et `runs show`

`runs list` affiche un tableau compact, trié du plus récent au plus ancien :

```
RUN                          SYSTÈME     RECALL@5   EXACTITUDE   DURÉE
2026-10-09-rag-chunk-256     rag         0,86       0,62         3 min
2026-10-09-rag-base          rag         0,78       0,58         3 min
2026-10-08-baseline          base        —          0,31         1 min
```

`runs show <run>` affiche `report.md` ; `eval diff` compare deux runs et **met en évidence les questions dont le verdict a changé** (régressions en premier), car ce sont elles qui expliquent un écart de métrique.

### 6.3 Rapport de comparaison à quatre systèmes (F14)

Le rapport est le livrable de M3 ; il doit répondre en un coup d'œil à « qu'est-ce qui m'apporte quoi ? ».

Structure :

1. **Verdict en une phrase** (ex. : « Le RAG apporte +27 points d'exactitude ; le fine-tuning seul +4 ; combiner les deux +29. »).
2. **Tableau principal** : une ligne par système, colonnes exactitude, recall@k, fidélité, latence moyenne, mémoire.

   | Système | Exactitude | Recall@5 | Fidélité | Latence |
   |---|---|---|---|---|
   | Base seule | 0,31 | — | — | 1,2 s |
   | Base + RAG | 0,58 | 0,78 | 0,81 | 2,9 s |
   | Fine-tuné | 0,35 | — | — | 1,2 s |
   | Fine-tuné + RAG | 0,60 | 0,78 | 0,84 | 3,0 s |

3. **Écarts incertains signalés** : avec un jeu de 20 à 50 questions, un écart de 1–2 questions n'est pas significatif. Le rapport affiche le nombre de questions et l'effectif derrière chaque pourcentage (`0,62 = 31/50`), et marque « écart non concluant » sous un seuil.
4. **Cas parlants** : 3 questions où les systèmes divergent le plus, avec les quatre réponses côte à côte.
5. **Reproduction** : la commande exacte et les identifiants de run source.

Le rapport indique toujours quelle partie du verdict repose sur un **LLM juge** et quelle partie sur des règles (risque du PRD §8), avec un lien vers l'échantillon à relire manuellement.

## 7. Messages d'erreur et cas limites

Format unique : **quoi** → **pourquoi** → **que faire**.

```
✖ Mémoire insuffisante pour l'entraînement
  Modèle : Llama-3.1-8B (4 bits) · batch 8 · estimé 21 Go, disponible 14 Go
  Essayez : --set finetune.batch_size=2   ou   un modèle 3B (voir configs/finetune-3b.yaml)
```

| Situation | Comportement attendu |
|---|---|
| Config invalide | Erreur avec fichier, ligne, valeur reçue, valeurs acceptées ; code 2. |
| Données absentes | Indique le dossier attendu et la commande qui le produit (`rag ingest`). |
| Index obsolète (documents ou config d'embedding modifiés) | Avertissement avec la cause ; ne reconstruit pas sans demande explicite. |
| Mémoire insuffisante | Détection **avant** l'entraînement (estimation) ; suggestions chiffrées. |
| Modèle non téléchargé | Annonce la taille du téléchargement avant de le lancer. |
| Run déjà existant au même nom | Refuse d'écraser ; propose un autre nom ou `--force`. |
| Interruption `Ctrl-C` | Sortie propre, état partiel sauvegardé, run marqué `interrompu` dans `meta.json`. |
| Collision de graine non fixée | Avertit que le run n'est pas rejouable et pourquoi. |

Les traces d'exception complètes vont dans `log.txt` ; le terminal ne montre que le message actionnable (la trace complète avec `-v`).

## 8. Notebooks

Les notebooks servent à **explorer et comprendre**, pas à exécuter la chaîne de référence (qui reste en CLI, reproductible).

- **Un notebook par question d'apprentissage** (ex. : « comment le chunking change-t-il le recall ? »), pas par module.
- **Structure fixe** : question, hypothèse, config utilisée, résultat, conclusion en une phrase.
- **Ils appellent le code des modules** (`from rag import …`) plutôt que de dupliquer la logique : un résultat de notebook doit pouvoir être reproduit par une config.
- **Sorties effacées avant commit** (sauf exemples synthétiques), pour ne jamais versionner de données personnelles (PRD §5).
- Les graphiques réutilisent les mêmes fonctions que le rapport (`eval.plots`) pour un rendu cohérent.

## 9. Accessibilité et confort

- **Contraste et daltonisme** : ne jamais coder une information par la seule couleur ; les graphiques utilisent des motifs ou marqueurs distincts en plus des teintes.
- **Largeur de terminal** : mise en page correcte à 80 colonnes ; les tableaux tronquent proprement.
- **Lecteurs d'écran** : sorties textuelles linéaires, sans dessins ASCII indispensables à la compréhension.
- **Langue** : messages et documentation en français ; noms de commandes, clés de config et identifiants de code en anglais.

## 10. Critères de réussite UX

| Critère | Mesure |
|---|---|
| Premier résultat rapide | De `git clone` à une première évaluation (M0) en **moins de 10 minutes**, avec une seule commande de setup. |
| Rejouabilité | Rejouer un run produit des métriques identiques (ou l'écart est expliqué dans le rapport). |
| Erreur actionnable | Chaque erreur fréquente de §7 donne une action corrective sans lire le code. |
| Lisibilité du rapport | Le verdict de M3 se comprend sans ouvrir `outputs.jsonl`. |
| Découvrabilité | `--help` de chaque commande contient un exemple copiable. |

## 11. Questions ouvertes

| Question | Impact | Piste |
|---|---|---|
| Bibliothèque CLI : `typer`, `click` ou `argparse` ? | Qualité de l'aide et des erreurs vs. nombre de dépendances | `typer` si l'aide générée vaut la dépendance ; sinon `argparse` (principe de simplicité). |
| Affichage riche (`rich`) ou texte brut ? | Barres de progression et tableaux vs. dépendance | Commencer en texte brut, ajouter `rich` si la lecture devient pénible. |
| Une UI légère (Gradio/Streamlit) pour `ask` et `chat` ? | Confort d'exploration vs. non-objectif du PRD | Hors périmètre v0.1 ; à reconsidérer après M3 si la CLI freine l'exploration. |
| Seuil de signification dans le rapport | Évite les fausses conclusions sur 20–50 questions | Commencer par un simple intervalle binomial, affiner avec la taille du jeu. |
