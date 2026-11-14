# Portail d'orchestration IA — Socle (A) : design

Date : 2026-11-14 · Statut : brouillon, à approuver par Nicolas

## Intention

Nicolas repart de zéro pour gérer ses IA. À terme, il veut un **portail web**
d'où il lance et suit des **pipelines** : une suite d'étapes confiées chacune à un
**agent** qui passe par son LiteLLM. La chaîne visée :

spec (chat) → plan → tableau de tâches → planificateur → agent de tests
(limité au répertoire de tests) → agent de code (ne voit pas le répertoire de
tests, seulement les tests à faire passer) → revue ; plus des agents
transversaux : sécurité, PM (lui parle), architecte, challenger, documentation.

C'est trop gros pour un seul projet. On le découpe :

- **A. Socle** (ce document) : portail, moteur de pipeline, suivi, un seul agent : le chat de spec.
- **B.** Spec → plan → tableau de tâches.
- **C.** Boucle de dev : planificateur, tests, code, revue, dépôt isolé, droits par agent.
- **D.** Agents transversaux, surtout de la config une fois C en place.

**But de A** : prouver la chaîne de bout en bout, de l'interface jusqu'au suivi
en passant par l'agent LiteLLM, sans encore toucher à un dépôt de code. Tout ce qui
est construit ici doit servir tel quel à B, C et D.

## Objectifs

1. Créer un **projet** (nom et description courte).
2. Lancer un **pipeline de spec** sur un projet. Sa seule étape est un chat avec l'agent de spec.
3. Discuter avec l'agent. Ses réponses s'affichent au fil de l'eau (streaming).
4. Demander à l'agent de **rédiger la spec** à partir de la conversation. Elle
   est rangée dans le portail en markdown, et Nicolas peut la relire et la corriger dans l'interface.
5. **Valider** la spec, ce qui termine l'étape et donc le pipeline.
6. **Suivre** les pipelines : une liste avec l'état de chacun (en cours, en
   attente de Nicolas, terminé, échoué), et pour chaque pipeline le détail de ses étapes et
   l'historique complet des échanges.
7. Définir les agents dans un **fichier YAML** (rôle, prompt système, modèle
   LiteLLM). Ajouter ou modifier un agent ne demande pas d'écrire de code.

## Non-objectifs (pour A)

- Aucun accès git ni aucune écriture dans un dépôt : la spec reste dans le portail. L'export vers un dépôt viendra en B ou C.
- Aucun outil pour les agents (fichiers, shell), aucune boucle d'agent : en A, un agent fait un appel au modèle.
- Pas de plan, de tableau de tâches ni d'autres agents que celui de spec.
- Pas de multi-utilisateur, de rôles ni de partage : Nicolas est le seul utilisateur.
- Pas de file d'attente ni de worker en arrière-plan.
- Pas de Rust (voir Contraintes).

## Anti-objectifs (échec même si ça « marche »)

- Un moteur de pipeline écrit pour un seul agent, qu'il faudra réécrire en B. Le
  modèle projet → pipeline → étape → agent doit déjà accepter plusieurs étapes et plusieurs agents.
- Des agents codés en dur dans le Python.
- Un outil lié à un framework d'agents avant qu'on sache ce dont C a besoin.
- Une spec ou une conversation perdue quand LiteLLM tombe ou quand la page se recharge.

## Contraintes

- **Pile** : frontend Vue 3 + TypeScript, backend Python (FastAPI), Postgres.
  Rust seulement plus tard, pour une fonction lourde dont on aura *mesuré* le
  besoin, afin de garder une empreinte légère. A n'en a pas.
- **LiteLLM** : `https://litellm.infra.famillelallier.net` (depuis le réseau
  `infra-net` : `http://litellm:4000`), API compatible OpenAI, clé bearer propre au
  portail. Modèles disponibles aujourd'hui : `qwen3.8:27b-mlx`,
  `mlx-community/GLM-4.7-Flash-8bit`. Ce sont des modèles locaux, donc lents et avec un contexte limité.
- **Hébergement** : le homelab, déployé par Portainer comme les autres apps.
  - Base : `make provision-app app=<nom>` dans l'Infra (base et rôle dédiés).
  - Accès : vhost NGINX en HTTPS. Le vhost doit suivre le modèle `resolver 127.0.0.11` + `set $upstream`.
  - Authentification : une porte Keycloak par oauth2-proxy + `auth_request`, la même recette que Jarvis (voir `Infra/keycloak/CLAUDE.md`).
- **Dépôt** : `nicolaslallier/AI`, vide depuis la PR #17 (README seul).

