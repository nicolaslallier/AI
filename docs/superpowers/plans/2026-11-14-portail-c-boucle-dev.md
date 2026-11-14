# Portail — C : boucle de dev : plan d'implémentation

> **Pour les agents qui exécutent :** SOUS-SKILL REQUIS : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans, tâche par tâche. Les étapes utilisent des cases `- [ ]`.

**But :** les tâches *Prêtes* du kanban deviennent seules des PR en brouillon, une par tâche. Les tests sont écrits d'abord par un agent qui ne peut écrire que des tests, puis le code par un agent qui lit les tests sans pouvoir les modifier. Le code s'exécute dans un bac à sable isolé. Le portail reprend le travail sur les commentaires de Nicolas.

**Architecture :**
- Un nouveau service **`lanceur`**, en Rust, dans `lanceur/`. C'est le seul à tenir le socket Docker. Il garde un espace de travail par tâche, applique les règles de chemin par rôle, fait les opérations git et lance des conteneurs jetables sur `run-net`.
- Côté portail (Python) :
  - un client du lanceur ;
  - des outils d'espace qui reprennent l'interface d'outils de B ;
  - un client GitHub App ;
  - un **orchestrateur `dev`** écrit comme une coroutine par pipeline, avec des phases enregistrées en base pour reprendre après un redémarrage ;
  - un ordonnanceur ;
  - un suivi des PR par sondage.

**Pile :**
- Lanceur : Rust (édition 2024), `axum`, `tokio`, `bollard` (API Docker), `globset`, `serde`, `subtle`, et `git` en CLI dans son image.
- Portail : celle de A et B, plus `pyjwt[crypto]` pour l'authentification de la GitHub App.

**Spec :** `docs/superpowers/specs/2026-11-14-portail-c-boucle-dev-design.md`. Ce plan s'appuie sur les plans de A (`…/plans/2026-11-14-portail-socle.md`) et de B (`…/plans/2026-11-14-portail-b-plan-taches.md`), dont il reprend les interfaces. **On suppose que A et B sont construits et fusionnés.**

## Contraintes globales

- Toutes les contraintes de A et B s'appliquent toujours.
- **Le portail ne parle jamais à Docker.** Seul le lanceur tient `/var/run/docker.sock`. Les agents n'ont **aucun shell libre** : `lancer` prend un **nom** de commande déclaré dans la config du projet, jamais une ligne de commande.
- **Lanceur** :
  - il écoute sur `0.0.0.0:8080` et ne publie aucun port ;
  - chaque requête, sauf `GET /sante`, porte `Authorization: Bearer <LANCEUR_SECRET>`, comparé en temps constant. Le lanceur refuse de démarrer si le secret fait moins de 32 caractères ;
  - ses variables : `LANCEUR_SECRET`, `LANCEUR_ESPACES` (par défaut `/espaces`), `LANCEUR_VOLUME` (le nom du volume Docker monté sur `/espaces`, par défaut `portail-espaces`), `LANCEUR_RESEAU` (par défaut `run-net`), `LANCEUR_PROXY` (par exemple `http://run-egress:3128`), `LANCEUR_IMAGES` et `LANCEUR_IMAGES_SERVICES` (listes permises, séparées par des virgules) ;
  - il demande Docker Engine **26 ou plus récent** (API 1.45, montage `VolumeOptions.Subpath`).
- **Conteneur de commande**, sans aucune exception :
  - `User: "1000:1000"`, `CapDrop: ["ALL"]`, `SecurityOpt: ["no-new-privileges"]`, `Privileged: false` ;
  - `Memory` vaut 2 GiB et `NanoCpus` 2e9 par défaut, `PidsLimit: 512` ;
  - `NetworkMode` = `LANCEUR_RESEAU`, avec en plus le réseau de services de la tâche s'il existe ;
  - `HTTP_PROXY` et `HTTPS_PROXY` = `LANCEUR_PROXY` ;
  - aucun autre montage que le sous-chemin de l'espace sur `/travail`, plus les montages en lecture seule de la règle de rôle, plus un `tmpfs` sur `/tmp` et `/home/agent` ;
  - aucune variable d'environnement venant du portail, sauf celles des services.
- **Délai par commande** : 600 s par défaut, 1800 s au plus. Au-delà, le conteneur est tué et la sortie se termine par `[délai dépassé : <n> s]`. On garde les **20 000 derniers caractères** de la sortie, précédés de `[… début coupé]` s'il y en avait plus.
- **Rôles** :
  - `tests` écrit **seulement** dans `chemins_tests` ∪ `config_tests` ;
  - `code` n'écrit **nulle part** dans `chemins_tests` ∪ `config_tests` ;
  - `revue` n'écrit rien ;
  - `systeme` (portail seulement, jamais exposé à un agent) peut écrire partout. Il sert à `installer`.

  Les motifs sont des globs `globset`, comparés au chemin relatif **après** résolution des liens symboliques.
- **Branche** : `portail/tache-<id>-<slug>`, puis `-<n>` à partir de la deuxième exécution. Le slug est le titre en minuscules, sans accents, `[a-z0-9-]`, coupé à 40 caractères.
- **Auteurs des commits** : `agent-tests <agent-tests@portail.local>`, `agent-code <agent-code@portail.local>`, `portail <portail@portail.local>` (fusions).
- **Jamais de force-push, jamais de rebase.** Le jeton d'installation de l'App ne transite qu'en mémoire, du portail vers le lanceur, dans le corps des requêtes. Il n'est ni écrit sur le disque, ni dans `.git/config`, ni dans les journaux.
- La branche par défaut d'un dépôt doit être **protégée** (`GET /repos/{o}/{r}/branches/{b}` → `protected: true`), sinon le pipeline `dev` refuse de démarrer. Toute erreur de cette vérification est un refus.
- **Limites par défaut** : `tours_max` 40 pour `tests` et `code` ; `renvois_max` 2 ; durée maximale d'une tâche 2 h ; `paralleles_max` 1. L'ordonnanceur tourne toutes les 30 s, le suivi des PR toutes les 120 s.
- Le seul compte dont les commentaires déclenchent une reprise est `PORTAIL_GITHUB_PROPRIETAIRE` (le login GitHub de Nicolas).
- **ntfy** : `PORTAIL_NTFY_URL`, `PORTAIL_NTFY_SUJET`, `PORTAIL_NTFY_JETON`. Si l'un d'eux est vide, aucun envoi, sans erreur.

## Points à surveiller en revue

