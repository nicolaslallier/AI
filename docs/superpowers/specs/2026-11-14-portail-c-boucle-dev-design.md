# Portail d'orchestration IA — C : boucle de dev : design

Date : 2026-11-14 · Statut : brouillon, à approuver par Nicolas
S'appuie sur : A (`2026-11-14-portail-socle-design.md`) et B (`2026-11-14-portail-b-plan-taches-design.md`),
**supposés construits et fusionnés.**

## Intention

Que les tâches *Prêtes* du kanban deviennent, **sans intervention de Nicolas**, des
**PR en brouillon, une par tâche**, avec des tests écrits d'abord par un agent qui ne peut écrire
que des tests, et du code écrit ensuite par un agent qui **lit les tests sans pouvoir les modifier**. Nicolas
relit chaque PR. S'il laisse des commentaires, les agents reprennent le travail sur la même PR. S'il fusionne,
la tâche est terminée. Ça doit pouvoir tourner seul, la nuit.

## Objectifs

1. Un **ordonnanceur** prend les tâches *Prêtes* une par une et lance pour chacune un pipeline `dev`.
2. Le pipeline `dev` déroule : **tests → vérification qu'ils échouent → code → suite complète au vert → revue**, avec des
   renvois possibles, puis **ouvre une PR en brouillon**.
3. Les agents travaillent dans un **bac à sable isolé**, sur le modèle des dev sessions (`devbox`) de l'Infra.
4. **La séparation tests / code est imposée** par trois protections indépendantes.
5. Le portail **suit les PR** : il relance la boucle sur les commentaires de Nicolas, et marque la tâche *Terminée* quand sa PR est fusionnée.
6. Nicolas est **notifié** (ntfy) quand une PR est ouverte, quand une tâche est bloquée et quand une reprise est terminée.

## Non-objectifs (pour C)

- Pas de fusion automatique : seul Nicolas fusionne.
- Aucun shell libre pour les agents (voir Approches).
- Les agents transversaux (sécurité, architecte, challenger, documentation, PM) sont pour D.
- Pas de webhooks GitHub : le homelab n'est pas exposé, on interroge l'API à intervalles réguliers.
- Pas de plusieurs tâches en parallèle au départ (le nombre est un réglage, à 1).
- **Premier dépôt visé : EA** (FastAPI/PostgreSQL/MinIO + Vue/TS). Les premières images d'exécution sont donc Python et Node, et les services
  de tests Postgres et MinIO. Les images Rust (Moria, avec Bevy, gourmand en mémoire) et le cas de Final (macOS/Metal, peut-être pas testable
  dans un conteneur Linux) viendront plus tard, selon la mémoire disponible sur le Docker du homelab (environ 7,7 Go en tout).

## Anti-objectifs

- Un agent de code qui modifie, supprime ou contourne un test, d'une façon ou d'une autre.
- Du code produit par un modèle qui s'exécute hors de la cage : sur l'hôte, avec accès au socket Docker, au réseau du homelab, ou à un secret.
- Un jeton capable de fusionner, de changer les protections de branche ou de pousser sur la branche par défaut.
- Une tâche construite sur du code que Nicolas n'a pas encore accepté.
- Une boucle qui tourne sans fin et use les modèles toute la nuit.

## Contraintes

- Celles de A et B. La boucle d'outils, le confinement des chemins et la jauge de contexte de B sont **réutilisés et étendus**, pas réécrits.
- **Modèle d'isolation de l'Infra (dev sessions)** : le réseau `dev-net` est `internal` et n'a aucune route. La seule sortie est le proxy squid
  `dev-egress`, avec une liste de destinations permises (GitHub, crates.io, npm, PyPI). L'image `devbox-session` contient les outils.
  Ne **jamais** donner le socket Docker brut au portail. L'Infra le signale déjà pour Prefect : quiconque le tient est root sur l'hôte.
- **GitHub : une GitHub App propre au portail**, installée sur les dépôts choisis, avec Contents et Pull requests
  en écriture, Metadata en lecture, et **sans** Administration. Le portail utilise les jetons d'installation de courte durée de l'App.
  *(Choix de Claude, à la suite de la relecture. Avec le jeton personnel de Nicolas, les PR et les réponses seraient signées
  « Nicolas » : il ne pourrait pas demander des changements sur ses propres PR, et le filtre « commentaires de Nicolas » attraperait les réponses
  du portail. Un compte machine ne peut pas avoir de jeton à grain fin sur des dépôts personnels.)* Le portail vérifie au
  démarrage que la branche par défaut de chaque dépôt est protégée, en échouant par défaut dans le doute. Le jeton en lecture seule de B peut lui aussi être remplacé par l'App.

## Approches envisagées

