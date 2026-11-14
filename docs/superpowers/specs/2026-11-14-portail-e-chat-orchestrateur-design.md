# Portail d'orchestration IA — E : chat avec l'orchestrateur : design

Date : 2026-11-14 · Statut : brouillon, à approuver par Nicolas
S'appuie sur : A, B et C (`2026-11-14-portail-{socle,b-plan-taches,c-boucle-dev}-design.md`). **Se construit une fois C fusionné sur `main`** (décision de Nicolas).

## Intention

Aujourd'hui, on ne parle au modèle qu'à l'intérieur d'une étape de pipeline, rattachée à un projet.
Nicolas veut **une porte d'entrée unique** : un chat **libre, hors projet**, où il parle à « l'orchestrateur »
pour poser des questions au modèle, écrire des specs, et **faire agir le portail** (créer un projet, y
déposer une spec, lancer un pipeline, agir sur le kanban), **chaque action n'ayant lieu qu'après sa confirmation**.

## Objectifs

Construit en **deux temps**, livrables séparément :

**Temps 1 — l'orchestrateur répond.**
1. Une page **Chat** dans le menu : la liste des conversations, une conversation à la fois, réponses en streaming.
2. Les conversations sont **enregistrées** et survivent à un redémarrage, sans projet ni pipeline.
3. L'orchestrateur répond aux questions générales et rédige des specs dans la conversation.
4. Il **lit l'état du portail** par des outils : projets, pipelines, tâches du kanban, spec courante d'un projet.

**Temps 2 — l'orchestrateur agit, avec confirmation.** Quatre actions :
1. **Créer un projet**, et y **déposer une spec** écrite dans le chat.
2. **Lancer un pipeline** (`spec`, `planification`…) sur un projet.
3. **Agir sur le kanban** : créer une tâche, la modifier, la déplacer, l'annuler.
4. **Démarrer une tâche `dev`**.

## Non-objectifs

- Pas de chat d'étape remplacé ni modifié : `ChatEtape.vue` et `ServiceChat` restent tels quels.
- Pas d'outils de lecture de dépôt (`lister`, `lire`, `chercher`) dans ce chat : il n'a pas de dépôt. Pour lire un dépôt, on passe par un pipeline.
- Pas de choix du modèle dans l'interface : le modèle est celui de l'agent `orchestrateur` dans `agents.yaml`.
- Pas de partage de conversations : un seul utilisateur, Nicolas.
- Pas de suppression de projet ni de pipeline par le chat.

## Anti-objectifs

- **Une action exécutée sans un clic de Nicolas.** Même si le modèle insiste, même après un redémarrage.
- **Un orchestrateur qui invente un état** : il ne parle des projets, pipelines et tâches qu'à partir de ce que ses outils renvoient (même règle que le PM de D).
- **Une confirmation qui ne dit pas ce qu'elle fait** : la carte montre l'action et ses paramètres exacts, tels qu'ils seront exécutés.
- **Un second chemin d'écriture** qui contourne les règles du portail : les actions passent par les mêmes fonctions que les routes (`creer_pipeline`, `creer_tache`, `deplacer_tache`…), avec leurs verrous, leurs refus et leur journal.

## Contraintes

- Celles de A et B : FastAPI + SQLAlchemy async + Postgres, migrations Alembic (`backend/migrations`), Vue 3 + TypeScript, SSE, LiteLLM par `ClientLLM`.
- **E se construit après la fusion de C** (décision de Nicolas). C réécrit `boucle.py`, `agents.py`, `outils.py`, `chat.py`, `api.py` et `db.py` : E part de leur version fusionnée et peut les modifier librement, en gardant le chat d'étape intact.
- Modèle local (`qwen3.8:27b-mlx` par défaut) : appels d'outils parfois mal formés, contexte limité (`contexte_max`).

## Approches envisagées

- **A. Les conversations ont leur propre modèle — retenue par Nicolas.** Nouvelles tables, nouveau service, nouvelles routes, qui réutilisent les briques indépendantes des étapes (`ClientLLM`, `FiltreReflexion`, la jauge de contexte, le `Diffuseur`, le rendu markdown). Le chat d'étape est intact, aucun conflit avec C. Coût : un peu de code de chat en double.
- **B. Une conversation = un pipeline caché** dans un projet fictif « Hors projet ». Presque pas de code nouveau, mais un faux projet pollue la liste des projets, le kanban et les pipelines, et il faut tordre les états d'étape (une conversation ne se valide jamais). Écartée.
- **C. Généraliser `Message`** (`etape_id` optionnel + `conversation_id`) et découper `ServiceChat`. Une seule table, mais il faut retoucher `ServiceChat` et ses tests pendant que C les modifie : conflits presque garantis. Écartée.