## Approches envisagées

1. **Tout fait maison, simple. Retenue.** FastAPI + Postgres + Vue. Le serveur
   appelle LiteLLM et relaie le flux à la page en SSE. L'état des pipelines vit en base. Les agents sont décrits en YAML.
   Pas de worker. Coût : on écrit un petit moteur d'états nous-mêmes. Retenue parce
   qu'elle fait exactement ce que A doit prouver avec le moins de pièces possible.
2. **Prefect, déjà dans l'Infra.** On aurait l'état, les relances et l'historique sans rien écrire. Mais une étape
   de chat avec un humain cadre mal avec Prefect, et le portail referait une partie de son interface.
   À reconsidérer en C pour les tâches de dev longues qui tournent seules.
3. **Un framework d'agents dès le départ** (PydanticAI, LangGraph…). A n'en
   utilise rien, et ce choix lierait l'outil tôt à un framework qui bouge vite et se tient parfois mal avec les modèles
   locaux. À reconsidérer en C.

Le moteur maison de l'approche 1 doit pouvoir, plus tard, confier une étape à
un framework ou à un flow Prefect sans être refait.

## Ce qui est décidé

### Modèle de données (Postgres)

- `projet` : id, nom, description, créé_le.
- `pipeline` : id, projet_id, type (`spec` pour A), état, créé_le, maj_le.
- `etape` : id, pipeline_id, ordre, agent (nom de l'agent dans le YAML), état, erreur (texte, nullable).
- `message` : id, etape_id, rôle (`user` / `assistant` / `system`), contenu, créé_le.
- `document` : id, projet_id, pipeline_id, etape_id, type (`spec` en A ; `plan` en B), contenu markdown, état (`brouillon` / `validee`), maj_le. *(Table générique plutôt qu'une table `spec` : B y range aussi le plan, avec le même mécanisme brouillon → validé.)*

**États d'étape et de pipeline** : `a_faire` (pas encore démarrée), `en_cours`,
`en_attente` (l'agent a répondu, c'est à Nicolas), `terminee`, `echouee`. L'état d'un pipeline se déduit de ses
étapes : échoué si une étape a échoué ; sinon en attente si une étape attend Nicolas ;
sinon terminé si toutes sont terminées ; sinon en cours. *(Choix de Claude :
ajout de `a_faire`.)*

**Enchaînement** : quand une étape passe à `terminee`, le moteur démarre
automatiquement la suivante. Un *type* de pipeline n'est pour l'instant qu'une
liste ordonnée d'agents. En A, `spec = [agent_spec]`, mais l'enchaînement
doit être écrit et testé avec un type à deux étapes, déclaré seulement dans les tests. *(Choix de Claude.)*

**Specs d'un projet** : un projet peut avoir plusieurs pipelines de spec. Une
spec validée est figée. La spec « courante » d'un projet est la dernière validée,
les autres restent en historique. C'est celle-là que B lira. Pour changer une
spec validée, on lance un nouveau pipeline de spec. *(Choix de Claude.)*

### Agents (YAML)

Un fichier `agents.yaml` est versionné dans le dépôt et lu au démarrage. Pour chaque agent :
`nom`, `description`, `modele` (nom côté LiteLLM), `prompt_systeme`, et
`temperature` en option, `contexte_max` (en jetons). Les types de pipeline sont déclarés dans le même fichier, sous
forme de liste d'agents. Une erreur dans le fichier fait échouer le démarrage avec un message clair.

### Déroulement du chat de spec

1. Nicolas envoie un message. Il est enregistré **avant** l'appel au modèle,
   l'étape passe à `en_cours`, et le serveur appelle LiteLLM (`/v1/chat/completions`,
   `stream=true`) avec le prompt système et tout l'historique de l'étape.
2. La réponse est relayée à la page en SSE. Une fois complète, elle est
   enregistrée et l'étape passe à `en_attente`.
3. Le bouton **« Rédiger la spec »** envoie à l'agent une consigne fixe : produire
   la spec en markdown à partir de la conversation. Le résultat crée ou remplace
   le brouillon de `document` (type `spec`) du pipeline.
4. Nicolas corrige le markdown dans l'interface et l'enregistre. Il peut aussi
   continuer la discussion et faire rédiger la spec de nouveau.
5. Le bouton **« Valider »** fige la spec (`validee`) et passe l'étape, puis le pipeline, à `terminee`.

**Rechargement et coupure** : l'appel à LiteLLM ne tourne pas dans la requête
SSE. Il tourne dans une tâche asyncio du processus serveur, qui enregistre la
réponse elle-même une fois complète. La page s'y abonne en SSE. Si elle se recharge pendant le flux, elle
retrouve l'état depuis la base et se réabonne. Ce n'est pas un « worker » au sens
des non-objectifs : pas de file d'attente ni de processus séparé. Au démarrage du serveur, une
étape laissée `en_cours` par un arrêt passe à `echouee` (« interrompue »), et on peut la relancer
avec « Réessayer ». La réponse partielle n'est pas enregistrée. *(Choix de Claude.)*

**Contexte limité (décision de Nicolas)** : tant qu'il n'y a pas de brouillon,
l'agent reçoit le prompt système et toute la conversation. Dès qu'un brouillon de
spec existe, il reçoit le prompt système, le **brouillon courant** (y compris les corrections de
Nicolas) et seulement les messages écrits **après** sa dernière rédaction. La conversation complète reste
enregistrée et affichée. Une **jauge** montre la part du contexte du modèle utilisée.
Elle s'appuie sur une limite de contexte déclarée pour chaque agent dans le YAML (`contexte_max`), avec une estimation
grossière des jetons. Passé un seuil, elle invite à cliquer « Rédiger la spec ». À
la limite, l'envoi est refusé avec ce même conseil. Jamais d'oubli silencieux.

**Raisonnement des modèles** : les blocs `<think>…</think>` (Qwen3) sont retirés
de la réponse. Ils ne sont ni affichés, ni gardés dans l'historique, ni mis dans la spec. *(Choix de Claude.)*

**En cas d'erreur** (LiteLLM injoignable, délai dépassé, flux coupé) : l'étape
passe à `echouee` avec le message d'erreur. Le message de Nicolas est déjà
enregistré, il n'est donc pas perdu. Un bouton **« Réessayer »** relance l'appel et
remet l'étape en cours.

### Interface (Vue)

- **Pipelines** (page d'accueil) : la liste des pipelines, avec projet, type, état,
  date de dernière mise à jour, et un filtre par état. Bouton « Nouveau pipeline » (choix ou création du projet).
- **Détail d'un pipeline** : les étapes et leur état. Pour l'étape de chat : la conversation,
  la zone de saisie, les boutons « Rédiger la spec » et « Réessayer », et l'éditeur
  markdown de la spec avec un aperçu et le bouton « Valider ».
- **Projets** : la liste des projets et, pour chacun, ses pipelines et sa spec validée.

**Suivi en direct** : le chat se met à jour par SSE. La liste des pipelines se rafraîchit
par sondage toutes les 5 s. On passera à un flux d'événements quand des étapes tourneront seules (en C).

### Authentification

C'est oauth2-proxy devant le portail qui s'en charge. L'app fait confiance à
l'en-tête d'utilisateur que lui transmet NGINX, et n'a donc pas de code de connexion à elle.
En développement local, il n'y a pas de porte.

### Livraison

- Le dépôt `AI` contient `backend/` (FastAPI, uv, migrations Alembic),
  `frontend/` (Vue 3 + Vite + TS), `agents.yaml`, et un `Dockerfile` par partie ou
  un seul s'il suffit. Le frontend compilé peut être servi par le backend.
- Comme pour DarkAngel : la CI construit les images et les pousse sur GHCR
  (`ghcr.io/nicolaslallier/…`). Portainer déploie la pile
  `deploy/portainer-stack.yml`, versionnée dans ce dépôt, qui tire ces images. *(Choix de Claude.)*
- **Les changements dans l'Infra** (vhost NGINX, oauth2-proxy + client Keycloak,
  provisionnement de la base, clé LiteLLM du portail) font l'objet d'une **PR séparée
  dans le dépôt Infra**. Elle fait partie du plan comme dernière tâche, en brouillon et sans
  fusion. Le vhost est aussi versionné dans `deploy/nginx/` ici, comme le fait DarkAngel.

## Laissé au constructeur

- Le nom de l'app, du service et du sous-domaine (proposition : `portail`, `portail.infra.famillelallier.net`).
- La structure interne du backend et du frontend, les bibliothèques (client HTTP, éditeur markdown, rendu).
- Le contenu exact du prompt de l'agent de spec et de la consigne « Rédiger la spec ».
- La forme des endpoints et des événements SSE.
- La stratégie de tests. Elle doit au minimum couvrir la transition d'états, le chargement
  du YAML, le chat avec un LiteLLM simulé, y compris en cas d'erreur, et la persistance avant l'appel.
- La CI (GitHub Actions) : lint et tests du backend et du frontend.
