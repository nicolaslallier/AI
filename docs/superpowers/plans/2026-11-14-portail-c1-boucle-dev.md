# Portail — C1 : boucle de dev jusqu'à la PR : plan d'implémentation

> **Pour les agents qui exécutent :** SOUS-SKILL REQUIS : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans, tâche par tâche. Les étapes utilisent des cases `- [ ]`.

**But :** les tâches *Prêtes* du kanban deviennent seules des PR en brouillon : tests écrits d'abord par un agent qui ne peut écrire que des tests, code ensuite par un agent qui ne peut pas les toucher, exécution dans des conteneurs jetables isolés.

**Architecture :**
- `lanceur/` (Rust) : seul détenteur du socket Docker. Il ne fait que lancer, attendre et tuer des conteneurs jetables durcis, et gérer les services de tests d'un espace. Il ne monte pas le volume des espaces : il le désigne par son nom (montage de sous-chemin).
- Portail (Python) : il monte le volume des espaces sur `/espaces`, fait les opérations de fichiers (outils de B étendus) et git, parle à GitHub (App), orchestre le pipeline `dev`, ordonne les tâches et suit les PR (fusion / fermeture).
- `execution/Dockerfile` : l'image d'exécution des commandes (Python 3.12, Node 22, uv, git, uid 1000).

**Pile :** Rust (édition 2024) : `axum`, `tokio`, `bollard`, `serde`, `subtle`. Portail : celle de A et B, plus `pyjwt[crypto]`.

**Spec :** `docs/superpowers/specs/2026-11-14-portail-c1-boucle-dev-design.md`, qui s'appuie sur `docs/superpowers/specs/2026-11-14-portail-c-boucle-dev-design.md`. Lire les deux. Le plan C (`docs/superpowers/plans/2026-11-14-portail-c-boucle-dev.md`) n'est **pas** la référence : celui-ci le remplace pour C1.

## Contraintes globales

- Contraintes de A et B : français partout (code, messages, commits), ruff, tests pytest contre le Postgres de test, `alembic check` vert, jamais de secret dans le dépôt, jamais de déclencheur `pull_request` dans `deploy.yml`.
- **Le portail ne parle jamais à Docker et n'exécute jamais rien de ce que les agents écrivent.** Les agents n'ont pas de shell : `lancer` prend un **nom** de commande de la config du projet.
- **git du portail**, à chaque appel, sans exception : `GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, et `-c core.hooksPath=/dev/null -c core.fsmonitor=false -c protocol.file.allow=user`. Le jeton passe par `-c http.extraHeader=Authorization: Basic <b64>` comme dans `depots.py`, et il est retiré de toute erreur. Jamais de `--force`, jamais de rebase.
- **Lanceur :**
  - il écoute `0.0.0.0:8080` sans publier de port ;
  - toute route sauf `GET /sante` exige `Authorization: Bearer <LANCEUR_SECRET>`, comparé en temps constant ; il refuse de démarrer avec un secret de moins de 32 caractères ;
  - variables : `LANCEUR_SECRET`, `LANCEUR_VOLUME` (défaut `portail-espaces`), `LANCEUR_RESEAU` (défaut `run-net`), `LANCEUR_PROXY` (ex. `http://run-egress:3128`), `LANCEUR_IMAGES`, `LANCEUR_IMAGES_SERVICES` (listes permises, séparées par des virgules) ;
  - Docker Engine 26 ou plus (montage `VolumeOptions.Subpath`, API 1.45).
- **Conteneur de commande**, sans exception : `User "1000:1000"`, `CapDrop ["ALL"]`, `SecurityOpt ["no-new-privileges"]`, `Privileged false`, `Memory` 2 GiB, `NanoCpus` 2e9, `PidsLimit 512`, `NetworkMode` = `LANCEUR_RESEAU` (+ le réseau de services de l'espace s'il existe), `HTTP_PROXY`/`HTTPS_PROXY` = `LANCEUR_PROXY`, `HOME=/home/agent`, `tmpfs` sur `/tmp` et `/home/agent`, label `portail.espace=<id>`, `Cmd ["sh","-c",commande]`, `WorkingDir /travail`. Montages : le sous-chemin `<id>` du volume sur `/travail` ; **toujours** `<id>/.git` en lecture seule sur `/travail/.git` ; puis chaque chemin de `lecture_seule` en lecture seule. Aucun autre montage, aucune autre variable.
- **Délai par commande** : 600 s par défaut, 1800 s au plus. Au-delà, le conteneur est tué et la sortie finit par `[délai dépassé : <n> s]`. On garde les **20 000 derniers caractères**, précédés de `[… début coupé]` si besoin.
- **Rôles** (appliqués par le portail) : `tests` n'écrit que dans `chemins_tests` ∪ `config_tests` ; `code` n'écrit nulle part dans `chemins_tests` ∪ `config_tests` ; `revue` n'écrit rien ; `systeme` (jamais exposé à un agent) sert à `installer`. Les motifs sont comparés au chemin relatif **résolu** (liens symboliques suivis, puis confinement à l'espace).
- **Branche** : `portail/tache-<id>-<slug>`, puis `-<n>` à partir de la 2e exécution. Slug : titre en minuscules, sans accents, `[a-z0-9-]`, 40 caractères au plus. **Espace** : `tache-<id>-<n>`, dossier `/espaces/<espace>`.
- **Auteurs** : `agent-tests <agent-tests@portail.local>`, `agent-code <agent-code@portail.local>`.
- **Limites par défaut** : `tours_max` 40 pour `tests` et `code` ; `renvois_max` 2 ; durée maximale d'une tâche 7200 s ; `paralleles_max` 1 **pour tout le portail** ; ordonnanceur toutes les 30 s ; suivi des PR toutes les 120 s.
- **Secrets** (OpenBao `infra/portail`, ajoutés à `MAP`) : `PORTAIL_GITHUB_APP_ID`, `PORTAIL_GITHUB_APP_CLE` (**la clé PEM encodée en base64 sur une ligne** : `vault-render-env.sh` refuse les retours à la ligne), `PORTAIL_LANCEUR_SECRET`. Si l'App ou le lanceur ne sont pas configurés, l'ordonnanceur et le suivi ne démarrent pas, sans erreur ; le reste du portail fonctionne comme avant.
- La branche par défaut d'un dépôt doit être **protégée**, sinon pas de pipeline `dev` ; toute erreur de cette vérification est un refus.

## Points à surveiller en revue

