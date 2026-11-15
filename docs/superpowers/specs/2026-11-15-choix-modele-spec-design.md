# Choisir l'IA de la spec — design court

## Intention

Nicolas veut choisir l'IA qui l'aide à écrire une spec (par exemple `gemma4:26b-a4b-it-qat`
plutôt que `qwen3.8:27b-mlx`), au moment où il commence la conversation de spec du pipeline.

## Objectifs

- Un menu déroulant en tête du chat de l'étape `spec`, visible tant que l'étape n'a aucun message.
- Choix possibles : `modeles_permis` de `agents.yaml` ; présélection : le `modele` de l'agent.
- Au premier envoi, le choix est enregistré sur l'étape et ne change plus ; le menu devient un libellé.
- Tous les appels faits pour cette étape (réponses, rédaction, boucle d'outils, conteneur
  d'agent) utilisent le modèle choisi.

## Non-objectifs

- Changer de modèle en cours de conversation (approche C écartée).
- Choisir le modèle au lancement du pipeline (approche B écartée).
- Un menu pour les autres étapes (plan, tâches, dev) : elles sont automatiques.

## Approches

- **A (retenue)** : colonne `modele` sur `etape`, fixée au premier message.
- B : choix dans la fenêtre de lancement du pipeline — pas l'endroit voulu.
- C : modifiable à tout moment — historique repris par un autre modèle, « qui a écrit la spec » devient flou.

## Le comment

- **Base** : migration `0010` ajoute `etape.modele` (texte, nullable). Vide = modèle de `agents.yaml`.
- **Substitution unique** : une fonction dans `agents.py` rend l'agent d'une étape avec
  `model_copy(update={"modele": etape.modele})` si renseigné. `chat.py` (`_agent`) et
  `avis.py` (l'auteur, pour que `modele_pour` évite au challenger le modèle réellement utilisé)
  passent par elle.
- **API** : `envoyer` accepte un `modele` optionnel. Pris en compte seulement au premier message ;
  refusé (422) s'il n'est pas dans `modeles_permis`. `EtapeOut` expose `modele` (effectif) et la
  liste `modeles_permis` est fournie à l'écran (via l'endpoint qui sert déjà le catalogue, ou `EtapeOut`).
- **Écran** : `ChatEtape.vue` affiche le `<select>` si l'agent est `spec` et qu'il n'y a aucun message,
  sinon « IA : <modele> ».
- **Config** : ajouter `gemma4:26b-a4b-it-qat` à `modeles_permis`.

## Contraintes / hors dépôt

- La clé LiteLLM du portail (dépôt Infra) doit autoriser `gemma4:26b-a4b-it-qat`, sinon LiteLLM refuse.
- `contexte_max` reste celui de l'agent (32768) : la jauge ne s'adapte pas au modèle choisi.
  Choix du builder : acceptable tant que les modèles permis ont au moins ce contexte.

## Laissé au builder

- Où exposer `modeles_permis` à l'écran (endpoint existant ou champ d'`EtapeOut`).
- Tests : un test serveur (modèle choisi utilisé, refus hors liste, figé après le premier message)
  et un test du composant.
