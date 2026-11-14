# Portail d'orchestration IA — C1 : boucle de dev jusqu'à la PR : design

Date : 2026-11-14 · Statut : à approuver par Nicolas
S'appuie sur : la spec C complète (`2026-11-14-portail-c-boucle-dev-design.md`, dite « la spec C »),
A et B (construits, fusionnés et déployés).

Ce document ne réécrit pas la spec C : il **découpe** C en C1 puis C2, et **remplace** quelques décisions.
Tout ce qui n'est pas mentionné ici reste comme dans la spec C, pour la partie qui tombe dans C1.

## Intention

La même que celle de la spec C. Les tâches *Prêtes* deviennent seules des PR en brouillon. Un agent écrit les
tests sans pouvoir toucher au code, un autre écrit le code sans pouvoir toucher aux tests, et Nicolas relit et
fusionne. **C1 s'arrête à la PR ouverte.** Le but de C1 est aussi de vérifier, sur un vrai dépôt, que les
modèles locaux arrivent à enchaîner tests → code, avant d'investir dans la reprise sur commentaires (C2).

## Découpage

**Dans C1 :**
- La config d'exécution du projet (`image`, `chemins_tests`, `config_tests`, `commandes`, `services`), comme dans la spec C.
- Le **lanceur réduit** (voir plus bas).
- Les outils d'espace : ceux de B, plus `ecrire`, `supprimer`, `lancer`, avec la règle de rôle.
- Les agents `agent_tests`, `agent_code`, `agent_revue`, et le pipeline `dev` : tests → rouge → code → suite complète
  → revue (au plus 2 renvois) → PR en brouillon.
- La troisième protection avant chaque push.
- La GitHub App, la vérification de la protection de la branche par défaut, le push et la PR.
- L'ordonnanceur (rang + dépendances + verrou, `paralleles_max` = 1).
- Annuler, *Bloquée* en première exécution, relance sur une branche neuve, reprise une fois après un redémarrage.
- Le **suivi minimal des PR** : fusionnée → *Terminée* (verrou levé, espace supprimé) ; fermée sans fusion → *À faire*
  (verrou levé, branche gardée). Sans ça, les dépendances ne se débloquent jamais.