1. **Une commande écrit dans `.git/hooks` ou `.git/config`** (un hook `pre-commit`, un `core.fsmonitor`) : le git du portail ne doit jamais l'exécuter. Deux protections : `.git` toujours en lecture seule dans les conteneurs (tâche 1) et les options git des contraintes globales (tâche 4, test avec un hook planté à la main).
2. **L'agent de tests modifie `src/` par une commande `lancer`** : ces changements sont annulés avant le commit de l'étape tests (tâche 4 et tâche 7).
3. **L'agent de tests n'écrit aucun test**, alors que `tests_cibles` « échoue » quand même (pytest renvoie 5) : *Bloquée* « aucun test écrit » (tâche 7).
4. **Un lien symbolique créé par une commande** (`raccourci -> tests`, ou `x -> /etc`) : les outils refusent d'écrire au travers, et l'empreinte des globs protégés ne suit pas les liens (tâche 3).
5. **Un redémarrage du portail en plein pipeline** : la phase en cours repart une fois d'un espace remis à `HEAD`. À la deuxième interruption, *Bloquée* (tâche 8).

---

### Task 1: le lanceur

**Fichiers :**
- Créer : `lanceur/Cargo.toml`, `lanceur/src/main.rs`, `lanceur/src/config.rs`, `lanceur/src/api.rs`, `lanceur/src/conteneurs.rs`, `lanceur/tests/docker.rs`, `lanceur/Dockerfile`
- Modifier : `.github/workflows/ci.yml` (job `lanceur`)

**Interfaces :**
- `Config::depuis_env() -> Result<Config, String>` (champs : `secret`, `volume`, `reseau`, `proxy`, `images: Vec<String>`, `images_services: Vec<String>`).
- `fn chemin_relatif_sur(c: &str) -> bool` : non vide, pas absolu, aucun composant `..` ni `.`, caractères `[A-Za-z0-9._/-]`, pas de composant `.git`.
- `fn specification(cfg: &Config, espace: &str, image: &str, commande: &str, lecture_seule: &[String], reseau_services: Option<&str>) -> Result<bollard::container::Config<String>, String>` : **pure** ; refuse une image hors de `cfg.images` et tout chemin de `lecture_seule` qui n'est pas `chemin_relatif_sur` ; applique toutes les règles « Conteneur de commande ». Si `bollard` n'expose pas `subpath` dans `VolumeOptions`, mettre à jour `bollard` ; ne **jamais** se rabattre sur un montage `bind`.
- Routes (JSON ; une erreur renvoie `{"erreur": "<texte>"}` avec 400, 404, 422 ; `espace` doit correspondre à `^[a-z0-9-]{1,64}$`) :
  - `GET /sante` → `{"ok": true}` ;
  - `POST /lancer {espace, image, commande, delai_s, lecture_seule: [str]}` → `{"code": int | null, "sortie": str, "delai_depasse": bool}`. `delai_s` ≤ 1800, sinon 422. Télécharge l'image si absente (seulement une image permise). Rattache le réseau `portail-svc-<espace>` s'il existe. Le conteneur est supprimé dans tous les cas (`force`). Sortie : stdout et stderr entrelacés, tronquée comme dans les contraintes ;
  - `POST /services {espace, services: [{nom, image, env: {k: v}}]}` : réseau `portail-svc-<espace>` (`internal: true`), un conteneur par service avec l'alias `nom` et le label `portail.espace`, sans montage. `nom` : `^[a-z0-9-]{1,32}$`. Image hors de `images_services` → 422 ;
  - `POST /arreter {espace}` : tue les conteneurs de label `portail.espace=<espace>` ;
  - `POST /nettoyer {espace}` : arrête et supprime ces conteneurs et le réseau de services.
- `lanceur/Dockerfile` : étape `rust:1-slim` qui compile, puis `debian:bookworm-slim` avec `ca-certificates`. Il tourne en root pour lire le socket, avec le commentaire `# ponytail: root pour le socket ; passer par un groupe docker dédié si l'hôte le permet`.

- [ ] **Étape 1 : tests unitaires** (`specification`, `chemin_relatif_sur`, routeur avec `tower::ServiceExt::oneshot` et un Docker simulé derrière un trait) :
  - `image_refusee`, `durcissement` (user, cap_drop, security_opt, privileged == Some(false), pids_limit, memory, nano_cpus, network_mode == "run-net", env exact `HTTP_PROXY`, `HTTPS_PROXY`, `HOME`) ;
  - `git_toujours_en_lecture_seule` : un montage `<id>/.git` → `/travail/.git` avec `read_only`, même sans `lecture_seule` ;
  - `lecture_seule_ajoutee` : `["backend/tests"]` donne un montage `<id>/backend/tests` → `/travail/backend/tests` en lecture seule ;
  - `lecture_seule_refuse` : `../x`, `/etc`, `a/../b`, `.git/hooks`, `a b` ;
  - `aucun_bind` : aucun montage de type `bind` ;
  - `secret_trop_court`, `auth` (sans en-tête ou mauvais secret → 401 sur `/lancer`, 200 sur `/sante`), `espace_invalide_400`, `delai_trop_long_422`.
- [ ] **Étape 2 :** `cd lanceur && cargo test` échoue.
- [ ] **Étape 3 :** implémenter.
- [ ] **Étape 4 : tests Docker** dans `lanceur/tests/docker.rs`, `#[ignore]`, sur un volume et un réseau `internal` créés par le test :
  - `ecriture_lecture_seule_echoue` : `echo x > tests/a.py` sort non nul, le fichier est inchangé ;
  - `git_non_modifiable` : `echo x > .git/hooks/pre-commit` sort non nul ;
  - `delai_tue_le_conteneur` : `sleep 30` avec `delai_s=2` → `delai_depasse` en moins de 10 s, aucun conteneur `portail.espace` ne reste ;
  - `pas_de_reseau` : `wget -T 3 http://1.1.1.1` échoue ;
  - `utilisateur_non_root` : `id -u` donne `1000`.
- [ ] **Étape 5 :** `cargo fmt --check && cargo clippy -- -D warnings && cargo test && cargo test -- --ignored` passent (Docker local requis pour `--ignored` ; sinon, le noter).
- [ ] **Étape 6 :** job CI `lanceur` : `dtolnay/rust-toolchain@stable`, `Swatinem/rust-cache`, puis fmt, clippy, `cargo test`, `cargo test -- --ignored`, dans `lanceur/`.
- [ ] **Étape 7 : commit** `feat(lanceur): conteneurs jetables durcis et services de tests`.

