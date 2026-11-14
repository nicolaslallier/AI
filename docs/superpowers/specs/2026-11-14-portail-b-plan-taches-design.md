# Portail d'orchestration IA — B : spec → plan → kanban : design

Date : 2026-11-14 · Statut : brouillon, à approuver par Nicolas
S'appuie sur : `2026-11-14-portail-socle-design.md` (A). **On suppose que A est construit et fusionné avant que B commence.**

## Intention

Passer d'une spec validée à une liste de tâches que la boucle de dev (C) pourra
prendre une par une. Les projets de Nicolas sont **surtout ses dépôts existants**
(Moria, DarkAngel, EA…), et parfois des projets neufs. Un plan fait sans lire le
code serait vague ou faux. L'agent de plan doit donc **lire le dépôt**. Le
kanban sert aussi d'**outil de suivi à Nicolas** : il est entièrement éditable à la main,
pas seulement un affichage de ce que les agents produisent.

## Objectifs

1. Un projet peut être lié à un **dépôt GitHub** (URL et branche de référence), ou à aucun s'il est neuf.
2. Le portail tient une **copie du dépôt en lecture seule**, mise à jour (`git fetch`
   puis remise sur la branche de référence) avant chaque étape qui la lit.
3. Une **boucle d'agent avec outils**, en lecture seule : `lister`, `lire`, `chercher`. Elle sert à
   l'agent de plan, et aussi à l'agent de spec quand le projet a un dépôt.
4. **Étape de plan** : l'agent lit la spec validée et le dépôt, puis rédige un plan en
   markdown. Nicolas le relit, le corrige ou le commente, peut le faire réécrire, et le valide.
5. **Étape de tâches** : l'agent découpe le plan validé en tâches et les **propose**.
   Nicolas les accepte, les modifie ou les rejette. Une tâche acceptée entre dans le kanban.
6. Un **kanban éditable** par projet : créer, modifier, déplacer, réordonner, supprimer.
7. **Re-planifier** : si la spec ou le plan change, l'agent de tâches propose des
   ajouts et des modifications sans toucher aux tâches commencées ou terminées.

## Non-objectifs (pour B)

- Aucune écriture dans un dépôt, aucune branche, aucune PR : c'est C.
- Pas de planificateur ni d'exécution des tâches : c'est C.
- Pas de synchronisation avec les issues ou les Projects GitHub (approche écartée, voir plus bas).
- Pas de kanban multi-projets. Un tableau par projet. Une vue « toutes mes tâches »
  pourra venir plus tard.

## Anti-objectifs

- Une tâche modifiée par Nicolas pendant qu'un agent travaille dessus, sans que personne ne le sache.
- Une re-planification qui écrase une tâche commencée, terminée, ou modifiée à la main.
- Une boucle d'outils qui peut lire hors du dépôt (`../`, liens symboliques, `.git/`,
  fichiers de secrets) ou tourner sans fin.
- Une deuxième boucle d'agent écrite pour C. Celle de B **est** celle que C étendra avec des outils d'écriture.

## Contraintes

- Celles de A : Vue, FastAPI, Postgres, LiteLLM compatible OpenAI, modèles locaux au
  contexte limité, homelab et Portainer, une seule personne qui l'utilise.
- **Appel d'outils** : on utilise le format `tools` / `tool_calls` d'OpenAI à travers LiteLLM.
  Les modèles actuels (`qwen3.8:27b-mlx`, `GLM-4.7-Flash`) le supportent, mais de façon inégale selon le modèle.