**Où tourne le code des agents.**
1. **Un conteneur jetable par commande, sur `dev-net` et le modèle devbox, piloté par un petit service lanceur. Retenue.**
   L'isolation est déjà conçue et vérifiée dans l'Infra. Coût : il faut un intermédiaire restreint pour créer
   les conteneurs, et une PR dans l'Infra.
2. **La CI GitHub Actions comme bac à sable.** Écartée : plusieurs minutes par essai, une branche pleine de commits d'essai,
   et les runners auto-hébergés exécutent de toute façon ce code sur l'hôte.
3. **Le socket Docker dans le portail.** Écartée : le portail serait root sur l'hôte, piloté par un modèle sans surveillance.

**Ce que peuvent faire les agents.**
1. **Pas de shell libre. Retenue.** Les outils sont `lister`, `lire`, `chercher`, `ecrire`, `supprimer` (avec les règles de chemin par rôle),
   et `lancer(<nom>)`, qui ne lance qu'une commande déclarée pour le projet. On sait ce qui peut s'exécuter, et ça cadre avec des modèles
   locaux qui appellent les outils de façon inégale.
2. **Un shell libre.** Écarté : il multiplie les façons de contourner la séparation tests / code.

## Ce qui est décidé

### Config d'exécution du projet

Dans les réglages du projet, un bloc YAML est **édité dans le portail**, pas versionné dans le dépôt cible.
*(Choix de Claude : on ne touche pas les dépôts pour configurer le portail.)*