### Task 2: config d'exécution, motifs et tables de C1

**Fichiers :**
- Créer : `backend/portail/execution.py`, `backend/migrations/versions/0003_boucle_dev.py`, `backend/tests/test_execution.py`
- Modifier : `backend/portail/db.py`, `backend/portail/config.py`, `backend/portail/schemas.py`, `backend/portail/api.py`

**Interfaces :**
- `CONFIG_TESTS_DEFAUT = ["**/conftest.py", "pytest.ini", "**/pytest.ini", "jest.config.*", "vitest.config.*", ".cargo/config.toml"]`.
- `class Service(BaseModel)` : `nom` (`^[a-z0-9-]{1,32}$`), `image: str`, `env: dict[str, str] = {}`.
- `class ConfigExecution(BaseModel)` : `image: str`, `chemins_tests: list[str]` (au moins 1), `config_tests: list[str] = CONFIG_TESTS_DEFAUT`, `commandes: dict[str, str]` (doit contenir `installer`, `tests`, `tests_cibles` ; `tests_cibles` doit contenir `{fichiers}`), `services: list[Service] = []`. Propriété `protege -> list[str]` = `chemins_tests + config_tests`.
- `def lire_config(texte_yaml: str) -> ConfigExecution` : lève `Refus(422, <message lisible>)`.
- `def commande(cfg, nom: str, fichiers: list[str] = []) -> str` : remplace `{fichiers}` par `" ".join(shlex.quote(f) for f in fichiers)` ; nom inconnu → `KeyError`.
- `def correspond(chemin: str, motifs: list[str]) -> bool` : globs avec `**` (zéro ou plusieurs dossiers), `*` et `?` ne traversent pas `/`, sensible à la casse.
- `def dossiers_lecture_seule(cfg, racine: Path) -> list[str]` : pour chaque motif de `cfg.protege` de la forme `<dossier>/**` sans autre joker, `<dossier>` s'il existe sous `racine` en tant que vrai dossier (pas un lien).
- **Change B** : `Projet.config_execution: str | None` (YAML brut) ; `Tache.resume_blocage: str | None`.
- Tables :
  - `ExecutionDev` : `id`, `pipeline_id` (unique, FK cascade), `tache_id` (FK `tache` cascade), `n`, `branche`, `espace`, `base` (branche de référence résolue), `base_sha`, `phase` (`preparation` | `tests` | `rouge` | `code` | `verification` | `revue` | `pr` | `fini`), `renvois` (0), `interruptions` (0), `remarques` (JSON, liste de textes pour la prochaine passe), `fichiers_tests` (JSON), `sortie_rouge` (Text, nullable), `pr_numero`, `pr_url` (nullables), `debut`.
  - `CommandeLancee` : `id`, `pipeline_id` (FK cascade), `etape_id` (FK cascade), `nom`, `code` (nullable), `delai_depasse`, `sortie` (Text), `debut`, `fin`.
- `Reglages` gagne : `lanceur_url = "http://lanceur:8080"`, `lanceur_secret = ""`, `espaces_dir: Path = Path("/espaces")`, `github_app_id = ""`, `github_app_cle = ""` (base64 du PEM), `paralleles_max = 1`, `duree_max_tache_s = 7200`, `delai_commande_s = 600`, `renvois_max = 2`.
- Routes : `PUT /api/projets/{id}/execution {yaml}` valide puis enregistre (`422` sinon ; `yaml` vide efface la config) ; `GET /api/projets/{id}` renvoie aussi `config_execution`.

- [ ] **Étape 1 : tests**
  - `test_config_valide` : config EA réaliste (`image: ghcr.io/nicolaslallier/ai-execution:latest`, `chemins_tests: ["backend/tests/**", "frontend/**/*.spec.ts"]`, `services: [{nom: postgres, image: "pgvector/pgvector:pg16", env: {POSTGRES_PASSWORD: test}}]`) ;
  - `test_commandes_obligatoires_422` (sans `tests_cibles`), `test_gabarit_sans_fichiers_422` ;
  - `test_commande_quote_les_fichiers` : `["a b.py"]` donne `'a b.py'` ;
  - `test_correspond` (paramétré) : `tests/**` correspond à `tests/a/b.py` et pas à `src/tests.py` ; `**/conftest.py` à `conftest.py` et `a/conftest.py` ; `frontend/**/*.spec.ts` à `frontend/src/x.spec.ts` et `frontend/x.spec.ts` ; `jest.config.*` pas à `a/jest.config.js` ;
  - `test_dossiers_lecture_seule` : `backend/tests/**` donne `backend/tests` s'il existe, rien s'il n'existe pas ou si c'est un lien ; `frontend/**/*.spec.ts` ne donne rien ;
  - `test_put_execution_api` (200, 422, effacement) ;
  - la migration `0003` monte et descend, `alembic check` vert.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** `uv run pytest` tout vert, ruff vert.
- [ ] **Étape 5 : commit** `feat(portail): config d'exécution des projets et tables de la boucle de dev`.

### Task 3: client du lanceur, outils d'espace et agents de dev

**Fichiers :**
- Créer : `backend/portail/lanceur.py`, `backend/tests/test_outils_espace.py`, `backend/tests/test_lanceur.py`
- Modifier : `backend/portail/outils.py`, `backend/portail/boucle.py`, `backend/portail/agents.py`, `agents.yaml`, `backend/tests/conftest.py` (`FauxLanceur`)