- **Accès GitHub** : un jeton à grain fin, en **lecture seule** sur les dépôts choisis,
  rangé dans les secrets du portail (`.env` ou OpenBao, au choix de l'Infra). C ajoutera un jeton d'écriture séparé.

## Approches envisagées

**Où vit le kanban.**
1. **Dans le portail. Retenue.** Tout est au même endroit (tâches, pipelines, suivi),
   le verrou pendant qu'un agent travaille est simple à faire respecter, et ça marche sans dépôt. Coût : on écrit le kanban nous-mêmes.
2. **Issues GitHub et un GitHub Project.** Le kanban existe déjà, avec le mobile et le lien aux PR. Écartée : le suivi serait coupé
   en deux, l'API des Projects est lourde, il faudrait un dépôt même pour un projet neuf, et le verrou serait difficile à imposer.

**Comment l'agent lit le dépôt.**
1. **Une boucle d'outils maison, en lecture seule. Retenue.** On écrit une seule boucle, qui servira aussi
   à C, et on l'éprouve d'abord en lecture, là où une erreur ne casse rien. Coût : elle dépend de la fiabilité des modèles locaux pour appeler des outils.
2. **Un résumé du dépôt préparé d'avance et mis dans le contexte.** Fiable avec n'importe quel modèle, mais l'agent ne voit que ce
   qu'on a choisi pour lui. On le **garde comme point de départ** de la boucle (voir plus bas).
3. **Un framework d'agents.** Écarté pour les mêmes raisons qu'en A.

## Ce qui est décidé

### Projet et dépôt

- On ajoute à `projet` : `depot_url` (nullable), `branche_ref` (par défaut celle du dépôt).
- Le portail garde un clone de référence par projet dans un de ses volumes. Au **démarrage** d'une étape
  qui lit le dépôt, il fait un `fetch`, sous un verrou propre au projet, puis crée un **arbre de travail détaché, propre à
  l'étape**, sur le SHA de `origin/<branche_ref>`. Ce **SHA reste fixe pendant toute l'étape**, même
  si elle dure des jours ou si le plan est réécrit, et il est enregistré sur l'étape. Le plan indique ainsi sur quelle version du
  code il s'appuie. Pour lire du code plus récent, on lance un nouveau pipeline. L'arbre de travail est supprimé quand
  l'étape se termine ou échoue. *(Choix de Claude, à la suite de la relecture.)*
- Si le dépôt est injoignable, l'étape échoue avec un message clair. « Réessayer » fonctionne comme en A.

### Boucle d'agent avec outils

- Dans le YAML, chaque agent peut déclarer `outils: [lister, lire, chercher]` et
  `tours_max` (une valeur par défaut raisonnable, par exemple 20).
- **Déroulement** : on appelle le modèle avec les outils. S'il demande des
  `tool_calls`, on les exécute, on ajoute les résultats et on recommence. On s'arrête quand il répond sans outil ou quand `tours_max` est atteint.
  Dans ce dernier cas, on lui demande de conclure avec ce qu'il a, et l'étape le signale.
- **Les outils**, tous confinés au clone :
  - `lister(chemin)` : le contenu d'un dossier (pas récursif au-delà d'une profondeur raisonnable).
  - `lire(chemin, debut?, fin?)` : un fichier texte, tronqué au-delà d'une taille limite, avec la mention de la troncature.
  - `chercher(motif, chemin?)` : une recherche dans le texte (façon `git grep`), avec un nombre de résultats plafonné.
- **Garde-fous** : on résout le chemin et on refuse s'il sort du clone ou passe par `.git/`. On refuse
  les liens symboliques qui sortent du clone, les fichiers binaires et les fichiers de secrets connus (`.env*`, `*.pem`,
  `*.key`…). Les fichiers ignorés par git n'existent pas dans le clone, puisqu'il est propre.
- **Point de départ** : le premier message de l'agent contient un aperçu du dépôt (l'arborescence sur deux niveaux, le README,
  `CLAUDE.md` / `AGENTS.md` s'ils existent, et les manifestes : `pyproject.toml`, `package.json`, `Cargo.toml`…),
  dans la limite d'une part du contexte.
- **Suivi** : chaque appel d'outil et un extrait de son résultat sont enregistrés comme messages de l'étape
  (rôle `tool`). Le détail du pipeline les montre repliés, ce qui permet de voir ce que l'agent a lu.
- **Contexte** : les résultats d'outils comptent dans la jauge de A. Quand le contexte est presque plein, les
  résultats d'outils les plus anciens sont remplacés par « [résultat retiré : relire si besoin] ». C'est la seule
  forme d'oubli permise, parce que l'agent peut relire le fichier. Les messages de Nicolas et le document courant ne sont jamais retirés.
- **Un modèle qui ne gère pas les outils** (erreur de LiteLLM ou réponse mal formée de façon répétée) fait échouer l'étape
  avec un message qui le dit clairement. On ne fait pas de repli silencieux.

### Pipeline de planification

- Un nouveau type de pipeline, `planification = [agent_plan, agent_taches]`, lancé sur un projet
  qui a une spec validée. Le type `spec` de A ne change pas.
  *(Choix de Claude : deux pipelines séparés plutôt qu'un seul spec → plan → tâches. Ça permet
  de re-planifier sans refaire la spec.)*
- **Étape de plan** : c'est le même mécanisme de document que la spec en A (la table `document`, de type
  `plan`). L'agent produit le brouillon, Nicolas le corrige ou envoie des remarques (« refais en tenant compte de… »),
  puis le valide. Il reçoit la spec courante et le dépôt, à travers les outils.
- **Étape de tâches** : elle démarre automatiquement après la validation du plan. L'agent répond en **JSON structuré**
  (`response_format` avec un schéma). Le serveur valide le JSON. S'il est invalide, il redemande une fois en donnant l'erreur, puis l'étape
  échoue. Le résultat devient un ensemble de **propositions**.

### Tâches et kanban