- `image` : l'image d'exécution, prise dans une liste permise par le lanceur (par défaut, l'image dérivée de `devbox-session`).
- `chemins_tests` : des motifs (`tests/**`, `**/*_test.py`, `**/*.spec.ts`…). Pour Rust : `tests/**` seulement,
  donc l'agent de tests n'écrit que des tests d'intégration qui passent par l'interface publique (accepté par Nicolas).
- `commandes` : un dictionnaire nom → commande. Au minimum `installer`, `tests` (la suite complète), et `tests_cibles`
  (un gabarit qui reçoit les fichiers de tests de la tâche). En option : `lint`, `build`.
- `services` (optionnel) : des conteneurs annexes nécessaires aux tests (par exemple `postgres:16-alpine` avec ses
  variables). Ils sont démarrés par le lanceur sur un réseau privé à la tâche, et détruits avec elle. *(Choix de Claude : DarkAngel et EA
  testent contre Postgres et le stockage S3.)*

- `config_tests` : les fichiers de configuration du harnais de tests, traités **comme des chemins de tests** (l'agent de code ne peut pas
  y écrire). Par défaut, selon le langage : `conftest.py` à tous les niveaux, `pytest.ini`, `jest.config.*`, `vitest.config.*`, `.cargo/config.toml`…
  Les manifestes (`pyproject.toml`, `package.json`, `Cargo.toml`) restent modifiables par l'agent de code, pour qu'il puisse ajouter des dépendances.
  En revanche, la troisième protection refuse tout changement fait par le rôle `code` dans leurs sections de tests (`[tool.pytest*]`, `jest`/`vitest`
  dans `package.json`, `[dev-dependencies]` et `[[test]]` dans `Cargo.toml`). *(Choix de Claude, à la suite de la relecture : sans ça, on pourrait faire
  passer les tests sans toucher `chemins_tests`.)*

Sans cette config, aucun pipeline `dev` ne démarre sur le projet, et le kanban le signale.

### Le lanceur (bac à sable)

C'est un petit service séparé, **le seul à tenir le socket Docker**, avec une API étroite que le portail appelle.
*(Choix de Claude : il est écrit en **Rust**. C'est un composant privilégié, critique pour la sécurité, qui doit rester petit et léger.
C'est le cas d'usage de Rust que Nicolas a décrit.)*

- **Espace de travail** : un volume par tâche, qui contient le clone sur la branche de la tâche.
- **Opérations sur les fichiers** (`lister`, `lire`, `chercher`, `ecrire`, `supprimer`) : c'est le lanceur qui les exécute dans le volume, en appliquant
  les règles de chemin de B **plus** la règle de rôle :
  - rôle `tests` : il ne peut écrire **que** dans `chemins_tests` ;
  - rôle `code` : il ne peut écrire **nulle part** dans `chemins_tests` ;
  - rôle `revue` : il ne peut rien écrire.
- **`lancer(nom)`** : un conteneur jetable (`--rm`), avec l'`image` du projet, sur `run-net` (sortie seulement par son squid),
  sans privilèges, sans capacités, en utilisateur non root, avec des limites de mémoire, de CPU et de temps, sans aucun secret, et avec le volume monté.
  **Pour le rôle `code`, les chemins de tests sont remontés en lecture seule** par-dessus le volume. La sortie, tronquée, et le code de
  retour sont renvoyés.
- **Paramètres refusés quoi que demande le portail** : une image hors de la liste permise, un montage de l'hôte, le mode privilégié, le réseau de l'hôte,
  un réseau autre que `run-net` ou celui des services de la tâche.
- **Authentification** : le portail présente un secret partagé. Le lanceur n'est joignable que depuis le portail,
  sur un réseau dédié, et ne publie aucun port.

### Git et GitHub (le portail, jamais les agents)

- Branche : `portail/tache-<id>-<slug>`, créée depuis `origin/<branche_ref>` au début de la tâche.
- **Un commit par étape réussie**, avec un auteur propre au rôle (`agent-tests`, `agent-code`). Le portail les fait dans le volume
  à travers le lanceur, avec les commandes git du lanceur et non avec `lancer`.
- **Troisième protection** : avant chaque push, le portail vérifie que les commits **des agents de rôle `code`** ne touchent aucun
  chemin de tests ni aucune config de tests (voir `config_tests`). Si c'est le cas, la tâche passe à *Bloquée*, sans push. Les commits de Nicolas
  ne sont pas vérifiés.
- **Jamais de force-push, jamais de rebase.** Avant une reprise, le portail récupère la branche, y compris les commits que Nicolas
  aurait poussés lui-même, puis il **fusionne** `origin/<branche_ref>` dedans. Si cette fusion produit un conflit, la tâche revient *En revue*, avec un
  commentaire sur la PR qui demande à Nicolas de le résoudre. *(Choix de Claude.)*
- Le push et l'ouverture de la PR en brouillon se font avec le jeton d'écriture, qui ne quitte jamais le portail. La PR contient
  le lien vers la tâche et vers le pipeline, les critères d'acceptation, le résumé de la revue et les remarques
  non résolues s'il y en a.

### Ordonnanceur

- Une boucle dans le processus serveur, réveillée à intervalles réguliers et à chaque changement du kanban.
- Il prend, dans l'ordre du rang, la première tâche *Prête* qui n'est **pas protégée par un verrou** et dont **toutes les dépendances sont *Terminées***, c'est-à-dire
  dont les PR sont fusionnées. Il pose le verrou, passe la tâche à *En cours* et lance le pipeline `dev`.
- Au plus `paralleles_max` pipelines `dev` en même temps (1 au départ).
- *(Choix de Claude : l'ordonnanceur est une **règle fixe** (rang + dépendances), pas un agent. Le choix de la
  prochaine tâche ne demande aucun jugement de modèle tant que Nicolas ordonne son kanban. Un agent
  planificateur pourra s'ajouter en D, par exemple pour proposer un ordre, si le besoin apparaît.)*

### Pipeline `dev`

Le type `dev` = `[agent_tests, agent_code, agent_revue]`, avec des renvois. Chaque agent travaille par la boucle d'outils de B,
à travers le lanceur.

1. **Tests** : l'agent reçoit la tâche (description, critères, fichiers indicatifs), le point de départ du dépôt et les outils
   (rôle `tests`, plus `lancer`). Il écrit les tests.
   **Vérification « rouge »** : `tests_cibles` doit **échouer**. S'il réussit, on renvoie une fois à l'agent avec ce constat,
   puis la tâche passe à *Bloquée*.
2. **Code** : l'agent reçoit la tâche, **lit les tests** (lecture seule), la sortie de l'échec et les outils (rôle `code`, plus
   `lancer`). Il écrit le code jusqu'à ce que `tests_cibles` passe, puis `tests` (la suite complète) doit passer. Au-delà de `tours_max`
   sans y arriver, la tâche passe à *Bloquée*.
3. **Revue** : l'agent reçoit le diff complet de la branche et la tâche (rôle `revue`, lecture seule). Il répond en JSON :
   `ok`, `renvoyer_tests` ou `renvoyer_code`, avec ses remarques. Un renvoi relance l'étape concernée avec les remarques. Si les tests changent,
   le code est revérifié. Au plus **2 renvois**. Au-delà, la PR est quand même ouverte avec les remarques non
   résolues bien en vue, puisque Nicolas relit de toute façon.
4. **PR** : push et ouverture en brouillon. La tâche passe à *En revue*, et le verrou **reste** posé (voir le suivi des PR).

**Limites**, toutes réglables : `tours_max` par agent, une durée maximale par commande `lancer`, une durée maximale par tâche. Le dépassement de l'une d'elles
fait passer la tâche à *Bloquée*, avec un résumé de ce qui a été essayé, écrit sur la tâche. L'ordonnanceur passe alors à la suivante.

**Redémarrage du serveur** pendant un pipeline : l'étape interrompue est relancée **une fois** automatiquement, depuis le dernier
commit. Si elle est interrompue une deuxième fois, la tâche passe à *Bloquée*.

### Suivi des PR

On interroge GitHub à intervalles réguliers (quelques minutes) pour chaque tâche *En revue* :
- **PR fusionnée** : la tâche passe à *Terminée*, le verrou est levé et le volume de la tâche est supprimé.
- **PR fermée sans fusion** : la tâche revient dans *À faire*, le verrou est levé, et la branche et la PR restent.
- **Nouveaux commentaires ou demande de changements de Nicolas**, et de lui seul (filtrés par son identifiant GitHub). Les commentaires des bots et
  des autres personnes sont ignorés. La tâche repasse à *En cours* et un pipeline `dev` de reprise démarre sur la **même branche**.
  - Un agent de tri (le rôle de revue, avec une consigne de tri) classe chaque commentaire en *tests* ou *code*. L'étape tests ou
    code concernée tourne avec les commentaires, puis la suite complète, puis la revue.
  - Le portail pousse les nouveaux commits et répond sous chaque commentaire traité.
  - Les mêmes protections s'appliquent : un commentaire sur un test est traité par l'agent de tests, jamais par l'agent de code.

### Annuler et Bloquée

*(Choix de Claude, à la suite de la relecture.)*

- **« Annuler »** sur une tâche verrouillée arrête la commande en cours (le lanceur tue le conteneur) et termine le pipeline
  (`echouee`, « annulé »). La tâche revient dans *À faire*, le verrou est levé et le volume est supprimé. La branche est gardée.
- **Bloquée pendant une première exécution** (avant la PR) : le verrou est levé, la tâche devient modifiable et le volume est supprimé. La branche est gardée,
  et le résumé de l'échec est écrit sur la tâche.
- **Reprendre** une tâche annulée ou bloquée, c'est-à-dire la remettre dans *Prête*, repart toujours d'une **branche neuve**,
  `portail/tache-<id>-<slug>-<n>`. Si une ancienne PR de cette tâche est encore ouverte, le portail la ferme avec un commentaire qui renvoie vers la nouvelle.
- **Échec d'une reprise sur commentaires** (la PR existe déjà) : la tâche **revient *En revue*** au lieu de passer à *Bloquée*. Le portail
  explique l'échec en commentaire sur la PR et notifie Nicolas, qui peut commenter de nouveau, corriger lui-même ou fermer la PR.

### Suivi et notifications

- Maintenant que des étapes tournent seules, la liste des pipelines et le kanban passent du sondage à un **flux d'événements** (SSE),
  comme A l'avait prévu.
- Le détail d'un pipeline `dev` montre chaque appel d'outil, chaque commande `lancer` avec sa sortie repliée, et chaque commit.
- **ntfy**, déjà dans l'Infra (`make ntfy-provision app=portail`) : une notification quand une PR est ouverte, quand une tâche est *Bloquée*, et quand une reprise sur commentaires est terminée.

### Changements dans l'Infra (PR séparée)

- Le service lanceur (son image vient du dépôt `AI`), un réseau dédié portail ↔ lanceur, et le socket Docker monté **dans le lanceur seulement**.
- **Un réseau d'exécution à part, `run-net`**, `internal` comme `dev-net` mais **séparé** de lui. Les conteneurs du lanceur ne
  voient donc ni les dev sessions (qui tiennent des jetons et des identifiants Claude) ni rien d'autre. Sa sortie passe par un **squid à lui**
  (ou une ACL séparée sur `dev-egress`) qui laisse passer seulement les registres de paquets (crates.io, npm, PyPI) et le **clonage GitHub en lecture**, **sans** `s3:8333`
  ni aucune adresse privée. *(Choix de Claude, à la suite de la relecture : `dev-net` laisse les sessions se joindre entre elles et passe par s3.)*
- L'image d'exécution, dérivée de `devbox-session`.
- Le provisionnement ntfy et les secrets : le jeton GitHub d'écriture et le secret portail ↔ lanceur.
- `scripts/dev-isolation-check.sh` doit pouvoir vérifier aussi un conteneur du lanceur.

## Laissé au constructeur

- Les prompts des trois agents et de l'agent de tri, et le schéma JSON de la revue.
- La forme de l'API du lanceur, et la façon de faire les opérations git dans le volume.
- Les valeurs par défaut des limites et des intervalles de sondage.
- Le format exact de la PR et des réponses aux commentaires.
- Les tests. Au minimum, pour le lanceur :
  - le refus de chaque paramètre dangereux, et l'application des règles de rôle ;
  - le montage en lecture seule des tests pour le rôle `code`, vérifié par une écriture qui échoue ;
  - pas de réseau hors de squid.

  Pour le portail :
  - la troisième protection (le diff des commits `code`) ;
  - le choix de l'ordonnanceur (rang, dépendances, verrou) ;
  - le cycle complet d'un pipeline `dev` avec un LiteLLM et un lanceur simulés, y compris le cas « rouge » qui réussit et les renvois de la revue ;
  - le suivi des PR (fusion, fermeture, commentaires de Nicolas et des autres).