**Interfaces :**
- `class ErreurLanceur(Exception)` (`statut: int`, `message: str`).
- `class Resultat(BaseModel)` : `code: int | None`, `sortie: str`, `delai_depasse: bool`.
- `class ClientLanceur(url, secret, transport=None)`, méthodes `async` : `lancer(espace, image, commande, delai_s, lecture_seule) -> Resultat`, `services(espace, services: list[Service]) -> None`, `arreter(espace) -> None`, `nettoyer(espace) -> None`. Délai httpx : `delai_s + 60` pour `lancer`, 120 s sinon.
- `FauxLanceur` (conftest) : même interface ; `codes: dict[str, list[int]]` (codes rendus tour à tour par commande exacte, 0 par défaut), `effets: dict[str, Callable[[Path], None]]` (appliqués au dossier de l'espace avant de rendre le résultat), `appels: list[dict]`.
- **Change B** : `boucle_outils(llm, agent, messages, outils, sur_appel)` accepte tout objet avec `schemas() -> list[dict]` et `async executer(nom, arguments) -> tuple[str, bool]`. `OutilsDepot.schemas()` renvoie les schémas de `SCHEMAS_OUTILS` (tous) ; la boucle filtre déjà par `agent.outils`.
- `class OutilsEspace(OutilsDepot)` dans `outils.py` : `__init__(racine, role: Literal["tests","code","revue"], cfg: ConfigExecution, lancer: Callable[[str], Awaitable[str]])`.
  - `schemas()` : `lister`, `lire`, `chercher` ; plus `ecrire(chemin, contenu)` et `supprimer(chemin)` si le rôle n'est pas `revue` ; plus `lancer(nom)` dont l'`enum` est `cfg.commandes` **sauf** `installer`, si le rôle n'est pas `revue`.
  - `ecrire` / `supprimer` : chemin résolu par `_resoudre` (refus des secrets et de `.git` comme en B), puis règle de rôle sur le chemin relatif **résolu** : refus `"erreur : écriture interdite pour le rôle <r>"` (pas un appel mal formé). `ecrire` crée les dossiers parents, 200 000 caractères au plus. `supprimer` ne supprime que des fichiers.
  - `lancer(nom)` : délègue à la fonction `lancer` reçue (l'orchestrateur), qui rend `"code <n>\n<sortie>"`.
- `def empreinte(racine: Path, motifs: list[str]) -> dict[str, str]` : SHA-256 de chaque fichier régulier (pas les liens symboliques, sans les suivre ; pas `.git`, ni les dossiers des exclusions d'artefacts) dont le chemin relatif correspond à `motifs`.
- **Change B** : `Agent.outils` accepte `ecrire`, `supprimer`, `lancer` ; `Agent.produit` accepte `travail` et `verdict` ; `Agent.role: Literal["tests","code","revue"] | None = None`. Validation : `travail` exige un `role` et `lancer` ; `verdict` exige `role: revue` et interdit `ecrire`, `supprimer`, `lancer`.
- `agents.yaml` : agents `tests` (`produit: travail`, `role: tests`, tous les outils, `tours_max: 40`), `code` (idem, `role: code`), `revue` (`produit: verdict`, `role: revue`, `lister`, `lire`, `chercher`), même modèle que `plan`, avec leurs prompts en français ; `pipelines.dev: [tests, code, revue]`. Les prompts disent : tests — écrire des tests qui échouent tant que la tâche n'est pas faite, ne pas écrire de code de production ; code — faire passer les tests sans jamais les modifier, lancer `tests_cibles` puis `tests` avant de conclure ; revue — répondre en JSON selon le schéma de la tâche 7.

- [ ] **Étape 1 : tests**
  - `test_client_lanceur_auth_et_erreurs` (`MockTransport` : en-tête `Bearer`, 422 → `ErreurLanceur(statut=422)`) ;
  - `test_schemas_par_role` : `revue` n'a ni `ecrire` ni `lancer` ; l'enum de `lancer` n'a pas `installer` ;
  - `test_role_code_refuse_tests`, `test_role_tests_refuse_src`, `test_role_tests_ecrit_conftest` ;
  - `test_lien_vers_tests_refuse_pour_code` : `raccourci -> tests`, écriture de `raccourci/test_x.py` refusée ;
  - `test_lien_hors_espace_refuse` : `x -> /tmp`, écriture de `x/a` → `chemin interdit` ;
  - `test_empreinte_ignore_les_liens` ;
  - les tests du catalogue pour les nouvelles validations ; `test_agents_yaml_du_depot_est_valide` mis à jour pour `pipelines.dev` ;
  - les tests de `boucle` de B passent toujours.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** tout vert.
- [ ] **Étape 5 : commit** `feat(portail): client du lanceur, outils d'espace et agents de dev`.

### Task 4: git de l'espace

**Fichiers :**
- Créer : `backend/portail/espace.py`, `backend/tests/test_espace.py`
- Modifier : `backend/portail/depots.py` (extraire l'appel git durci en fonction de module, réutilisée par `Depots` et `Espace`)

**Interfaces :**
- `async def git(*args, cwd: Path | None, jeton: str = "", delai: int = 30, distant: bool = False) -> str` dans `depots.py` : l'environnement et les options des contraintes globales ; lève `ErreurDepot` avec le jeton retiré. `Depots._git` l'appelle.
- `EXCLUSIONS = [".venv/", "node_modules/", "__pycache__/", ".pytest_cache/", "target/", "dist/", ".ruff_cache/"]`.
- `class Espace(racine: Path)` (racine = `/espaces/<espace>`), méthodes `async` :
  - `cloner(depot_url, jeton, base, branche) -> str` : supprime d'abord tout dossier existant, `clone --branch <base> --single-branch`, `checkout -b <branche>`, écrit `EXCLUSIONS` dans `.git/info/exclude` ; rend le SHA de `HEAD` ;
  - `changements() -> list[str]` : fichiers modifiés, supprimés ou non suivis (hors ignorés), chemins relatifs (`status --porcelain -z --untracked-files=all`) ;
  - `restaurer(garder: Callable[[str], bool]) -> list[str]` : annule tout changement dont le chemin ne satisfait pas `garder` (fichier suivi : `checkout -- <f>` ; non suivi : suppression) ; rend les chemins annulés ;
  - `remettre_a_zero() -> None` : `reset --hard HEAD` puis `clean -fd` (les ignorés restent) ;
  - `commiter(nom, courriel, message) -> str | None` : `add -A` puis commit avec cet auteur et ce committer ; `None` s'il n'y a rien ;
  - `commits(depuis: str) -> list[tuple[str, str, list[str]]]` : `(sha, courriel_auteur, fichiers)` ;
  - `fichier_a(rev, chemin) -> str | None` ;
  - `diff(depuis) -> str` : tronqué à 200 000 caractères ;
  - `pousser(jeton, branche) -> None` : `push origin <branche>`, sans `--force` ;
  - `supprimer() -> None` : `rmtree` du dossier.

- [ ] **Étape 1 : tests** (origine : dépôt nu local en `file://`, comme `test_depots.py`) :
  - `test_cloner_branche_et_exclusions` : `node_modules/x` créé après coup n'apparaît pas dans `changements()` ;
  - `test_restaurer_garde_les_tests` : changements dans `tests/a.py`, `src/b.py` (suivi) et `src/c.py` (nouveau) ; avec `garder = correspond(·, ["tests/**"])`, seuls `tests/a.py` reste, `src/b.py` est restauré, `src/c.py` supprimé ;
  - `test_commit_auteur_et_commits` ; `test_commit_sans_changement_none` ;
  - `test_hook_jamais_execute` : un `.git/hooks/pre-commit` exécutable qui crée un fichier témoin, et un `core.fsmonitor` écrit à la main dans `.git/config` pointant vers un script témoin : après `commiter` et `changements`, aucun témoin n'existe ;
  - `test_pousser_sans_force` : l'origine a avancé sur la branche → `ErreurDepot`, l'origine est intacte ;
  - `test_jeton_absent_des_erreurs_et_du_disque` (aucune occurrence dans `.git/` ni dans le message d'erreur) ;
  - les tests de `test_depots.py` passent toujours.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** tout vert.
- [ ] **Étape 5 : commit** `feat(portail): espace de travail git durci`.

### Task 5: client GitHub App

**Fichiers :**
- Créer : `backend/portail/github.py`, `backend/tests/test_github.py`
- Modifier : `backend/pyproject.toml` (`pyjwt[crypto]`), `backend/uv.lock`

**Interfaces :**
- `class ErreurGitHub(Exception)`.
- `def depot_depuis_url(url: str) -> str` : `https://github.com/a/b(.git)` → `"a/b"`.
- `class GitHubApp(app_id: str, cle_b64: str, transport=None, horloge=time.time)`, méthodes `async` :
  - `jeton(depot) -> str` : `GET /repos/{depot}/installation`, puis `POST /app/installations/{id}/access_tokens` ; cache par installation jusqu'à `expires_at - 5 min`. JWT RS256, `iat = maintenant - 60`, `exp = maintenant + 540`, `iss = app_id`. La clé est décodée du base64 une fois ;
  - `branche_defaut(depot) -> str` : `GET /repos/{depot}` → `default_branch` ;
  - `branche_protegee(depot, branche) -> bool` : `GET /repos/{depot}/branches/{branche}` → `protected` ; toute erreur lève `ErreurGitHub` ;
  - `creer_pr(depot, branche, base, titre, corps) -> tuple[int, str]` avec `draft: true` ;
  - `etat_pr(depot, numero) -> Literal["ouverte", "fusionnee", "fermee"]` ;
  - `commenter(depot, numero, texte) -> None` ; `fermer_pr(depot, numero) -> None`.
- `FauxGitHub` dans `conftest.py` : même interface, état en mémoire (`protegee`, `prs`, `commentaires`, `etats`).

- [ ] **Étape 1 : tests** (`MockTransport`, clé RSA générée dans le test) : `test_jeton_cache_et_renouvele` (horloge injectée), `test_jwt_valide`, `test_branche_protegee_vrai_faux_erreur`, `test_creer_pr_draft`, `test_etat_pr` (`merged: true` → `fusionnee`, `state: closed` → `fermee`), `test_cle_base64_invalide_erreur_claire`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** tout vert.
- [ ] **Étape 5 : commit** `feat(portail): client GitHub App`.

### Task 6: troisième protection

**Fichiers :**
- Créer : `backend/portail/protections.py`, `backend/tests/test_protections.py`

**Interfaces :**
- `async def verifier_commits_code(espace: Espace, depuis: str, cfg: ConfigExecution) -> list[str]` : pour chaque commit de `espace.commits(depuis)` dont l'auteur est `agent-code@portail.local` :
  - chaque fichier qui `correspond` à `cfg.protege` → violation `"<fichier> (fichier de tests)"` ;
  - chaque manifeste touché (`pyproject.toml`, `package.json`, `Cargo.toml`, à tout niveau) : sections de tests comparées entre `sha^` et `sha` (`tomllib` / `json`) → violation `"<fichier> (section <clé>)"`. Sections : dans `pyproject.toml`, toute clé sous `tool.pytest` ; dans `package.json`, `jest`, `vitest` et toute entrée de `scripts` dont le nom contient `test` ; dans `Cargo.toml`, `dev-dependencies` et `test`. Un manifeste illisible d'un côté → violation `"<fichier> (illisible)"`.
  - Les autres auteurs sont ignorés.

- [ ] **Étape 1 : tests** (espaces git réels, comme la tâche 4) : `test_commit_code_touche_un_test`, `test_commit_code_change_tool_pytest`, `test_commit_code_ajoute_une_dependance_permis`, `test_package_json_script_test`, `test_cargo_dev_dependencies`, `test_commit_d_un_autre_auteur_ignore`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** tout vert.
- [ ] **Étape 5 : commit** `feat(portail): troisième protection sur les commits de l'agent de code`.

### Task 7: orchestrateur du pipeline `dev`

**Fichiers :**
- Créer : `backend/portail/dev.py`, `backend/tests/test_dev.py`
- Modifier : `backend/portail/moteur.py`, `backend/tests/conftest.py`

**Interfaces :**
- **Change A/B** : pour le type `dev`, `creer_pipeline` n'est pas utilisé. L'état d'un pipeline `dev` et de ses étapes est écrit **par `dev.py` seul** (sans `changer_etat`) : le pipeline est `en_cours` pendant l'exécution, `terminee` à l'ouverture de la PR, `echouee` sur *Bloquée* ou annulation. Chaque passage d'agent ajoute une `Etape(agent="tests"|"code"|"revue")`, chaque vérification du portail une `Etape(agent="portail", action=<phase>)`, avec un `ordre` croissant.
- `class Orchestrateur(sessions, catalogue, llm, lanceur, github, reglages, horloge=…)` :
  - `async demarrer(session, tache: Tache) -> Pipeline` : dans la transaction de l'appelant (l'ordonnanceur), crée le pipeline `dev` et l'`ExecutionDev` (`n`, `branche`, `espace`, `base` = `projet.branche_ref` ou `github.branche_defaut(depot)`), pose `tache.verrou` et passe la tâche en `en_cours` (verrou levé le temps du `deplacer_tache`, comme la route d'annulation) ;
  - `lancer(pipeline_id) -> None` : tâche de fond `executer`, gardée dans `taches: dict[int, asyncio.Task]` ;
  - `async executer(pipeline_id) -> None` : enveloppé par `asyncio.timeout(duree_max_tache_s)` ; déroule les phases depuis `ExecutionDev.phase`. **Chaque phase écrit son nom dans `phase` avant de commencer** ; une phase relancée commence par `espace.remettre_a_zero()` (sauf `preparation`, qui reclone).
  - `async bloquer(pipeline_id, raison: str) -> None`.
- `lancer` côté orchestrateur (fonction passée à `OutilsEspace`) : `ClientLanceur.lancer(espace, cfg.image, commande(cfg, nom, fichiers_tests), delai_commande_s, lecture_seule)` où `lecture_seule = dossiers_lecture_seule(cfg, racine)` pour le rôle `code`, `[]` sinon ; pour le rôle `code`, `empreinte(racine, cfg.protege)` avant et après, et restauration (`git checkout --` du fichier, ou suppression s'il était nouveau) de tout fichier changé, avec en fin de sortie `[fichiers de tests restaurés : …]`. Chaque appel enregistre une `CommandeLancee`.
- Phases (`cfg = lire_config(projet.config_execution)`, `racine = espaces_dir / espace`) :
  1. **`preparation`** : `branche_protegee(depot, base)` sinon *Bloquée* « branche par défaut non protégée » ; `cloner` (jeton de l'App) ; `services` si `cfg.services` ; `installer` (rôle `systeme`) : code non nul → *Bloquée* « installation échouée » avec la fin de la sortie ; `base_sha`.
  2. **`tests`** : boucle de l'agent `tests` avec `OutilsEspace(role="tests")`. Annexes : titre, description, critères, fichiers indicatifs, `apercu(racine, 25 % du contexte)`, `remarques`. Puis `restaurer(garder=correspond(·, cfg.protege))` ; les fichiers annulés sont notés dans un message `system`. `fichiers_tests` = changements qui `correspondent` à `cfg.chemins_tests`. Vide → *Bloquée* « aucun test écrit ». Sinon commit `agent-tests`.
  3. **`rouge`** (sauf après un renvoi aux tests, voir 6) : `tests_cibles` sur `fichiers_tests`. Code 0 → une seule fois retour à `tests` avec la remarque « les tests passent déjà : ils ne testent rien de nouveau », la deuxième fois *Bloquée* ; code 5 → *Bloquée* « aucun test collecté » ; délai dépassé → *Bloquée* ; sinon `sortie_rouge` est gardée.
  4. **`code`** : boucle de l'agent `code` avec `OutilsEspace(role="code")`, annexes : tâche, `fichiers_tests`, `sortie_rouge`, `remarques`. Puis `restaurer(garder=lambda c: not correspond(c, cfg.protege))` et commit `agent-code` (un commit vide n'est pas une erreur).
  5. **`verification`** : `tests_cibles` puis `tests` doivent rendre 0, sinon *Bloquée* avec les 3 000 derniers caractères de la sortie ; puis `verifier_commits_code(depuis=base_sha)` : une violation → *Bloquée* « protection des tests : … ».
  6. **`revue`** : agent `revue` (outils de lecture), annexes : tâche et `diff(base_sha)`. Réponse validée par `{"decision": "ok"|"renvoyer_tests"|"renvoyer_code", "remarques": [str]}` (`response_format` json_schema), une relance si invalide ; encore invalide → traité comme `ok` avec la remarque non résolue « revue automatique illisible ». Renvoi tant que `renvois < renvois_max` : `renvois += 1`, `remarques` = celles de la revue, puis `tests` → `code` → `verification` → `revue` (**sans** `rouge` : le code existe déjà) ou `code` → `verification` → `revue`. Au-delà, les remarques deviennent « non résolues ».
  7. **`pr`** : `pousser` ; `creer_pr(titre = titre de la tâche, corps)` — corps : lien vers le kanban (`/projets/<p>/kanban`) et le pipeline (`/pipelines/<id>`), critères, résumé de la revue, section « Remarques non résolues » s'il y en a ; `pr_numero`, `pr_url` ; tâche en `en_revue` en **gardant** le verrou ; pipeline `terminee` ; `services` arrêtés (`nettoyer`) ; phase `fini`. Si une `ExecutionDev` précédente de la même tâche a une PR encore `ouverte` : `commenter(« Remplacée par <url> »)` puis `fermer_pr`.
- **`bloquer(raison)`** : étape en cours `echouee` avec la raison ; tâche `bloquee`, `resume_blocage` = raison + une ligne par étape ; verrou levé ; si l'espace a au moins un commit d'agent et que la raison n'est pas une violation de protection, `pousser` (sans PR, au mieux : une erreur est seulement journalisée) et le nom de la branche est ajouté au résumé ; `lanceur.nettoyer`, `espace.supprimer()` ; pipeline `echouee`. Une erreur inattendue dans une phase (`ErreurLanceur`, `ErreurGitHub`, `ErreurDepot`, `ErreurLLM`, `ErreurOutils`) → `bloquer(str(erreur))`. Dépassement de la durée maximale → *Bloquée* « durée maximale dépassée ».

- [ ] **Étape 1 : tests** avec `FauxLLM` (réponses `completer` réglées à l'avance, dont des `tool_calls` vers `ecrire` et `lancer`), `FauxLanceur` (codes par commande) et `FauxGitHub`, dépôt d'origine `file://` :
  - `test_parcours_complet_ouvre_une_pr` : deux commits (`agent-tests` puis `agent-code`), PR en brouillon avec le bon corps, tâche `en_revue` avec verrou, pipeline `terminee`, `CommandeLancee` enregistrées ;
  - `test_aucun_test_ecrit_bloque` (avec `tests_cibles` qui rend 5) ;
  - `test_tests_qui_touche_src_est_annule` : l'agent `tests` écrit aussi `src/x.py` via un effet du `FauxLanceur` ; le commit `agent-tests` ne contient pas `src/x.py` ;
  - `test_rouge_qui_passe_renvoie_une_fois_puis_bloque` ;
  - `test_verification_rouge_bloque_avec_sortie` ;
  - `test_glob_protege_restaure_pour_code` : un effet du `FauxLanceur` modifie `conftest.py` pendant un `lancer` en rôle `code` ; le fichier est restauré et la sortie le dit ;
  - `test_violation_protection_bloque_sans_push` (commit `agent-code` fabriqué qui touche `tests/`) ;
  - `test_revue_renvoie_au_code_puis_ok` (`renvois == 1`, PR ouverte, aucune phase `rouge` après le renvoi) ;
  - `test_trois_renvois_ouvre_quand_meme_avec_remarques` ;
  - `test_branche_non_protegee_bloque` ;
  - `test_delai_depasse_en_verification_bloque` ;
  - `test_duree_max_tache` (`duree_max_tache_s=0.1`, faux modèle bloqué sur un `asyncio.Event`) ;
  - `test_blocage_pousse_la_branche_sans_pr`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** tout vert.
- [ ] **Étape 5 : commit** `feat(portail): orchestrateur du pipeline dev jusqu'à la PR en brouillon`.

### Task 8: ordonnanceur, annulation, relance et redémarrage

**Fichiers :**
- Créer : `backend/portail/ordonnanceur.py`, `backend/tests/test_ordonnanceur.py`
- Modifier : `backend/portail/api.py` (lifespan, routes d'annulation, réveil), `backend/portail/moteur.py`, `backend/portail/dev.py`

**Interfaces :**
- `async def choisir(session) -> Tache | None` : parmi les projets qui ont `depot_url` et `config_execution`, la tâche en `prete`, **sans verrou**, dont **toutes** les dépendances sont `terminee`, de plus petit `(rang, id)` ; `SELECT … FOR UPDATE SKIP LOCKED` sur la tâche.
- `class Ordonnanceur(sessions, orchestrateur, paralleles_max)` : `reveiller()` (un `asyncio.Event`) ; `async tourner()` : toutes les 30 s ou au réveil, tant que le nombre de tâches de fond actives de l'orchestrateur est inférieur à `paralleles_max`, `choisir` puis `orchestrateur.demarrer` **dans la même transaction**, commit, puis `orchestrateur.lancer`. Une exception est journalisée et la boucle continue.
- Les routes qui modifient le kanban (`ajouter`, `modifier`, `deplacer`, `annuler`, `accepter`, `tout_accepter`) appellent `reveiller()` après le commit.
- `async Orchestrateur.annuler(pipeline_id) -> None` : annule la tâche asyncio et l'attend ; `lanceur.arreter` puis `nettoyer` ; `espace.supprimer()` ; étape en cours `echouee` « annulé » ; pipeline `echouee` (s'il n'était pas `terminee`). `POST /api/taches/{id}/annuler` et `POST /api/pipelines/{id}/annuler` passent par lui pour un pipeline `dev` (y compris une tâche `en_revue` dont le pipeline est `terminee` : nettoyage seul) ; la route de tâche remet ensuite la tâche dans `a_faire` sans verrou, comme aujourd'hui.
- **Relance** : `n` = 1 + nombre d'`ExecutionDev` précédentes de la tâche (géré par `demarrer`).
- **Change A** : `recuperer_interrompues` ignore les étapes des pipelines `dev`.
- **Redémarrage** (lifespan, après la récupération de A, si l'App et le lanceur sont configurés) : pour chaque `ExecutionDev` de phase autre que `fini` dont le pipeline est `en_cours` : étape `en_cours` → `echouee` « interrompue par un redémarrage » (sans toucher l'état du pipeline), `interruptions += 1` ; si `interruptions <= 1`, `lancer` (la phase enregistrée repart) ; sinon `bloquer(« interrompue deux fois »)`. Puis démarrer l'ordonnanceur ; à l'arrêt, annuler sa boucle et les tâches de l'orchestrateur.

- [ ] **Étape 1 : tests**
  - `test_choisir_respecte_rang_dependances_verrou` : T1 (`prete`, rang 2000), T2 (`prete`, rang 1000, dépend de T3 `en_revue`), T4 (`prete`, rang 500, verrouillée) → T1 ;
  - `test_choisir_entre_projets` (plus petit `(rang, id)`) ; `test_projet_sans_config_ignore` ;
  - `test_paralleles_max_respecte` ;
  - `test_deux_choix_concurrents_jamais_la_meme_tache` (deux sessions) ;
  - `test_annuler_dev` (tâche en `a_faire`, verrou levé, espace supprimé, `arreter` appelé) ;
  - `test_relance_branche_n` (2e exécution : `…-2`, espace `tache-<id>-2`) et `test_relance_ferme_l_ancienne_pr` ;
  - `test_redemarrage_reprend_une_fois_puis_bloque` ;
  - `test_recuperer_interrompues_ignore_dev`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** tout vert.
- [ ] **Étape 5 : commit** `feat(portail): ordonnanceur, annulation, relance et redémarrage de la boucle de dev`.

### Task 9: suivi minimal des PR

**Fichiers :**
- Créer : `backend/portail/suivi_pr.py`, `backend/tests/test_suivi_pr.py`
- Modifier : `backend/portail/api.py` (lifespan)

**Interfaces :**
- `class SuiviPR(sessions, github, orchestrateur, ordonnanceur)` : `async passer() -> None` (un passage) et `async tourner()` (toutes les 120 s). Pour chaque tâche `en_revue` dont l'`ExecutionDev` la plus récente a `pr_numero` :
  - `fusionnee` → tâche `terminee`, verrou levé, nettoyage de l'espace (`lanceur.nettoyer`, `espace.supprimer()`), puis `ordonnanceur.reveiller()` ;
  - `fermee` → tâche `a_faire`, verrou levé, nettoyage ; la branche reste ;
  - `ouverte` → rien. Une `ErreurGitHub` sur une PR est journalisée et n'arrête pas le passage.
- Démarré au lifespan avec l'ordonnanceur, aux mêmes conditions.

- [ ] **Étape 1 : tests** avec `FauxGitHub` : `test_fusionnee_termine_et_libere`, `test_fermee_retour_a_faire`, `test_ouverte_rien`, `test_erreur_sur_une_pr_n_arrete_pas_les_autres`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** tout vert.
- [ ] **Étape 5 : commit** `feat(portail): suivi des PR (fusion et fermeture)`.

### Task 10: interface de la boucle de dev

**Fichiers :**
- Modifier : `backend/portail/schemas.py`, `backend/portail/api.py`, `frontend/src/api.ts`, `frontend/src/views/ProjetView.vue`, `frontend/src/views/PipelineView.vue`, `frontend/src/views/KanbanView.vue`, `frontend/src/components/CarteTache.vue`
- Créer : `frontend/src/components/ConfigExecution.vue`, `frontend/src/dev.ts`, `frontend/src/dev.test.ts`

**Interfaces :**
- Backend : `GET /api/pipelines/{id}` inclut `execution: {branche, phase, renvois, pr_url} | null` et `commandes: [{etape_id, nom, code, delai_depasse, sortie, debut, fin}]` ; `TacheVue` gagne `pr_url: str | None` (de l'`ExecutionDev` la plus récente) et `resume_blocage: str | None` ; `Kanban` (ou le détail du projet) indique `config_execution` présente ou non.
- `ConfigExecution.vue` (dans `ProjetView`) : `<textarea>` YAML pré-rempli d'un exemple EA commenté si vide, « Enregistrer » → `PUT /api/projets/{id}/execution` ; un 422 affiche son `detail`.
- `PipelineView`, pour un pipeline `dev` : bandeau (branche, phase, renvois, lien de la PR) ; sous chaque étape `portail` ou d'agent, ses `CommandeLancee` repliées (`<details>` : nom, code, durée, sortie dans `<pre>`).
- `CarteTache` : lien « PR #n » s'il existe ; `resume_blocage` replié sur une carte `bloquee`.
- `KanbanView` : bandeau « Sans config d'exécution, aucune tâche Prête ne démarre. » si le projet n'en a pas.
- `dev.ts` : `duree(debut: string, fin: string | null): string` (`"12 s"`, `"3 min 4 s"`, `"en cours"`) et `numeroPr(url: string): string` (`.../pull/42` → `"PR #42"`).

- [ ] **Étape 1 : tests** : `dev.test.ts` pour `duree` et `numeroPr` ; un test pytest pour les nouveaux champs du détail du pipeline et de `TacheVue`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** `npm test`, `npm run typecheck`, `npm run build` et `uv run pytest` verts.
- [ ] **Étape 5 : commit** `feat(portail): interface de la boucle de dev`.

### Task 11: image d'exécution, pile de déploiement et PR Infra

**Fichiers (dépôt AI) :**
- Créer : `execution/Dockerfile`
- Modifier : `Dockerfile`, `deploy/portainer-stack.yml`, `.github/workflows/deploy.yml`, `scripts/vault-render-env.sh`, `README.md`

**Changements :**
- `execution/Dockerfile` : `python:3.12-slim-bookworm`, Node 22 (binaire officiel ou `node:22-bookworm-slim` copié), `uv` (`COPY --from=ghcr.io/astral-sh/uv:0.9.8`), `git`, `ca-certificates`, utilisateur `agent` d'uid/gid 1000, `HOME=/home/agent`, rien d'autre.
- `Dockerfile` du portail : `useradd -u 1000 portail` ; dossiers `/donnees` et `/espaces` créés et possédés par 1000.
- `deploy.yml` : le job `image` construit aussi `ghcr.io/${{ github.repository }}-lanceur` (`lanceur/Dockerfile`) et `ghcr.io/${{ github.repository }}-execution` (`execution/Dockerfile`), mêmes tags.
- `deploy/portainer-stack.yml` :
  - volume des données renommé `portail-donnees-2` (l'ancien appartient à l'ancien uid ; ce n'était qu'un cache de clones) avec le commentaire `# ponytail: l'ancien volume portail-donnees reste orphelin, à supprimer à la main` ;
  - volume `portail-espaces` avec `name: portail-espaces` (nom fixe : le lanceur le désigne par ce nom), monté sur `/espaces` dans `portail` seulement ;
  - service `lanceur` : `ghcr.io/nicolaslallier/ai-lanceur:${IMAGE_TAG:-latest}`, `/var/run/docker.sock` monté **dans ce service seulement**, variables `LANCEUR_*` (secret `${PORTAIL_LANCEUR_SECRET:?}`, `LANCEUR_IMAGES=ghcr.io/nicolaslallier/ai-execution:latest`, `LANCEUR_IMAGES_SERVICES=pgvector/pgvector:pg16,postgres:16-alpine,minio/minio:latest`, `LANCEUR_PROXY=http://run-egress:3128`), réseau `portail-lanceur` (`internal: true`), aucun port, `mem_limit: 128m` ;
  - service `portail` : `PORTAIL_LANCEUR_URL`, `PORTAIL_LANCEUR_SECRET`, `PORTAIL_GITHUB_APP_ID`, `PORTAIL_GITHUB_APP_CLE`, réseau `portail-lanceur` en plus d'`infra-net`.
- `MAP` gagne `PORTAIL_GITHUB_APP_ID`, `PORTAIL_GITHUB_APP_CLE`, `PORTAIL_LANCEUR_SECRET`.
- README : section « GitHub App du portail » : la créer (Contents : Read & write, Pull requests : Read & write, Metadata : Read, **sans** Administration, sans webhook), l'installer sur les dépôts choisis, ranger l'id et `base64 -w0 cle.pem` dans OpenBao, `openssl rand -hex 32` pour `PORTAIL_LANCEUR_SECRET` ; la branche par défaut doit être protégée ; Docker 26 ou plus sur l'hôte ; la config d'exécution d'EA en exemple.

- [ ] **Étape 1 :** `docker build -f execution/Dockerfile .` et `docker build -f lanceur/Dockerfile lanceur` réussissent, et `docker run --rm <execution> sh -c 'id -u; python3 --version; node --version; uv --version'` donne `1000`, `3.12`, `v22` (si Docker local indisponible : parse YAML de la pile + vérification des clés, et le noter).
- [ ] **Étape 2 : commit** `feat(portail): image d'exécution, lanceur dans la pile et secrets de la GitHub App`.
- [ ] **Étape 3 : PR brouillon dans le dépôt Infra** (`~/Code/Infra`, nouvelle branche depuis `origin/main`, jamais de push sur `main`, jamais de fusion) :
  - réseau `run-net` `internal: true`, distinct de `dev-net`, **sur l'hôte Docker qui porte la pile `portail`** (à vérifier par le `PORTAINER_ENDPOINT_ID` du dépôt AI) ;
  - un squid `run-egress` à lui, sur `run-net` et un réseau de sortie, qui ne laisse passer que `pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`, `crates.io`, `static.crates.io`, `index.crates.io`, `github.com`, `codeload.github.com`, `objects.githubusercontent.com` ; ni `s3:8333`, ni adresse privée ; mêmes règles d'ordre et `dstdomain -n` que `dev-egress` (voir le `CLAUDE.md` de l'Infra) ;
  - le selftest de `portainer-stack.sh` mis à jour s'il fige les services ;
  - description : lien vers la PR du dépôt AI, et ce que Nicolas doit faire (secrets, App).

### Task 12: revue finale et PR

- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `alembic upgrade/check/downgrade`, `npm test`, `npm run typecheck`, `npm run build`, `cargo fmt --check`, `cargo clippy -- -D warnings`, `cargo test` : tous verts.
- [ ] Revue finale de toute la branche (superpowers:requesting-code-review), corrections.
- [ ] PR **en brouillon** vers `main` : résumé, ce qui n'a pas été vérifié en vrai (LiteLLM, Docker de l'hôte, App), étapes à faire par Nicolas avant fusion (App, trois secrets, PR Infra), lien vers la PR Infra. Pas de fusion.