- `tache` : id, projet_id, titre, description (markdown), criteres (liste), fichiers (liste,
  indicative), colonne, rang (ordre dans la colonne), origine (`agent` + document plan_id, ou `manuel`),
  protegee (booléen), verrou (pipeline_id nullable, posé par C), créée_le, maj_le.
- **`protegee`** passe à vrai, et n'en revient jamais, quand Nicolas crée la tâche à la main, modifie son **contenu** (titre,
  description, critères, fichiers, dépendances), ou modifie une proposition avant de l'accepter.
  Déplacer ou réordonner une carte **ne la protège pas**. Accepter telle quelle une proposition d'agent
  ne la protège pas non plus. *(Choix de Claude, à la suite de la relecture.)*
- `tache_dependance` : (tache_id, depend_de_id). On refuse les cycles.
- `tache_evenement` : un journal de chaque création, modification, déplacement et suppression, avec qui l'a fait (Nicolas ou tel agent).
- **Colonnes fixes** : *À faire* → *Prête* → *En cours* → *En revue* → *Terminée*, plus *Bloquée*.
  Nicolas déplace les tâches librement entre les colonnes qui ne sont pas verrouillées. Une dépendance pas encore terminée est
  signalée sur la carte mais ne bloque pas le déplacement. C'est le planificateur de C qui la respectera.
- **Verrou** : une tâche dont `verrou` est posé se lit mais ne se modifie pas, ni par Nicolas ni par un autre agent.
  L'API répond `409` avec le pipeline qui la tient. Seule action permise : **« Annuler »**, qui demande à C
  d'arrêter (le sens précis est défini par C). En B, rien ne pose de verrou, mais le refus et l'affichage doivent déjà exister.
- **Propositions** : une proposition est une tâche qui n'est pas encore entrée au tableau, affichée dans un panneau
  « Propositions » à côté du kanban. Il y a deux sortes :
  - *nouvelle tâche* : on peut l'accepter (elle entre dans *À faire*), la modifier puis l'accepter, ou la rejeter ;
  - *modification d'une tâche existante* (lors d'une re-planification) : un affichage avant/après, à accepter ou rejeter ;
  - *tâche devenue obsolète* (lors d'une re-planification) : l'agent propose de la retirer, avec sa raison.
    Si Nicolas accepte, elle est supprimée du tableau, et le journal la garde.
  Un bouton « Tout accepter » est disponible. L'étape de tâches est `en_attente` tant qu'il reste des
  propositions, puis `terminee`.
- **Re-planification** : on relance un pipeline `planification` sur un projet qui a déjà des tâches.
  - L'agent de plan **révise** le dernier plan validé : il reçoit la spec courante, ce plan et le dépôt, et il produit un plan complet.
  - L'agent de tâches reçoit le nouveau plan validé **et** les tâches existantes.
  - Il ne peut proposer que des nouvelles tâches, ou bien des modifications ou des retraits de tâches qui sont dans *À faire* ou *Prête*,
    **non protégées** et sans verrou. Le serveur refuse toute autre proposition, quoi que dise le modèle.
  - Si une tâche visée a changé entre la proposition et son acceptation, la proposition est marquée « périmée » et ne peut plus être acceptée.
  *(Choix de Claude : une tâche créée ou modifiée à la main par Nicolas n'est jamais modifiée par un agent.)*
- **Un seul pipeline `planification` actif par projet.** On ne peut pas en lancer un autre tant que le
  précédent n'est pas terminé. « Annuler » sur ce pipeline rejette les propositions qui restent et le passe à
  `echouee` (« annulé »). *(Choix de Claude, à la suite de la relecture.)*
- **Interface** : un glisser-déposer entre les colonnes et à l'intérieur d'une colonne. Un clic sur une carte ouvre l'édition
  (titre, description, critères, fichiers, dépendances). Un filtre par texte. Les mises à jour se font par sondage, comme la liste des pipelines en A.

### Agent de spec avec dépôt

Si le projet a un dépôt, l'agent de spec de A reçoit les mêmes outils en lecture seule et
le même point de départ. Rien d'autre ne change dans le chat de spec.

## Laissé au constructeur

- Les prompts des agents de plan et de tâches, et le schéma JSON exact d'une tâche proposée.
- Les limites exactes (taille de lecture, nombre de résultats, profondeur de `lister`, part du contexte pour le point de départ).
- La bibliothèque de glisser-déposer, et le calcul du rang (entiers espacés, fractions…).
- Comment `chercher` est implémenté (`git grep` en sous-processus, ou autre).
- Les tests. Au minimum : le confinement des chemins (traversée de dossiers, liens symboliques, `.git`, secrets), la boucle d'outils avec un
  LiteLLM simulé (arrêt à `tours_max`, appel mal formé), le verrou (`409`), les règles de re-planification
  (une tâche protégée ne peut pas être modifiée), et le refus des cycles de dépendances.