1. **L'agent de tests n'écrit aucun test**, alors que `tests_cibles` « échoue » quand même (pytest renvoie 5, « no tests collected »). La tâche passe à *Bloquée* avec « aucun test écrit », pas à « rouge OK ». *Test : tâche 8.*
2. **Une commande qui ne rend jamais la main** (un serveur lancé dans les tests) : elle est tuée au délai, la sortie le dit, et l'espace reste utilisable. *Tests : tâche 3 (Docker) et tâche 8 (simulé).*
3. **Le rôle `code` qui écrit par un lien symbolique de l'espace pointant vers `tests/`** : l'écriture est refusée, parce que la règle de rôle s'applique au chemin résolu. *Test : tâche 1.*
4. **Plusieurs commentaires de Nicolas d'un coup, ou un commentaire modifié après coup** : chaque commentaire est traité une seule fois, et une reprise en cours n'est pas relancée. *Test : tâche 10.*
5. **Un redémarrage du portail en plein pipeline `dev`** : la phase en cours est reprise une fois, à partir de l'espace intact du lanceur. À la deuxième interruption, la tâche passe à *Bloquée*. *Test : tâche 9.*

---

### Task 1: lanceur, squelette, authentification et règles de chemin

**Fichiers :**
- Créer : `lanceur/Cargo.toml`, `lanceur/src/main.rs`, `lanceur/src/config.rs`, `lanceur/src/chemins.rs`, `lanceur/src/api.rs`
- Modifier : `.github/workflows/ci.yml` (job `lanceur`)