## Ce qui est décidé

### Données

- `conversation` : `id`, `titre` (le début du premier message, modifiable), `etat` (`pret | en_cours | erreur`), `erreur`, `cree_le`, `maj_le`.
- `message_conversation` : `id`, `conversation_id` (cascade), `role` (`user | assistant | system | tool`), `contenu`, `outil` (libellé de l'appel, comme `Message.outil`), `cree_le`.
- *(Temps 2)* `action_conversation` : `id`, `conversation_id`, `nom`, `parametres` (JSON), `etat` (`proposee | confirmee | refusee | echouee | perimee`), `resultat` (texte renvoyé au modèle), `lien` (vers ce qui a été créé), `cree_le`, `maj_le`. La carte se place dans le fil selon `cree_le`.
- Une migration Alembic par temps.

### Agent

Un agent `orchestrateur` dans `agents.yaml`, avec un prompt système en français : il répond aux questions, aide à écrire des specs
(mêmes règles que l'agent `spec` : une question à la fois, pas de rédaction avant qu'on la demande), ne parle de l'état du portail
qu'à partir de ses outils, et propose une action plutôt que de prétendre l'avoir faite.
`Agent.outils` accepte de nouveaux noms (ceux du portail, ci-dessous). Le catalogue refuse qu'un agent mélange outils de dépôt et outils du portail.

### Outils de lecture (temps 1)

S'exécutent directement, sans confirmation :
- `lister_projets()` ; `lire_projet(projet_id)` (avec la spec courante) ;
- `lister_pipelines(projet_id?, etat?)` ; `lire_pipeline(pipeline_id)` (étapes et états) ;
- `lire_kanban(projet_id)`.

Ils réutilisent les requêtes des routes existantes et renvoient un texte compact, borné en taille comme les outils de dépôt.

### Actions (temps 2)

Chaque action est un **outil** dont l'appel ne fait rien d'autre qu'enregistrer une `action_conversation` à l'état `proposee`.
Les paramètres sont validés **au moment de la proposition** (projet existant, type de pipeline connu, colonne valide…) : une
proposition invalide revient tout de suite au modèle comme une erreur d'outil, sans carte.

| Outil | Ce qu'il fait une fois confirmé |
|---|---|
| `creer_projet(nom, description, depot_url?, branche_ref?)` | comme `POST /api/projets` (même `_verifier_depot`) |
| `deposer_spec(projet_id, contenu)` | ouvre un pipeline `spec` sur le projet, écrit `contenu` dans le document de son étape **à l'état `validee`** et termine l'étape (comme `ServiceChat.valider`). La spec devient la spec courante : `lancer_pipeline(planification)` passe tout de suite |
| `lancer_pipeline(projet_id, type)` | `creer_pipeline` + lancement de l'étape auto, comme `POST /api/pipelines` |
| `creer_tache(projet_id, titre, description, criteres, depend_de)` | `creer_tache` (colonne *À faire*) |
| `modifier_tache(tache_id, …champs)` | `modifier_tache` |
| `deplacer_tache(tache_id, colonne)` | `deplacer_tache`, en fin de colonne |
| `annuler_tache(tache_id)` | comme `POST /api/taches/{id}/annuler` |

**Démarrer une tâche `dev`** n'est pas un outil à part : dans C, l'ordonnanceur démarre seul toute tâche *Prête*. Démarrer une tâche,
c'est donc `deplacer_tache(tache_id, "prete")`. Comme E se construit après C, l'action marche dès le premier jour.

**Déroulement :**
1. Le modèle appelle un outil d'action → l'action est enregistrée `proposee`, le **tour s'arrête** : le modèle reçoit comme résultat
   « action proposée, en attente de la confirmation de Nicolas » et doit finir sa réponse sans appeler d'autre outil.
2. Le chat affiche une **carte** : l'action en clair, ses paramètres exacts, et deux boutons *Confirmer* / *Refuser*. Pour `deposer_spec`, la carte montre **la spec en entier** (rendue en markdown) : confirmer, c'est la valider (décision de Nicolas).
3. *Confirmer* → `POST /api/actions/{id}/confirmer` exécute l'action dans une transaction, avec l'auteur `"nicolas"` dans le
   journal des tâches. Le résultat (ou le refus du portail, ex. « une planification est déjà en cours ») est enregistré dans l'action et
   ajouté à la conversation comme message `tool`, puis le modèle est relancé pour commenter le résultat.
4. *Refuser* → l'action passe `refusee`, un message `tool` « Nicolas a refusé » est ajouté, et le modèle est relancé.
5. Si Nicolas écrit un nouveau message alors qu'une action est encore `proposee`, elle passe `perimee` (la carte se grise) : une
   action ne s'exécute jamais hors du fil où elle a été proposée.
6. Une action se confirme **une seule fois** : la transition `proposee → confirmee` est conditionnelle en base (verrou de ligne), un
   double clic ou deux onglets ne l'exécutent pas deux fois.

### Service et routes

- `ServiceConversation` (nouveau module `conversations.py`), sur le modèle de `ServiceChat` : une tâche de fond par tour, diffusée en SSE,
  avec **sa propre instance de `Diffuseur`** (les identifiants de conversation et d'étape se recouvrent).
- Boucle d'outils : on réutilise `boucle_outils` si elle accepte un exécuteur d'outils quelconque. Sinon, on la généralise par un ajout
  (un paramètre exécuteur), sans changer son comportement pour les étapes.
- Routes : `GET/POST /api/conversations`, `GET/PATCH/DELETE /api/conversations/{id}`, `POST /api/conversations/{id}/messages`,
  `GET /api/conversations/{id}/flux`, et au temps 2 `POST /api/actions/{id}/confirmer|refuser`.
- Redémarrage : un tour en cours est perdu et marqué en erreur, comme une étape (A). Les actions `proposee` restent confirmables.

### Interface

- Lien **Chat** dans l'en-tête de `App.vue`, route `/chat` et `/chat/:id`.
- Colonne de gauche : *+ Nouvelle*, puis les conversations par `maj_le` décroissante. À droite : les messages (markdown), les appels
  d'outils repliés comme dans `ChatEtape.vue`, la jauge de contexte, la zone de saisie.
- *(Temps 2)* Les cartes d'action, dans le fil, avec leur état. Une action exécutée affiche un lien vers ce qu'elle a créé (projet, pipeline, kanban).

### Tests

- Backend : LiteLLM simulé (comme `test_chat.py`) pour le streaming, la persistance, les outils de lecture ; pour chaque action :
  proposition valide/invalide, confirmation, refus, péremption, double confirmation, refus du portail transmis au modèle.
- Frontend : la logique de la carte d'action et de la liste de conversations, au niveau de ce que testent déjà `flux.test.ts` et `kanban.test.ts`.

### Choix de Claude, après relecture

- **Streaming** : même comportement que le chat d'étape. Les tours avec outils passent par `completer` (non streamé), chaque appel
  d'outil s'affiche au fil de l'eau, et le texte final arrive d'un bloc. `llm.py` ne change pas : streamer les appels d'outils serait
  fragile avec qwen, qui les forme mal assez souvent.
- **Rejeu de l'historique** : comme dans le chat d'étape, on ne rejoue d'un tour à l'autre que les messages `user`, `assistant`
  et `system` ; les messages `tool` ne servent qu'à l'affichage. Le sort d'une action (confirmée, refusée, refusée par le portail)
  est ajouté comme message `system` en clair (« Action n°12 (creer_projet) confirmée par Nicolas : projet 7 créé »). Pas d'ids
  d'appels à stocker, et l'historique reste valide après une confirmation ou un redémarrage.
- **Auteur d'une action confirmée** : `"nicolas"`, puisque c'est son clic. La tâche est donc protégée, comme si Nicolas avait fait
  la modification lui-même, et l'agent de planification ne peut pas l'écraser. La trace « venu du chat » est la ligne `action_conversation`.
- **`deposer_spec` sur un projet qui a déjà un pipeline `spec` ouvert** : refus à la proposition (« un pipeline de spec est déjà
  ouvert : finis-le ou annule-le »). Il n'y a jamais deux specs concurrentes.
- **Outils de lecture partagés avec D** : ils vivent dans un module `outils_portail.py`, que le PM de D réutilisera tel quel au lieu
  d'en définir un second jeu. Leurs noms sont ceux de ce document.

## Laissé au constructeur

- Le texte exact du prompt système et des descriptions d'outils.
- La forme du texte renvoyé par les outils de lecture, tant qu'il est compact et borné.
- Le découpage en tâches et en commits, et le détail du composant Vue.
- Le titre automatique d'une conversation (début du premier message par défaut).