- L'interface : le bloc de config d'exécution dans les réglages du projet, le détail d'un pipeline `dev`
  (appels d'outils, sorties de `lancer` repliées, commits, lien de la PR), et l'avertissement sur le kanban
  quand le projet n'a pas de config d'exécution. **Par sondage**, comme aujourd'hui.
- Le déploiement : le service lanceur dans la pile `portail`, le volume des espaces, les nouveaux secrets dans
  `MAP`, et une **PR en brouillon dans l'Infra** pour `run-net` et sa sortie squid.

**Reporté à C2 :**
- La reprise sur les commentaires de Nicolas (agent de tri, réponses sous les commentaires, échec d'une reprise
  qui revient *En revue*), avec `PORTAIL_GITHUB_PROPRIETAIRE`.
- Les notifications ntfy.
- Le passage au flux d'événements (SSE) pour le kanban et la liste des pipelines. Le détail d'un pipeline garde
  le SSE existant de A/B pour ses étapes.

En C1, une PR *En revue* qui reçoit des commentaires ne déclenche rien : Nicolas corrige lui-même, ou ferme
la PR et remet la tâche dans *Prête*.

## Décisions qui remplacent la spec C

### 1. Le lanceur ne fait que l'exécution (décidé par Nicolas)

Dans la spec C, le lanceur Rust faisait aussi les opérations sur les fichiers et git. En C1 :

- **Le portail** monte le volume des espaces (`portail-espaces`) et fait lui-même :
  - les opérations de fichiers, en **étendant les outils de B** (`outils.py`) avec `ecrire` et `supprimer` et la règle
    de rôle. Les règles de chemin n'existent donc qu'à un endroit, en Python ;
  - les opérations git (clone, branche, commit, diff, fusion de `origin/<branche_ref>`, push), avec le git durci de B
    (`GIT_CONFIG_NOSYSTEM`, `GIT_CONFIG_GLOBAL=/dev/null`, `core.hooksPath=/dev/null`, refs passées sans risque d'injection
    d'options). Le jeton d'installation est passé comme en B (`http.extraHeader`), jamais écrit sur le disque.
  - **Le portail n'exécute jamais rien de ce que les agents écrivent.** git ne lance aucun hook ni filtre venu du dépôt
    (pas de `.gitattributes` avec un filtre défini dans une config que l'agent contrôle : la config est hors de l'espace
    et `.git/` est interdit aux agents).
- **Le lanceur** (Rust, seul à tenir le socket Docker) ne fait que :
  - `lancer` : un conteneur jetable durci (toutes les règles de la spec C et des « contraintes globales » du plan C :
    utilisateur 1000, aucune capacité, `no-new-privileges`, limites, `run-net`, proxy, pas de secret, délai, sortie tronquée),
    avec le sous-chemin de l'espace monté sur `/travail` ;
  - pour le rôle `code`, les montages en lecture seule des dossiers de tests. Le portail lui envoie la liste des
    sous-dossiers à protéger (ceux des motifs `<dossier>/**` qui existent) ; le lanceur vérifie que chacun est un chemin
    relatif sans `..` ;
  - les services de tests d'une tâche (réseau `internal` privé à la tâche, images de services en liste permise) ;
  - arrêter tout ce qui appartient à un espace, et supprimer le dossier d'un espace.
  - Il refuse quoi que demande le portail : image hors liste, montage de l'hôte, privilégié, réseau de l'hôte, autre réseau.
- **Les globs de fichiers** de `chemins_tests` ∪ `config_tests` (ceux qui ne sont pas des dossiers entiers, comme
  `**/conftest.py`) sont protégés **par le portail** autour de chaque `lancer` en rôle `code` : empreinte SHA-256 avant,
  comparaison après, restauration (`git checkout --` ou suppression) et `violation` renvoyée à l'agent.
- **Propriété des fichiers** : le portail et les conteneurs de commande tournent avec le même uid (1000), pour que
  tous deux puissent écrire dans l'espace.

### 2. GitHub App (décidé par Nicolas)

Comme dans la spec C : une GitHub App propre au portail, Contents et Pull requests en écriture, Metadata en lecture,
sans Administration, installée par Nicolas sur les dépôts choisis. Deux nouveaux secrets dans OpenBao `infra/portail`,
ajoutés à `MAP` : `PORTAIL_GITHUB_APP_ID` et `PORTAIL_GITHUB_APP_CLE` (clé privée PEM). Le portail en tire des jetons
d'installation d'une heure. **Le jeton en lecture seule de B reste** pour la planification. *(Choix de Claude : B n'a pas à
changer pour C1.)*

### 3. Ce qu'une étape a le droit de commiter *(choix de Claude, après relecture)*

La règle de rôle des outils ne suffit pas : une commande `lancer` peut écrire n'importe où dans `/travail`.
Le portail fait donc la règle au moment du commit :
- **étape tests** : seuls les chemins de `chemins_tests` ∪ `config_tests` sont commités ; tout autre changement
  (fichier suivi modifié ou fichier non suivi et non ignoré) est **annulé** avant le commit, et l'agent en est informé ;
- **étape code** : tout est commité sauf les chemins de tests, qui sont de toute façon en lecture seule ou restaurés ;
  la troisième protection reste en filet ;
- **artefacts** : le portail écrit dans `.git/info/exclude` de l'espace les dossiers d'outils courants
  (`.venv/`, `node_modules/`, `__pycache__/`, `.pytest_cache/`, `target/`, `dist/`, `.ruff_cache/`), pour qu'ils ne soient
  jamais commités même si le `.gitignore` du dépôt les oublie.

### 4. L'image d'exécution *(choix de Claude, après relecture)*

`devbox-session` est construite sur le démon de l'Infra (sans registre), contient Claude Code, `gh` et sshd, et n'a que
Python 3.11, alors qu'EA demande Python 3.12. L'image d'exécution est donc **construite dans ce dépôt**
(`execution/Dockerfile` : Python 3.12, Node 22, `uv`, `git`, utilisateur `agent` d'uid 1000, rien d'autre) et publiée
sur GHCR par le workflow de déploiement, à côté de l'image du portail. Le lanceur ne télécharge que les images de sa
liste permise. La PR Infra se réduit à `run-net` et à sa sortie squid.

### 5. Autres réglages *(choix de Claude, après relecture)*

- `paralleles_max` = 1 compte pour **tout le portail** (l'hôte a peu de mémoire). Entre projets, l'ordonnanceur prend
  la tâche *Prête* de plus petit `(rang, id)`.
- **Trois** nouveaux secrets dans OpenBao `infra/portail` et dans `MAP` : `PORTAIL_GITHUB_APP_ID`,
  `PORTAIL_GITHUB_APP_CLE` et `PORTAIL_LANCEUR_SECRET` (au moins 32 caractères, partagé portail ↔ lanceur).
- Le portail passe à l'uid 1000. Les clones de B dans `/donnees` ne sont qu'un cache, mais un uid 1000 sans root ne
  peut pas reprendre l'ancien volume : la pile monte un **volume neuf** (`portail-donnees-2`), l'ancien reste orphelin.
- Le portail, qui monte le volume des espaces, supprime lui-même le dossier d'un espace ; le lanceur ne monte pas ce volume
  (il le désigne par son nom) et ne fait que nettoyer conteneurs et réseau de services.
- `.git` est **toujours** monté en lecture seule dans les conteneurs de commande : sinon une commande pourrait planter un
  hook ou une option de `.git/config` que le git du portail exécuterait.
- La clé de la GitHub App est rangée **en base64 sur une ligne** (`vault-render-env.sh` refuse les retours à la ligne).
- Après un renvoi de la revue aux tests, la vérification « rouge » est sautée : le code existe déjà, des tests ajoutés
  peuvent légitimement passer.
- Un **plan C1 neuf** remplace le plan C pour C1. Ses valeurs (délais, limites, auteurs, branches, durcissement des
  conteneurs) sont reprises du plan C, sauf là où ce document le contredit.

## Ce qui reste comme dans la spec C (pour C1)

Config d'exécution et `config_tests` (dont le refus des sections de tests des manifestes par la troisième protection),
noms de branches, auteurs des commits, un commit par étape réussie, jamais de force-push ni de rebase, vérification
« rouge » (« aucun test écrit » est un blocage distinct de « les tests passent déjà »), limites (`tours_max`, délai par
commande, durée maximale de tâche), redémarrage, annuler, *Bloquée*, relance sur branche neuve (avec fermeture de l'ancienne
PR ouverte), contenu de la PR, refus de démarrer sans branche par défaut protégée, premier dépôt visé : EA.

## Changements dans l'Infra (PR en brouillon, non fusionnée par Claude)

- `run-net` : réseau `internal`, séparé de `dev-net`.
- Une sortie squid pour `run-net` qui ne laisse passer que les registres de paquets (PyPI, npm, crates.io) et GitHub
  en lecture, sans `s3:8333` ni adresse privée.

- Le provisionnement des secrets.

Le lanceur et le volume des espaces sont dans la pile `portail` de ce dépôt ; seul le lanceur monte le socket Docker.
L'hôte doit avoir Docker 26 ou plus (montage de sous-chemin de volume).

## Laissé au constructeur

Comme dans la spec C : prompts des agents, schéma JSON de la revue, forme exacte de l'API du lanceur, valeurs par défaut,
format de la PR, tests. Pour les tests, la liste de la spec C s'applique, moins le suivi des commentaires (C2), plus :
- la règle de rôle dans les outils Python (dont un lien symbolique vers `tests/` en rôle `code`) ;
- la restauration des globs de fichiers protégés après un `lancer` en rôle `code` ;
- le refus, par le lanceur, d'un chemin de montage en lecture seule absolu ou avec `..`.

## Risque connu

L'appel d'outils et `json_schema` de qwen3.8 à travers LiteLLM n'ont jamais été vérifiés en vrai (recommandation de la
revue finale de B). C1 en dépend entièrement. À vérifier au premier déploiement, sur une tâche simple d'EA.