**Interfaces :**
- Produit, en Rust :
  - `struct Config { secret, espaces: PathBuf, volume, reseau, proxy, images: Vec<String>, images_services: Vec<String> }`, avec `Config::depuis_env() -> Result<Config, String>` (refus d'un secret de moins de 32 caractères).
  - `enum Role { Tests, Code, Revue, Systeme }`, désérialisé depuis `"tests" | "code" | "revue" | "systeme"`.
  - `struct Regles { chemins_tests: Vec<String>, config_tests: Vec<String> }`, avec `fn compiler(&self) -> Result<GlobSet, String>`.
  - `fn resoudre(racine: &Path, relatif: &str) -> Result<PathBuf, ErreurChemin>`. Elle refuse un chemin absolu, un composant `.git`, et un chemin qui sort de `racine` une fois canonicalisé. Pour un fichier qui n'existe pas encore, on canonicalise le parent existant le plus proche. Elle reprend aussi les **secrets** de B (`.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`), refusés en lecture comme en écriture.
  - `fn peut_ecrire(role: Role, relatif_resolu: &str, protege: &GlobSet) -> bool`.
  - `enum ErreurChemin { Interdit, Secret, RoleRefuse }`, affichée en français (« chemin interdit », « fichier de secrets », « écriture interdite pour le rôle <r> »).
  - Le routeur `axum` : `GET /sante` → `{"ok": true}`, et un middleware d'authentification sur tout le reste (`401 {"erreur": "non authentifié"}`).

- [ ] **Étape 1 : tests unitaires**, dans `chemins.rs` et `api.rs`, avec `tempfile` :
  - `resoudre_refuse` (paramétré à la main) : `../x`, `/etc/passwd`, `.git/config`, `a/../../x`, un lien `lien -> /etc` puis `lien/passwd`, `.env.prod`, `cle.pem` ;
  - `role_tests` : avec `chemins_tests = ["tests/**"]` et `config_tests = ["**/conftest.py"]`, `tests/test_a.py` et `src/conftest.py` sont permis, `src/a.py` est refusé ;
  - `role_code` : l'inverse exact du cas précédent ;
  - `role_revue_refuse_tout` ;
  - `role_code_lien_vers_tests` : `raccourci -> tests` puis l'écriture `raccourci/test_x.py` est refusée pour `code` ;
  - `secret_trop_court` : `Config::depuis_env` renvoie une erreur ;
  - `auth` : `GET /sante` sans en-tête donne 200. Une autre route sans en-tête, ou avec un mauvais secret, donne 401.
- [ ] **Étape 2 :** `cd lanceur && cargo test` échoue.
- [ ] **Étape 3 : implémenter.**
- [ ] **Étape 4 :** `cargo fmt --check && cargo clippy -- -D warnings && cargo test` donne PASS.
- [ ] **Étape 5 :** dans la CI, ajouter le job `lanceur` : `dtolnay/rust-toolchain@stable`, `Swatinem/rust-cache`, puis `cargo fmt --check`, `clippy -D warnings` et `cargo test`, dans `lanceur/`.
- [ ] **Étape 6 : commit** `feat(lanceur): squelette, authentification et règles de chemin par rôle`.

### Task 2: lanceur, espaces, fichiers et git

**Fichiers :**
- Créer : `lanceur/src/espaces.rs`, `lanceur/src/fichiers.rs`, `lanceur/src/git.rs`, `lanceur/tests/espaces.rs`
- Modifier : `lanceur/src/api.rs`

**Interfaces :**
- Un espace vit dans `<espaces>/<id>/travail` (le dépôt). Ses métadonnées (`Regles`, branche, base) sont dans `<espaces>/<id>/meta.json`, **hors** de `travail`. `id` doit correspondre à `^[a-z0-9-]{1,64}$`.
- Routes (en JSON). Une erreur renvoie `{"erreur": "<texte>"}` avec 400, 404, 409 ou 422 :
  - `POST /espaces {id, depot_url, jeton, base, branche, existante: bool, regles: Regles}`. Si `existante` est faux, on clone `base` puis on fait `checkout -b branche`. Sinon, on clone et on fait `checkout branche` (la branche distante existe). Si l'espace existe déjà, on obtient 409 ;
  - `POST /espaces/{id}/fichiers {role, op, chemin?, contenu?, debut?, fin?, motif?}`, avec `op ∈ lister|lire|chercher|ecrire|supprimer`. La réponse est `{"texte": …}`. Les limites et les messages sont **ceux de B** (lister, lire, chercher, binaire, `git grep`). Une écriture refusée pour le rôle donne 403 `{"erreur": "écriture interdite pour le rôle <r>"}` ;
  - `POST /espaces/{id}/git/commit {auteur_nom, auteur_courriel, message}` renvoie `{"sha": …}`, ou `{"sha": null}` s'il n'y a rien à commiter ;
  - `GET /espaces/{id}/git/commits?depuis=<rev>` renvoie `[{sha, auteur_courriel, fichiers: [str]}]` ;
  - `GET /espaces/{id}/git/diff?depuis=<rev>` renvoie `{"texte": …}`, tronqué à 200 000 caractères ;
  - `GET /espaces/{id}/git/fichier?rev=&chemin=` renvoie `{"texte": … | null}` ;
  - `POST /espaces/{id}/git/fusionner {jeton, base}` fait un `fetch`, puis `merge --no-edit origin/<base>` avec l'auteur `portail`. En cas de conflit, il fait `merge --abort` et renvoie 409 `{"erreur": "conflit", "fichiers": [...]}` ;
  - `POST /espaces/{id}/git/pousser {jeton}` fait un `push origin <branche>`, **sans** `--force`. Un refus de GitHub donne 409 ;
  - `GET /espaces/{id}/git/tete` renvoie `{"sha": …}`.
- Le jeton est passé par `git -c http.extraHeader=…`, comme en B, et retiré de toute sortie d'erreur.

- [ ] **Étape 1 : tests d'intégration** dans `lanceur/tests/espaces.rs`. L'origine est un dépôt nu local (`file://`), et on passe par le routeur avec `tower::ServiceExt::oneshot`, sans Docker :
  - `creer_puis_lire` ;
  - `ecrire_tests_role_code_403` ;
  - `commit_puis_commits_liste_auteur_et_fichiers` ;
  - `commit_sans_changement_sha_null` ;
  - `fusion_sans_conflit` ;
  - `fusion_en_conflit_409_et_espace_propre` (après le 409, `git status` est propre) ;
  - `pousser_sans_force` : quand l'origine a avancé sur la branche, on obtient 409 et l'origine n'est pas écrasée ;
  - `jeton_absent_des_fichiers` ;
  - `id_invalide_400`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** `cargo test` donne PASS, clippy OK.
- [ ] **Étape 5 : commit** `feat(lanceur): espaces de travail, opérations de fichiers et git`.

### Task 3: lanceur, conteneurs jetables, services et image

**Fichiers :**
- Créer : `lanceur/src/conteneurs.rs`, `lanceur/tests/docker.rs`, `lanceur/Dockerfile`
- Modifier : `lanceur/src/api.rs`, `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`

**Interfaces :**
- `fn specification(cfg: &Config, espace: &str, role: Role, regles: &Regles, travail: &Path, image: &str, commande: &str, reseau_services: Option<&str>) -> Result<bollard::container::Config<String>, String>`. C'est une fonction **pure** :
  - elle refuse une image hors de `cfg.images` ;
  - elle construit tous les réglages des contraintes globales, avec `Cmd = ["sh", "-c", commande]`, `WorkingDir = /travail` et le label `portail.espace=<espace>` ;
  - le montage principal est un `Mount { typ: VOLUME, source: cfg.volume, target: "/travail", volume_options: { subpath: "<espace>/travail" } }` ;
  - pour le rôle `code`, chaque motif de `chemins_tests` ∪ `config_tests` **qui finit par `/**` sans autre joker** (par exemple `tests/**`) ajoute un montage en lecture seule du sous-dossier correspondant, s'il existe ;
  - les autres motifs (des globs de fichiers) sont protégés par une **empreinte** : avant la commande, on calcule le SHA-256 de chaque fichier correspondant. Après, si un fichier a changé, été créé ou supprimé, on le restaure avec `git checkout -- <f>` (ou on le supprime s'il était nouveau), et la réponse porte `"violation": [fichiers]`.
- `POST /espaces/{id}/lancer {role, image, commande, delai_s}` renvoie `{"code": int | null, "sortie": str, "delai_depasse": bool, "violation": [str]}`. On a `delai_s ≤ 1800`, sinon 422. Le conteneur est créé, démarré et attendu avec `tokio::time::timeout`. Il est supprimé dans tous les cas (`force`).
- `POST /espaces/{id}/services {services: [{nom, image, env: {k: v}}]}` : il crée le réseau `portail-svc-<id>` (`internal: true`) et démarre les services sur ce réseau, avec l'alias `nom`. Une image hors de `images_services` donne 422.
- `POST /espaces/{id}/arreter` tue les conteneurs qui portent `portail.espace=<id>`. `DELETE /espaces/{id}` arrête tout, supprime les services, le réseau et le dossier.
- `lanceur/Dockerfile` : une étape `rust:1-slim` qui compile, puis `debian:bookworm-slim` avec `git` et `ca-certificates`. Le lanceur tourne en root dans son conteneur, pour lire le socket : c'est un choix assumé, puisque c'est son rôle. On ajoute le commentaire `# ponytail: root pour le socket ; passer par un groupe docker dédié si l'hôte le permet`.

- [ ] **Étape 1 : tests unitaires de `specification`** :
  - `image_refusee` ;
  - `durcissement` : `user`, `cap_drop`, `security_opt`, `privileged == Some(false)`, `pids_limit`, `memory`, `network_mode == "run-net"` ;
  - `role_code_monte_tests_en_lecture_seule` : un montage `tests` avec `read_only` ;
  - `role_tests_sans_montage_lecture_seule` ;
  - `aucun_bind_hote` : aucun montage de type `bind`.

  **Tests Docker**, dans `lanceur/tests/docker.rs`, marqués `#[ignore]` et lancés en CI avec `-- --ignored` (le runner GitHub a Docker) :
  - `ecriture_tests_echoue_pour_code` : `sh -c 'echo x > tests/a.py'` sort avec un code non nul, et le fichier n'a pas changé ;
  - `glob_de_fichier_restaure` : avec `**/conftest.py`, la commande modifie `conftest.py` ; la réponse porte `violation == ["conftest.py"]`, et le contenu a été restauré ;
  - `delai_tue_le_conteneur` : avec `sleep 30` et `delai_s=2`, on obtient `delai_depasse` en moins de 10 s, et aucun conteneur `portail.espace` ne reste ;
  - `pas_de_reseau` : sur un réseau `internal` créé par le test, `wget -T 3 http://1.1.1.1` échoue ;
  - `utilisateur_non_root` : `id -u` donne `1000`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** `cargo test` donne PASS, puis `cargo test -- --ignored` donne PASS avec Docker local.
- [ ] **Étape 5 :** dans la CI, le job `lanceur` lance aussi `cargo test -- --ignored`. Dans `deploy.yml`, ajouter un second build qui pousse `ghcr.io/${{ github.repository }}-lanceur` depuis `lanceur/Dockerfile`.
- [ ] **Étape 6 : commit** `feat(lanceur): conteneurs jetables durcis, services de tests et image`.

### Task 4: config d'exécution du projet et tables de C

**Fichiers :**
- Créer : `backend/portail/execution.py`, `backend/migrations/versions/0003_boucle_dev.py`, `backend/tests/test_execution.py`
- Modifier : `backend/portail/db.py`, `backend/portail/config.py`, `backend/portail/api.py`, `backend/portail/schemas.py`

**Interfaces :**
- `class ConfigExecution(BaseModel)` :
  - `image: str` ;
  - `chemins_tests: list[str]` (au moins 1) ;
  - `config_tests: list[str] = CONFIG_TESTS_DEFAUT` ;
  - `commandes: dict[str, str]`, qui doit contenir `installer`, `tests` et `tests_cibles`. `tests_cibles` doit contenir `{fichiers}` ;
  - `services: list[Service] = []`, où `Service` contient `nom` (`^[a-z0-9-]+$`), `image` et `env: dict[str, str] = {}`.

  `CONFIG_TESTS_DEFAUT = ["**/conftest.py", "pytest.ini", "**/pytest.ini", "jest.config.*", "vitest.config.*", ".cargo/config.toml"]`.
- `def lire_config(texte_yaml: str) -> ConfigExecution`. Elle lève `Refus(422, <message Pydantic lisible>)`.
- `def commande(cfg, nom: str, fichiers: list[str] = []) -> str` : `tests_cibles` reçoit `" ".join(shlex.quote(f) for f in fichiers)` à la place de `{fichiers}`. Un nom inconnu lève `KeyError`.
- **Change B** :
  - `Projet` gagne `config_execution: str | None` (le YAML brut, tel qu'édité) ;
  - `Tache` gagne `resume_blocage: str | None`.
- Nouvelles tables :
  - `ExecutionDev` : `id`, `pipeline_id` (unique), `tache_id`, `branche`, `espace` (`tache-<tache_id>-<n>`), `base` (la branche de référence), `base_sha`, `phase` (`preparation` | `tests` | `rouge` | `code` | `verification` | `revue` | `pr` | `reprise` | `fini`), `renvois` (int), `interruptions` (int), `reprise` (bool), `fichiers_tests` (JSON), `pr_numero` (nullable), `pr_url` (nullable), `commentaires_vus` (JSON, une liste d'ids), `debut`.
  - `CommandeLancee` : `id`, `pipeline_id`, `etape_id`, `nom`, `code` (nullable), `delai_depasse`, `sortie` (Text, déjà tronquée), `debut`, `fin`.
- `Reglages` gagne :
  - `lanceur_url = "http://lanceur:8080"` et `lanceur_secret = ""` ;
  - `github_app_id = ""`, `github_app_cle = ""` (PEM) et `github_proprietaire = ""` ;
  - `ntfy_url = ""`, `ntfy_sujet = ""` et `ntfy_jeton = ""` ;
  - `paralleles_max = 1`, `duree_max_tache_s = 7200` et `delai_commande_s = 600`.
- Routes :
  - `PUT /api/projets/{id}/execution {yaml}` valide puis enregistre, ou renvoie `422` ;
  - `GET /api/projets/{id}` renvoie aussi `config_execution` (le texte brut).

- [ ] **Étape 1 : tests**
  - `test_config_valide` (une config EA réaliste : `image: portail-exec:1`, `chemins_tests: ["backend/tests/**", "frontend/**/*.spec.ts"]`, `services: [{nom: postgres, image: postgres:16-alpine, env: {POSTGRES_PASSWORD: test}}]`) ;
  - `test_commandes_obligatoires_422`, pour l'absence de `tests_cibles` ;
  - `test_gabarit_sans_fichiers_422` ;
  - `test_commande_quote_les_fichiers` : `["a b.py"]` donne `"'a b.py'"` dans la commande ;
  - `test_put_execution_api` ;
  - la migration `0003` monte et descend, comme en B.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): config d'exécution des projets et tables de la boucle de dev`.

### Task 5: client du lanceur, outils d'espace et agents de dev

**Fichiers :**
- Créer : `backend/portail/lanceur.py`, `backend/portail/outils_espace.py`, `backend/tests/test_outils_espace.py`, et dans `backend/tests/conftest.py`, un `FauxLanceur` qui tient un espace en mémoire (un dict chemin → contenu) et applique les mêmes règles de rôle avec `fnmatch`
- Modifier : `backend/portail/agents.py`, `backend/portail/boucle.py`, `agents.yaml`

**Interfaces :**
- `class ErreurLanceur(Exception)`, avec `statut: int` et `message`.
- `class ClientLanceur(url, secret, transport=None)`. Il a une méthode `async` par route des tâches 2 et 3, avec les mêmes noms que les opérations : `creer_espace`, `fichiers`, `commit`, `commits`, `diff`, `fichier_a`, `fusionner`, `pousser`, `tete`, `lancer`, `services`, `arreter`, `supprimer`. Délai httpx : `delai_s + 60` pour `lancer`, 120 s pour le reste.
- **Change B** : `boucle_outils(llm, agent, messages, outils, sur_appel)` accepte tout objet qui a `schemas() -> list[dict]` et `async executer(nom, arguments) -> tuple[str, bool]`. `OutilsDepot` gagne `schemas()`, qui renvoie les schémas de `agent.outils`. La boucle utilise `outils.schemas()` au lieu de `SCHEMAS_OUTILS`.
- `class OutilsEspace(client, espace, role, cfg: ConfigExecution, noms: list[str], journal: Callable[[CommandeLancee-like dict], Awaitable[None]])` :
  - `schemas()` : les outils `lister`, `lire`, `chercher`, plus `ecrire(chemin, contenu)` et `supprimer(chemin)` si le rôle peut écrire, plus `lancer(nom)` dont l'`enum` est l'ensemble des clés de `cfg.commandes`, **sauf** `installer` ;
  - `executer` : un refus du lanceur (403, 422) devient un texte `"erreur : …"` et n'est pas compté comme un appel mal formé. `lancer` passe par `commande(cfg, nom, self.fichiers_tests)` puis `client.lancer`, et appelle `journal(...)`. Le résultat rendu au modèle vaut `"code <n>\n<sortie>"` ;
  - `fichiers_tests: list[str]` : les chemins que le rôle `tests` a écrits pendant cette exécution, tenus à jour par `ecrire`.
- **Change B** :
  - `Agent.outils` accepte aussi `ecrire`, `supprimer` et `lancer` ;
  - `Agent` gagne `role: Literal["tests", "code", "revue"] | None = None` ;
  - `produit` accepte aussi `"travail"` (un agent qui écrit dans l'espace), `"verdict"` (une réponse JSON de revue) et `"tri"` ;
  - validation : un agent `travail` doit avoir un `role` et l'outil `lancer`. Un agent `revue` ne peut avoir ni `ecrire` ni `supprimer`.
- `agents.yaml` gagne les agents suivants, et `pipelines.dev: [tests, code, revue]` :
  - `tests` : `produit: travail`, `role: tests`, avec tous les outils ;
  - `code` : `produit: travail`, `role: code`, avec tous les outils ;
  - `revue` : `produit: verdict`, `role: revue`, avec `lister`, `lire` et `chercher` ;
  - `tri` : `produit: tri`, sans outils.

- [ ] **Étape 1 : tests**
  - `test_client_lanceur_auth_et_erreurs`, avec `MockTransport` : l'en-tête `Bearer` est présent, et un 409 lève `ErreurLanceur(statut=409)` ;
  - `test_outils_espace_schemas_par_role` : `revue` n'a pas `ecrire`, et l'enum de `lancer` ne contient pas `installer` ;
  - `test_ecrire_refuse_devient_texte` : avec le `FauxLanceur`, le rôle `code` qui écrit `tests/x.py` donne `("erreur : écriture interdite pour le rôle code", False)` ;
  - `test_lancer_tests_cibles_utilise_les_fichiers_ecrits` ;
  - `test_lancer_journalise` ;
  - les tests du catalogue pour les nouvelles validations ;
  - `test_agents_yaml_du_depot_est_valide`, mis à jour pour `pipelines.dev`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests, ceux de B compris).
- [ ] **Étape 5 : commit** `feat(portail): client du lanceur, outils d'espace et agents de dev`.

### Task 6: client GitHub App

**Fichiers :**
- Créer : `backend/portail/github.py`, `backend/tests/test_github.py`
- Modifier : `backend/pyproject.toml` (`pyjwt[crypto]`), `backend/uv.lock`

**Interfaces :**
- `class ErreurGitHub(Exception)`.
- `class GitHubApp(app_id: str, cle_pem: str, transport=None)`. Ses méthodes `async` :
  - `jeton(depot: str) -> str`, où `depot` vaut `"owner/nom"`. Elle fait `GET /repos/{depot}/installation`, puis `POST /app/installations/{id}/access_tokens`. Le résultat est mis en cache jusqu'à `expires_at - 5 min`, par installation. Le JWT de l'App est en RS256, avec `iat = maintenant - 60` et `exp = maintenant + 540` ;
  - `branche_protegee(depot, branche) -> bool` : `GET /repos/{depot}/branches/{branche}`, puis le champ `protected`. Toute erreur lève `ErreurGitHub` (l'appelant refuse) ;
  - `creer_pr(depot, branche, base, titre, corps) -> tuple[int, str]`, avec `draft: true` ;
  - `etat_pr(depot, numero) -> Literal["ouverte", "fusionnee", "fermee"]` ;
  - `commentaires(depot, numero, auteur: str) -> list[Commentaire]` : c'est la fusion des commentaires d'issue (`/issues/{n}/comments`), des commentaires de revue (`/pulls/{n}/comments`) et des revues dont l'état est `CHANGES_REQUESTED` ou `COMMENTED` et le corps non vide (`/pulls/{n}/reviews`). On ne garde que ceux dont `user.login == auteur`. `Commentaire` contient `cle: str` (`"issue-<id>"`, `"revue-<id>"`, `"avis-<id>"`), `texte`, `chemin: str | None`, `ligne: int | None` et `type`. La liste est triée par date ;
  - `commenter(depot, numero, texte) -> None` ;
  - `repondre_revue(depot, numero, commentaire_id, texte) -> None` ;
  - `fermer_pr(depot, numero) -> None`.
- `def depot_depuis_url(url: str) -> str` : `https://github.com/a/b(.git)` donne `"a/b"`.

- [ ] **Étape 1 : tests** avec `MockTransport` et une clé RSA générée dans le test :
  - `test_jeton_cache_et_renouvele` : deux appels donnent un seul `POST access_tokens`. Après avoir avancé une horloge injectée au-delà de `expires_at - 5 min`, on obtient un deuxième `POST` ;
  - `test_jwt_valide` : il se décode avec la clé publique, et `iss == app_id` ;
  - `test_branche_protegee_vrai_faux_erreur` (200 avec true, 200 avec false, 404 qui lève) ;
  - `test_commentaires_filtre_auteur_et_fusionne` : un commentaire de `nicolaslallier`, un de `portail[bot]` et une revue `APPROVED` vide donnent un seul commentaire ;
  - `test_creer_pr_draft`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS.
- [ ] **Étape 5 : commit** `feat(portail): client GitHub App (jetons d'installation, PR, commentaires)`.

### Task 7: troisième protection

**Fichiers :**
- Créer : `backend/portail/protections.py`, `backend/tests/test_protections.py`

**Interfaces :**
- `SECTIONS_TESTS` :
  - dans `pyproject.toml`, toute clé dont le chemin commence par `tool.pytest` ;
  - dans `package.json`, les clés de premier niveau `jest` et `vitest`, et toute entrée de `scripts` dont le nom contient `test` ;
  - dans `Cargo.toml`, `dev-dependencies` et `test`.
- `async def verifier_commits_code(client: ClientLanceur, espace: str, depuis: str, cfg: ConfigExecution) -> list[str]` renvoie la liste des violations (vide si tout va bien) :
  - pour chaque commit de `commits(depuis)` dont `auteur_courriel == "agent-code@portail.local"`, chaque fichier qui correspond à `chemins_tests` ∪ `config_tests` (avec `fnmatch` étendu à `**`, la même sémantique que `globset`, voir les tests) est une violation `"<fichier> (fichier de tests)"` ;
  - pour chaque manifeste touché, on compare les sections de tests avant et après le commit (`fichier_a(rev=sha^)` et `fichier_a(rev=sha)`, avec `tomllib` ou `json`). Une différence donne la violation `"<fichier> (section <clé>)"` ;
  - les commits d'un autre auteur sont ignorés.
- `def correspond(chemin: str, motifs: list[str]) -> bool`.

- [ ] **Étape 1 : tests** avec le `FauxLanceur` (qui expose `commits` et `fichier_a`) :
  - `test_correspond`, paramétré : `tests/**` correspond à `tests/a/b.py` mais pas à `src/tests.py`. `**/conftest.py` correspond à `conftest.py` et à `a/conftest.py`. `frontend/**/*.spec.ts` correspond à `frontend/src/x.spec.ts` ;
  - `test_commit_code_touche_un_test` ;
  - `test_commit_code_change_tool_pytest` ;
  - `test_commit_code_ajoute_une_dependance_permis` (`[project.dependencies]` change) ;
  - `test_package_json_script_test` ;
  - `test_cargo_dev_dependencies` ;
  - `test_commit_de_nicolas_ignore`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS.
- [ ] **Étape 5 : commit** `feat(portail): troisième protection sur les commits de l'agent de code`.

### Task 8: orchestrateur du pipeline `dev`

**Fichiers :**
- Créer : `backend/portail/dev.py`, `backend/tests/test_dev.py`, et dans `backend/tests/conftest.py`, un `FauxGitHub`
- Modifier : `backend/portail/moteur.py` (le type `dev`), `backend/portail/chat.py` (lancement)

**Interfaces :**
- **Change B** : pour le type `dev`, `creer_pipeline` ne crée **aucune** étape. C'est l'orchestrateur qui ajoute une `Etape` par passage d'agent (avec un `ordre` croissant, renvois compris) et une étape `systeme` pour chaque vérification du portail (agent `"portail"`). L'état du pipeline se déduit toujours de `etat_pipeline`.
- `class Orchestrateur(sessions, catalogue, llm, lanceur: ClientLanceur, github: GitHubApp, depots_lecture, notifier)`. Ses méthodes :
  - `async demarrer(tache_id: int) -> int` crée le pipeline `dev` et l'`ExecutionDev`, puis lance `executer` en tâche de fond. Elle renvoie l'id du pipeline ;
  - `async executer(pipeline_id: int) -> None` déroule les phases à partir de `ExecutionDev.phase`. Chaque phase **enregistre la suivante avant de s'exécuter**, ce qui permet la reprise ;
  - `taches: dict[int, asyncio.Task]`.

  Les phases (avec `cfg = lire_config(projet.config_execution)`) :
  1. **`preparation`** :
     - vérifier `branche_protegee`, sinon *Bloquée* « branche par défaut non protégée » ;
     - `creer_espace(existante=False)` ;
     - `services` si `cfg.services` ;
     - `lancer("systeme", installer)`. Un code non nul donne *Bloquée* « installation échouée » ;
     - `base_sha = tete()`.
  2. **`tests`** :
     - lancer la boucle de l'agent `tests` avec `OutilsEspace(role="tests")`. Il reçoit l'annexe de la tâche (titre, description, critères, fichiers), l'aperçu (`apercu` de B, pris à travers `lister` et `lire`, ou bien directement l'aperçu du clone de lecture de B au même SHA) et les remarques éventuelles ;
     - si `fichiers_tests` est vide après la boucle, *Bloquée* « aucun test écrit » ;
     - sinon, `commit(agent-tests)`.
  3. **`rouge`** :
     - `lancer(tests_cibles)` doit renvoyer un code **non nul et différent de 5** ;
     - avec le code 5, *Bloquée* « aucun test collecté » ;
     - avec 0, on revient une seule fois à `tests` avec la remarque « les tests passent déjà : ils ne testent rien de nouveau », puis *Bloquée*.
  4. **`code`** : la boucle de l'agent `code`, avec `OutilsEspace(role="code")`, la sortie de l'échec rouge et les éventuelles remarques. Puis `commit(agent-code)`.
  5. **`verification`** :
     - `tests_cibles`, puis `tests`, doivent renvoyer 0. Sinon, *Bloquée*, avec la fin de la sortie dans `resume_blocage` ;
     - ensuite, `verifier_commits_code(depuis=base_sha)`. Une violation donne *Bloquée* « protection des tests : … », sans push.
  6. **`revue`** : l'agent `revue` reçoit `diff(depuis=base_sha)` et la tâche. Sa réponse est un JSON validé par `{"decision": "ok" | "renvoyer_tests" | "renvoyer_code", "remarques": [str]}`, avec une seule relance si elle est invalide.
     - Un renvoi tant que `renvois < 2` : `renvois += 1`, puis la phase `tests` (suivie de `rouge`, `code` et `verification`) ou la phase `code` (suivie de `verification`), avec les remarques. Après un renvoi aux tests, `rouge` ne lance que les fichiers modifiés par ce renvoi.
     - Au-delà de 2 renvois, les remarques sont gardées comme « non résolues ».
  7. **`pr`** :
     - `pousser` ;
     - `creer_pr(titre = "<titre de la tâche>", corps)`. Le corps contient le lien vers la tâche (`/projets/<p>/kanban`) et vers le pipeline, les critères, le résumé de la revue et une section « Remarques non résolues » s'il y en a ;
     - enregistrer `pr_numero` et `pr_url` ;
     - la tâche passe à `en_revue` et **garde son verrou** ;
     - `notifier("PR ouverte : <titre>", url)`, puis la phase passe à `fini`.
- **Bloquée**, une fonction `bloquer(raison)` :
  - la tâche passe à `bloquee`, avec `resume_blocage = raison` et un résumé de chaque étape ;
  - le verrou est levé ;
  - `lanceur.supprimer(espace)` ;
  - le pipeline passe à `echouee` avec la raison ;
  - `notifier("Tâche bloquée : <titre>", raison)`.
- **Durée maximale** : `executer` est enveloppé par `asyncio.timeout(duree_max_tache_s)`. Un dépassement donne *Bloquée* « durée maximale dépassée ».

- [ ] **Étape 1 : tests** avec `FauxLLM` (des réponses `completer` réglées à l'avance, dont des `tool_calls` vers `ecrire` et `lancer`), `FauxLanceur` (des codes de sortie réglés par commande) et `FauxGitHub` :
  - `test_parcours_complet_ouvre_une_pr` : on obtient deux commits (`agent-tests`, puis `agent-code`), la PR en brouillon a le bon corps, la tâche est `en_revue` avec son verrou, et une notification a été envoyée ;
  - `test_aucun_test_ecrit_bloque` (point de revue n° 1) ;
  - `test_rouge_qui_passe_renvoie_une_fois_puis_bloque` ;
  - `test_verification_rouge_bloque_avec_sortie` ;
  - `test_violation_protection_bloque_sans_push` : `pousser` n'est jamais appelé ;
  - `test_revue_renvoie_au_code_puis_ok` : `renvois == 1` et une PR ouverte ;
  - `test_trois_renvois_ouvre_quand_meme_avec_remarques` : le corps de la PR contient « Remarques non résolues » ;
  - `test_branche_non_protegee_bloque` ;
  - `test_commande_qui_depasse_le_delai` : le faux lanceur renvoie `delai_depasse=True` sur `tests` pendant la vérification, ce qui donne *Bloquée*, avec « délai dépassé » dans le résumé ;
  - `test_duree_max_tache` (avec `duree_max_tache_s=0.1` et un faux modèle bloqué).
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): orchestrateur du pipeline dev jusqu'à la PR en brouillon`.

### Task 9: ordonnanceur, annulation, reprise d'une tâche et redémarrage

**Fichiers :**
- Créer : `backend/portail/ordonnanceur.py`, `backend/tests/test_ordonnanceur.py`
- Modifier : `backend/portail/api.py` (lifespan, `POST /api/taches/{id}/annuler`), `backend/portail/taches.py`

**Interfaces :**
- `async def choisir(session) -> Tache | None`. Elle prend, parmi les projets qui ont un `depot_url` et une `config_execution`, triés par id, la première tâche en `prete` selon le rang, **sans verrou**, et dont **toutes** les dépendances sont `terminee`.
- `class Ordonnanceur(sessions, orchestrateur, paralleles_max)` :
  - `reveiller()` (un `asyncio.Event`) ;
  - une boucle qui tourne toutes les 30 s ou au réveil. Tant que le nombre de pipelines `dev` actifs (dont les tâches de fond ne sont pas finies) est inférieur à `paralleles_max`, elle prend une tâche avec `choisir`, pose le verrou (`verrou = pipeline_id`, colonne `en_cours`) dans **la même transaction** que la création du pipeline, puis lance l'orchestrateur ;
  - toute route qui modifie le kanban appelle `reveiller()`.
- **Change B** : `POST /api/taches/{id}/annuler` sur une tâche dont le pipeline est `dev` :
  - annuler la tâche asyncio ;
  - `lanceur.arreter` puis `lanceur.supprimer` ;
  - le pipeline passe à `echouee` « annulé » ;
  - la tâche revient dans `a_faire`, et le verrou est levé.
- **Reprendre** (une tâche remise de `bloquee` ou `a_faire` vers `prete`, puis choisie de nouveau) : `n` = 1 + le nombre d'`ExecutionDev` précédentes de la tâche. On obtient une branche `…-<n>` et un espace `tache-<id>-<n>`. Si une `ExecutionDev` précédente a une PR `ouverte`, on fait `commenter(« Remplacée par <nouvelle PR> »)` puis `fermer_pr` **après** l'ouverture de la nouvelle PR.
- **Redémarrage** (au lifespan, après la récupération de A) : pour chaque `ExecutionDev` dont la phase n'est pas `fini` et dont le pipeline n'est ni `terminee` ni `echouee`, on fait `interruptions += 1`. Si `interruptions <= 1`, on relance `executer` à la phase enregistrée ; sinon, *Bloquée* « interrompue deux fois ». L'étape interrompue a déjà été marquée `echouee` par A ; l'orchestrateur en ajoute une nouvelle.

- [ ] **Étape 1 : tests**
  - `test_choisir_respecte_rang_dependances_verrou` : il y a T1 (`prete`, rang 2000), T2 (`prete`, rang 1000, qui dépend de T3 en `en_revue`) et T4 (`prete`, rang 3000, verrouillée). On obtient T1 ;
  - `test_projet_sans_config_ignore` ;
  - `test_paralleles_max_respecte` : avec deux tâches prêtes et `paralleles_max=1`, un seul pipeline est lancé ;
  - `test_verrou_pose_dans_la_meme_transaction` : deux `choisir` + verrouillage concurrents ne prennent jamais la même tâche (`SELECT … FOR UPDATE SKIP LOCKED`) ;
  - `test_annuler_dev` ;
  - `test_reprendre_branche_n_et_ferme_l_ancienne_pr` ;
  - `test_redemarrage_reprend_une_fois_puis_bloque` (point de revue n° 5).
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): ordonnanceur, annulation, reprise de tâche et redémarrage`.

### Task 10: suivi des PR et reprise sur commentaires

**Fichiers :**
- Créer : `backend/portail/suivi_pr.py`, `backend/tests/test_suivi_pr.py`
- Modifier : `backend/portail/dev.py` (la phase `reprise`), `agents.yaml` (les prompts de `tri`)

**Interfaces :**
- `class SuiviPR(sessions, github, orchestrateur, lanceur, notifier, proprietaire)`. Toutes les 120 s, pour chaque tâche `en_revue` qui a une `ExecutionDev` avec `pr_numero` :
  - **PR fusionnée** : la tâche passe à `terminee`, le verrou est levé, `lanceur.supprimer(espace)`, et le pipeline est `terminee`. L'ordonnanceur est réveillé ;
  - **PR fermée** : la tâche passe à `a_faire`, le verrou est levé et `lanceur.supprimer(espace)` ;
  - **Nouveaux commentaires** de `proprietaire` (dont la `cle` n'est pas dans `commentaires_vus`), seulement si aucune reprise n'est active pour cette tâche : on ajoute leurs clés à `commentaires_vus` **avant** de lancer la reprise. La tâche passe à `en_cours`, et un pipeline `dev` de reprise démarre (`ExecutionDev.reprise = true`, même branche, même espace, même PR).
- Les étapes de la phase `reprise` dans l'orchestrateur :
  1. `fusionner(base)`. Un 409 de conflit donne `commenter(« Conflit avec <base> sur : <fichiers>. Résous-le et je reprendrai. »)`, puis la tâche revient `en_revue` ;
  2. l'agent `tri` répond `{"classement": [{"cle": str, "cible": "tests" | "code"}]}`, validé, avec une relance ;
  3. si des commentaires sont classés `tests`, on passe par la phase `tests` avec ces commentaires comme remarques, puis `rouge` sur les fichiers modifiés seulement ;
  4. si des commentaires sont classés `code`, ou si les tests ont changé, on passe par `code` ;
  5. puis `verification`, `revue` (avec un compteur de renvois **remis à 0**), puis `pousser` ;
  6. on répond à chaque commentaire traité : `repondre_revue` pour un commentaire de revue, `commenter` sinon, avec « Traité dans <sha court> ». La tâche revient `en_revue` et on fait `notifier("Reprise terminée : <titre>")`.

  Si la reprise échoue à n'importe quelle étape, la tâche revient **`en_revue`** (pas *Bloquée*). Le portail fait `commenter(« La reprise a échoué : <raison>. »)`, puis `notifier`, et l'espace est gardé.

- [ ] **Étape 1 : tests** avec `FauxGitHub` :
  - `test_fusionnee_termine_et_libere` ;
  - `test_fermee_retour_a_faire` ;
  - `test_commentaire_de_nicolas_declenche_une_reprise` ;
  - `test_commentaire_d_un_autre_ignore` ;
  - `test_commentaires_traites_une_seule_fois` : deux passages du suivi avec les mêmes commentaires, plus un nouveau commentaire pendant une reprise active, donnent une seule reprise. Le nouveau commentaire est pris au passage suivant, après la fin de la reprise (point de revue n° 4) ;
  - `test_tri_tests_passe_par_l_agent_de_tests` : l'agent de code ne reçoit jamais le commentaire classé `tests` ;
  - `test_conflit_commente_et_retourne_en_revue` ;
  - `test_echec_de_reprise_retourne_en_revue_avec_commentaire`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): suivi des PR et reprise sur les commentaires de Nicolas`.

### Task 11: notifications et flux d'événements

**Fichiers :**
- Créer : `backend/portail/notifications.py`, `backend/tests/test_notifications.py`
- Modifier : `backend/portail/api.py`, `backend/portail/chat.py` (le `Diffuseur` gagne un canal global)

**Interfaces :**
- `class Notifieur(url, sujet, jeton, transport=None)`, avec `async def __call__(self, titre: str, texte: str = "", lien: str | None = None) -> None`. Elle fait `POST {url}/{sujet}`, avec les en-têtes `Title`, `Authorization: Bearer` et `Click` (le lien). Elle ne fait rien si la config est incomplète. Une erreur réseau est journalisée et **ne lève jamais d'exception**.
- **Change A** : `Diffuseur` gagne `publier_global(evenement: dict)` et `abonner_global() -> asyncio.Queue`. `changer_etat` (moteur) et toute écriture de tâche publient `{"type": "pipeline", "id": …}` ou `{"type": "kanban", "projet_id": …}`. Comme le moteur n'a pas de diffuseur, ce sont les appelants (chat, orchestrateur, routes) qui publient après le commit.
- `GET /api/evenements` : un flux SSE global (`event: pipeline` / `event: kanban`), avec un `: ping` toutes les 25 s.

- [ ] **Étape 1 : tests**
  - `test_notifie_avec_titre_et_lien` ;
  - `test_config_incomplete_ne_fait_rien` ;
  - `test_erreur_reseau_avalee_et_journalisee` (avec `caplog`) ;
  - `test_flux_global_recoit_pipeline_et_kanban`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS.
- [ ] **Étape 5 : commit** `feat(portail): notifications ntfy et flux d'événements global`.

### Task 12: interface de la boucle de dev

**Fichiers :**
- Modifier : `frontend/src/api.ts`, `frontend/src/flux.ts`, `frontend/src/views/PipelinesView.vue`, `frontend/src/views/KanbanView.vue`, `frontend/src/views/ProjetView.vue`, `frontend/src/views/PipelineView.vue`, `frontend/src/components/CarteTache.vue`
- Créer : `frontend/src/components/ConfigExecution.vue`, `frontend/src/evenements.ts`, `frontend/src/evenements.test.ts`

**Interfaces :**
- `ecouterEvenements(rappel: (e: {type: "pipeline" | "kanban", id?: number, projet_id?: number}) => void): () => void`. Elle passe par `EventSource("/api/evenements")` et se reconnecte d'elle-même : c'est le comportement natif d'`EventSource`.
- **Change A et B** : `PipelinesView` et `KanbanView` remplacent leur `setInterval` de 5 s par `ecouterEvenements` (on recharge sur un événement qui les concerne). On garde un rechargement de secours toutes les 60 s.
- `ConfigExecution` (dans `ProjetView`) : un `<textarea>` YAML, pré-rempli avec un exemple EA commenté si la config est vide, et « Enregistrer ». Un `422` affiche son `detail`.
- `PipelineView`, pour un pipeline `dev` :
  - un bandeau avec la branche, la phase, les renvois et le lien de la PR ;
  - les étapes `portail` affichent chaque `CommandeLancee` repliée (nom, code, durée, sortie dans `<pre>`) ;
  - chaque commit s'affiche avec son auteur.

  `api.ts` gagne `ExecutionDev` et `CommandeLancee` dans le détail du pipeline ; **côté backend**, `GET /api/pipelines/{id}` les inclut (à ajouter dans `schemas.py`, dans cette tâche).
- `CarteTache` affiche le lien « PR #n » quand il existe, et `resume_blocage` (replié) sur une carte `bloquee`.

- [ ] **Étape 1 : test** dans `evenements.test.ts` : avec un faux `EventSource`, un événement `kanban` appelle le rappel avec `{type: "kanban", projet_id: 3}`, et la fonction de désabonnement ferme la source.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** `npm test` et `npm run build` donnent PASS, et pytest aussi pour l'ajout dans `schemas.py`.
- [ ] **Étape 5 : vérification manuelle**, si le lanceur et LiteLLM sont joignables en local (avec `docker compose`, le lanceur et un `run-net` local) : une tâche simple sur un petit dépôt de test donne une PR en brouillon. Sinon, la noter comme non vérifiée.
- [ ] **Étape 6 : commit** `feat(portail): interface de la boucle de dev et événements en direct`.

### Task 13: pile de déploiement et PR dans le dépôt Infra (brouillon, sans fusion)

**Fichiers (dépôt AI) :**
- Modifier : `deploy/portainer-stack.yml`, `README.md`

**Changements dans le dépôt AI :**
- La pile gagne le service `lanceur` :
  - l'image `ghcr.io/nicolaslallier/ai-lanceur:${IMAGE_TAG:-latest}` ;
  - `/var/run/docker.sock` monté **dans ce service seulement**, et le volume `portail-espaces` sur `/espaces` ;
  - les variables `LANCEUR_*` (le secret vient de `${LANCEUR_SECRET:?}`) ;
  - les réseaux `portail-lanceur` (interne) et une sortie vers `github.com` ;
  - aucun port publié.
- Le service `portail` gagne `PORTAIL_LANCEUR_URL=http://lanceur:8080`, `PORTAIL_LANCEUR_SECRET`, les variables `PORTAIL_GITHUB_APP_*` et `PORTAIL_GITHUB_PROPRIETAIRE`, les variables `PORTAIL_NTFY_*`, et le réseau `portail-lanceur`.
- Le README gagne une section « GitHub App du portail » : comment la créer, avec les permissions **Contents : Read & write**, **Pull requests : Read & write** et **Metadata : Read**, **sans Administration** ; sur quels dépôts l'installer ; et pourquoi la branche par défaut doit être protégée.
- [ ] **Commit** `feat(portail): lanceur dans la pile de déploiement`.

**PR dans le dépôt Infra**, à confier à `dev-infra` dans `~/Code/Infra`, en **PR brouillon**, sans pousser sur `main` et sans fusionner :
- **Réseau `run-net`** : `internal: true`, distinct de `dev-net`. Un squid `run-egress` à lui (ou une ACL dédiée sur `dev-egress`, à justifier dans la PR) qui laisse passer **seulement** `pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`, `crates.io`, `static.crates.io`, `index.crates.io`, ainsi que `github.com` et `codeload.github.com` en lecture. **Pas** de `s3:8333`, ni aucune adresse privée. Garder l'ordre des règles et le `dstdomain -n` décrits dans `CLAUDE.md` (Dev sessions).
- **Image d'exécution** `portail-exec:1`, dérivée de `devbox-session`, avec Python 3.12, uv, Node 22 et npm, et l'utilisateur 1000. Elle est construite comme `make dev-image`. On l'ajoute aux `LANCEUR_IMAGES`, et `postgres:16-alpine` et `minio/minio` aux `LANCEUR_IMAGES_SERVICES` (pour EA).
- **ntfy** : `make ntfy-provision app=portail topic=portail`.
- **Secrets** : `LANCEUR_SECRET` (`openssl rand -hex 32`), la clé privée de la GitHub App et `PORTAIL_GITHUB_PROPRIETAIRE`, dans l'endroit où l'Infra range les secrets des piles (`.env` ou OpenBao).
- **Vérification** : `scripts/dev-isolation-check.sh` accepte un conteneur du lanceur (par son label `portail.espace`) et vérifie qu'aucune sortie n'est possible hors de la liste permise, fuite DNS comprise. `make check-env` passe.
- [ ] **PR brouillon** `feat(portail): run-net, squid d'exécution, image portail-exec et secrets du lanceur`, avec dans la description le lien vers la PR du dépôt AI.
