# Portail F — Sécurité et confidentialité : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Durcir la chaîne de livraison, les conteneurs et les données du portail, et prouver par des tests qu'aucun contenu ne fuit et qu'un agent manipulé ne sort pas de ses limites.

**Architecture:** Aucun service nouveau. Le backend gagne trois petits modules (`journal.py`, `audit.py`, une règle dans `agents.py`), le lanceur apprend à faire correspondre un nom d'image à un digest épinglé, et le reste est de la configuration (workflows, pile Portainer, vhost, Renovate). Les changements côté Infra sont préparés ici dans `deploy/` et recopiés par une PR Infra.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / Alembic / pytest ; Rust (bollard) ; Vue 3 / vitest ; GitHub Actions ; Docker Compose ; NGINX ; Renovate.

**Spec:** `docs/superpowers/specs/2026-11-14-portail-f-i-ameliorations-design.md`, section « F — Sécurité et confidentialité ».

## Global Constraints

- Français partout : noms, messages, commentaires, commits (style du dépôt : `feat(portail): …`, `fix(deploy): …`).
- Aucun journal, aucune métrique, aucune notification ne contient de contenu (prompt, spec, code, sortie de commande, titre de tâche) : seulement identifiants, compteurs, durées, codes et noms de classes d'erreur.
- Aucun workflow ne gagne de déclencheur `pull_request_target`, `issue_comment` ou `workflow_run` ; le runner `ai` ne tourne que sur `main`.
- Les conteneurs du lanceur gardent leur durcissement actuel ; pas de racine en lecture seule pour eux ; les conteneurs de service gardent leurs cinq capacités.
- Pas de refonte de `dev.py` ni de `api.py` : on y change des lignes, on n'y déplace rien.
- Une dépendance nouvelle seulement si une tâche la nomme. Ce plan n'en ajoute aucune au backend ni au frontend.
- Vérifications avant chaque commit backend : `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q`. Si la base de test a un schéma périmé : `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` sur `portail_test`.

## Review Focus

1. Un message d'exception qui porte du contenu (corps d'une réponse LiteLLM, sortie d'une commande) et finit dans un journal par `logger.exception` — tâche 5, test du marqueur.
2. Un projet existant dont la configuration nomme `ghcr.io/nicolaslallier/ai-execution:latest` ou `postgres:16-alpine` : il doit continuer de fonctionner après l'épinglage — tâche 2, tests de correspondance.
3. Une image demandée avec un digest que la liste ne porte pas, ou un nom qui n'est qu'un préfixe d'une entrée (`postgres:16` face à `postgres:16-alpine@sha256:…`) : refus — tâche 2.
4. Un `agents.yaml` sans `modeles_permis`, ou avec une liste vide : le portail refuse de démarrer avec un message clair — tâche 4.
5. Une action confirmée sans en-tête `X-Auth-Request-Email` (développement local) : l'audit inscrit `local`, il ne plante pas — tâche 7.

---

### Task 1 : Chaîne de livraison

**Files:**
- Modify: `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`
- Modify: `Dockerfile`, `lanceur/Dockerfile`, `execution/Dockerfile`
- Create: `renovate.json`
- Modify: `README.md` (section « Déploiement »)

**Interfaces:**
- Produces: le job `image` de `deploy.yml` expose la sortie `execution_digest` (`sha256:…`), consommée par la tâche 2.

- [ ] **Step 1 : `ci.yml` devient appelable.** Remplacer `on:` par `pull_request:` et `workflow_call:` (retirer `push: branches: [main]`). Les trois jobs restent sur `ubuntu-latest`.
- [ ] **Step 2 : le déploiement attend la CI.** Dans `deploy.yml`, ajouter le job `ci: uses: ./.github/workflows/ci.yml` et mettre `needs: ci` sur le job `image`. `deploy` garde `needs: image`.
- [ ] **Step 3 : job `securite` dans `ci.yml`**, bloquant, sur `ubuntu-latest`, quatre étapes :
  - `uvx pip-audit --strict` dans `backend` (sur `uv export --frozen --no-dev --format requirements-txt`) ;
  - `npm audit --audit-level=high --omit=dev` dans `frontend` ;
  - `cargo audit` dans `lanceur` (action `rustsec/audit-check` ou `cargo install cargo-audit --locked`) ;
  - `gitleaks` sur le dépôt (action `gitleaks/gitleaks-action`, `fetch-depth: 0`).
- [ ] **Step 4 : analyse des images.** Dans le job `image`, après chaque `build-push-action`, une étape `aquasecurity/trivy-action` sur l'image `…@${{ steps.<id>.outputs.digest }}` avec `severity: CRITICAL,HIGH`, `ignore-unfixed: true`, `exit-code: 1`. Donner un `id` à chaque étape de construction (`construire`, `construire-lanceur`, `construire-execution`). Déclarer `outputs: execution_digest: ${{ steps.construire-execution.outputs.digest }}` sur le job.
- [ ] **Step 5 : épingler toutes les actions par SHA** dans les deux workflows, avec la version en commentaire, comme le fait déjà le job `deploy` (`actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2`). Résoudre chaque SHA avec `gh api repos/<owner>/<action>/git/ref/tags/<tag> --jq .object.sha` (et suivre l'objet si c'est un tag annoté).
- [ ] **Step 6 : épingler les images de base par digest** dans les trois Dockerfile (`FROM image:tag@sha256:…`, y compris les `COPY --from=`). Résoudre avec `docker buildx imagetools inspect <image:tag> --format '{{.Manifest.Digest}}'`.
- [ ] **Step 7 : `renovate.json`.** Partir de celui de l'Infra (`config:recommended`, `docker:pinDigests`, `automerge: false`, `schedule: ["before 6am on saturday"]`, `prConcurrentLimit: 3`). Gestionnaires : `dockerfile`, `docker-compose`, `github-actions`, `pep621`, `npm`, `cargo`. Ajouter un `customManagers` de type `regex` sur `deploy/portainer-stack.yml` pour les entrées `nom:tag@sha256:…` de `LANCEUR_IMAGES_SERVICES` (datasource `docker`).
- [ ] **Step 8 : vérifier.** `actionlint` sur les deux workflows (ou `gh workflow view` après push) ; `docker build .`, `docker build lanceur`, `docker build execution` passent ; `grep -nE 'uses: [^@]+@v?[0-9]' .github/workflows/*.yml` ne renvoie rien.
- [ ] **Step 9 : README.** Dans « Déploiement », remplacer la ligne « Le déploiement n'attend pas la CI… » par : le déploiement rejoue la CI et ne construit rien si elle échoue ; lister les **étapes manuelles** : protection de `main` avec les contrôles `backend`, `frontend`, `lanceur`, `securite` ; installation de l'application Renovate sur le dépôt.
- [ ] **Step 10 : commit** `ci: la CI bloque le déploiement, actions et images épinglées, audits`.

### Task 2 : Le lanceur exécute des digests épinglés

**Files:**
- Modify: `lanceur/src/config.rs`, `lanceur/src/conteneurs.rs:102-145`
- Modify: `deploy/portainer-stack.yml`, `.github/workflows/deploy.yml`, `scripts/portainer-stack.sh` (si la liste des variables y est figée)

**Interfaces:**
- Consumes: `needs.image.outputs.execution_digest` (tâche 1).
- Produces: `pub fn epinglee<'a>(liste: &'a [String], demandee: &str) -> Option<&'a str>` dans `config.rs`.

- [ ] **Step 1 : tests qui échouent** dans `config.rs` :

```rust
#[test]
fn image_epinglee() {
    let l = vec!["postgres:16-alpine@sha256:aaa".to_string(), "busybox:1.36".to_string()];
    assert_eq!(epinglee(&l, "postgres:16-alpine"), Some("postgres:16-alpine@sha256:aaa"));
    assert_eq!(epinglee(&l, "postgres:16-alpine@sha256:aaa"), Some("postgres:16-alpine@sha256:aaa"));
    assert_eq!(epinglee(&l, "busybox:1.36"), Some("busybox:1.36"));
    assert_eq!(epinglee(&l, "postgres:16"), None);            // préfixe : refusé
    assert_eq!(epinglee(&l, "postgres:16-alpine@sha256:bbb"), None); // autre digest : refusé
    assert_eq!(epinglee(&l, "busybox:1.36@sha256:ccc"), None);
}
```

- [ ] **Step 2 :** `cargo test image_epinglee` échoue (fonction absente).
- [ ] **Step 3 : implémenter `epinglee`** : une entrée correspond si elle est égale à la demande, ou si sa partie avant `@` est égale à la demande. Rien d'autre.
- [ ] **Step 4 : s'en servir.** Dans `valider_services` (ligne 107) et `specification` (ligne 143), remplacer les `contains` / `any` par `epinglee`, et **démarrer la référence renvoyée**, pas celle de la demande. Ajouter aux tests existants `image_refusee` et `service_durci` un cas où la demande `nom:tag` produit un `ContainerCreateBody.image` égal à `nom:tag@sha256:…`.
- [ ] **Step 5 :** `cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test` passent.
- [ ] **Step 6 : pile.** Dans `deploy/portainer-stack.yml` :
  - `LANCEUR_IMAGES: ghcr.io/nicolaslallier/ai-execution:latest@${EXECUTION_DIGEST:?}` ;
  - `LANCEUR_IMAGES_SERVICES` : les trois images actuelles avec leur digest (`pgvector/pgvector:pg16@sha256:…,postgres:16-alpine@sha256:…,minio/minio:<tag daté>@sha256:…` — remplacer `minio/minio:latest` par le tag daté courant et le noter dans le README, car les projets devront nommer ce tag).
- [ ] **Step 7 : déploiement.** Dans le job `deploy`, ajouter `EXECUTION_DIGEST: ${{ needs.image.outputs.execution_digest }}` à l'environnement et l'écrire dans `$PORTAIL_STACK_ENV` à côté de `IMAGE_TAG` ; l'ajouter à la boucle qui vérifie les variables obligatoires.
- [ ] **Step 8 : commit** `feat(lanceur): images épinglées par digest, nommées par tag`.

### Task 3 : Conteneurs durcis et journaux privés

**Files:**
- Modify: `deploy/portainer-stack.yml`
- Modify: `lanceur/src/conteneurs.rs:125-130` (`libelle`), `lanceur/tests/docker.rs`
- Create: `deploy/infra/alloy-journaux-prives.alloy`, `deploy/infra/README.md`

- [ ] **Step 1 : test qui échoue** dans `conteneurs.rs`, à côté de `durcissement` :

```rust
#[test]
fn journaux_prives() {
    let c = spec(&[]).unwrap();
    assert_eq!(c.labels.unwrap().get("portail.journaux").map(String::as_str), Some("prives"));
}
```

- [ ] **Step 2 :** il échoue. **Step 3 :** `libelle(espace)` ajoute `portail.journaux=prives` ; les trois appelants (`specification`, les deux créations de `services`) en héritent. **Step 4 :** `cargo test` passe.
- [ ] **Step 5 : test d'intégration** dans `lanceur/tests/docker.rs` (`#[ignore]`, même banc `Banc`) : `sans_route_directe` lance `wget -T 3 -q -O- http://1.1.1.1` sur le réseau `internal` du banc et attend un code de sortie non nul. `cargo test -- --ignored sans_route_directe` passe.
- [ ] **Step 6 : pile.** Sur `portail` et `lanceur` : `read_only: true`, `cap_drop: [ALL]`, `security_opt: ["no-new-privileges:true"]`, `tmpfs: [/tmp]`. Rien d'autre ne change.
- [ ] **Step 7 : vérifier le portail en lecture seule** avec la base de test :

```bash
docker compose -f docker-compose.test.yml up -d
docker build -t portail-local .
docker run --rm --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  --network host -v portail-essai:/donnees -v portail-essai-e:/espaces \
  -e PORTAIL_DATABASE_URL=postgresql+psycopg://portail:portail@localhost:5433/portail_test \
  -d --name portail-essai portail-local
sleep 8 && curl -fsS localhost:8000/api/sante   # attendu : {"ok":true}
docker logs portail-essai 2>&1 | grep -i 'read-only' ; docker rm -f portail-essai
```

  Attendu : `{"ok":true}` et aucune ligne « Read-only file system ». Si une écriture échoue, ajouter le chemin en `tmpfs` (jamais retirer `read_only`).
- [ ] **Step 8 : côté Infra.** `deploy/infra/alloy-journaux-prives.alloy` contient la règle à insérer dans `discovery.relabel` de `monitoring/alloy/config.alloy` de l'Infra :

```alloy
rule {
	source_labels = ["__meta_docker_container_label_portail_journaux"]
	regex         = "prives"
	action        = "drop"
}
```

  `deploy/infra/README.md` liste ce que la PR Infra de F doit recopier : cette règle, le vhost (tâche 9), et la vérification à faire après déploiement (`{container=~"run-.*"}` vide dans Loki ; adapter au préfixe réel des conteneurs du lanceur).
- [ ] **Step 9 : commit** `feat(deploy): conteneurs en lecture seule, journaux d'exécution hors de Loki`.

### Task 4 : Modèles permis

**Files:**
- Modify: `backend/portail/agents.py` (`Catalogue`, `charger_catalogue`), `agents.yaml`
- Test: `backend/tests/test_agents.py`

**Interfaces:**
- Produces: `Catalogue.modeles_permis: list[str]` (défaut `[]` pour les catalogues construits en test) ; `charger_catalogue` l'exige.

- [ ] **Step 1 : tests qui échouent**, sur des YAML écrits dans `tmp_path` comme les tests voisins :
  - `test_modeles_permis_absents` : sans la clé → `CatalogueInvalide` dont le message contient `modeles_permis` ;
  - `test_modeles_permis_vides` : `modeles_permis: []` → `CatalogueInvalide` ;
  - `test_modele_hors_liste` : un agent avec `modele: gpt-x` et `modeles_permis: [qwen3.8:27b-mlx]` → `CatalogueInvalide` contenant `agent « <nom> »` et `gpt-x` ;
  - `test_catalogue_du_depot` : `charger_catalogue(Path("../agents.yaml"))` réussit.
- [ ] **Step 2 :** ils échouent. **Step 3 :** ajouter le champ à `Catalogue`, la lecture et les deux contrôles dans `charger_catalogue` ; ajouter en tête de `agents.yaml` `modeles_permis: [qwen3.8:27b-mlx]`. **Step 4 :** la suite passe.
- [ ] **Step 5 : README**, étapes manuelles : remplacer `PORTAIL_LITELLM_CLE` dans OpenBao par une clé LiteLLM limitée aux modèles de `modeles_permis` (jamais la clé maîtresse).
- [ ] **Step 6 : commit** `feat(portail): liste blanche des modèles`.

### Task 5 : Journaux sans contenu

**Files:**
- Create: `backend/portail/journal.py`
- Modify: tous les `logger.exception(…)` de `backend/portail/` (20 appels : `api.py`, `chat.py`, `conversations.py`, `dev.py`, `ordonnanceur.py`, `suivi_pr.py`) ; `dev.py:847`, `dev.py:932-945`, `dev.py:1010` ; `api.py` (gestionnaire d'exception)
- Modify: `lanceur/src/conteneurs.rs:278`
- Test: `backend/tests/test_journal.py`

**Interfaces:**
- Produces: `journal.erreur(logger: logging.Logger, message: str, *args: object) -> None` — à appeler dans un `except`. Journalise `message % args`, le nom de la classe de l'exception en cours et les cadres de la pile (`traceback.format_tb`), **jamais** `str(exception)`.

- [ ] **Step 1 : tests qui échouent** dans `test_journal.py`, avec `caplog` et le marqueur `MARQUEUR = "ZZ-secret-7731"` :
  - `test_erreur_sans_message_d_exception` : lever `ValueError(MARQUEUR)`, appeler `journal.erreur(logger, "tâche %s", 4)` ; le texte journalisé contient `tâche 4` et `ValueError`, pas `MARQUEUR` ;
  - `test_mission_complete_sans_contenu` : avec les fixtures de `test_dev.py`, dérouler un pipeline `dev` où le marqueur figure dans le titre de la tâche, dans un fichier du dépôt, dans la sortie d'une commande (faux lanceur), dans une réponse du `FauxLLM` et dans le message d'une `ErreurLLM` levée en cours de route ; `MARQUEUR not in caplog.text` ;
  - `test_conversation_sans_contenu` : même principe sur une conversation de l'orchestrateur dont le `FauxLLM` lève une exception portant le marqueur ;
  - `test_route_500_sans_contenu` : une route qui lève `RuntimeError(MARQUEUR)` répond 500 `{"detail": "erreur interne"}` et `MARQUEUR not in caplog.text`.
- [ ] **Step 2 :** ils échouent.
- [ ] **Step 3 : `journal.erreur`**, puis remplacer chaque `logger.exception(` par `journal.erreur(logger, ` (mêmes arguments).
- [ ] **Step 4 : appels qui journalisent du contenu.**
  - `dev.py:847` : `logger.warning("pipeline dev %s bloqué", pipeline_id)` (la raison reste en base, dans `resume_blocage`) ;
  - `dev.py:932-945` : même traitement, identifiants seulement ;
  - `dev.py:1010` : journaliser le nombre de violations, pas les chemins ;
  - `conteneurs.rs:278` : garder l'image, remplacer `{e:?}` par la seule catégorie d'erreur si elle peut contenir une réponse du registre.
- [ ] **Step 5 : gestionnaire global** dans `create_app` : `@app.exception_handler(Exception)` → `journal.erreur(logger, "erreur interne sur %s %s", methode, modele_de_route)` et `JSONResponse(500, {"detail": "erreur interne"})`. Journaliser le modèle de route (`/api/taches/{tache_id}`), pas l'URL.
- [ ] **Step 6 :** la suite passe ; `grep -rn 'logger.exception' backend/portail` ne renvoie rien.
- [ ] **Step 7 : commit** `feat(portail): journaux sans contenu`.

### Task 6 : Notifications sobres et suppression réelle

**Files:**
- Modify: `backend/portail/dev.py:185-187, 787, 883, 937`, `backend/portail/ordonnanceur.py:118-131`, `backend/portail/notifications.py` (retirer `raison_courte`)
- Test: `backend/tests/test_notifications.py`, `backend/tests/test_dev.py`, `backend/tests/test_ordonnanceur.py`, `backend/tests/test_conversations.py`

**Interfaces:**
- Produces: `Orchestrateur.notifier(self, tache_id: int, message: str, lien: str | None) -> None`. Titre envoyé : `Portail — tâche T{tache_id}`. Messages permis, exactement : `PR ouverte`, `Bloquée`, `Reprise échouée`.

- [ ] **Step 1 : tests qui échouent.** Dans les tests existants qui observent le faux notifieur, attendre le nouveau titre et les trois messages exacts ; ajouter `test_notification_sans_contenu` : une tâche titrée `MARQUEUR`, bloquée avec une raison contenant `MARQUEUR` → ni le titre ni le message envoyés ne le contiennent.
- [ ] **Step 2 :** ils échouent. **Step 3 :** changer la signature et les quatre appelants ; supprimer `raison_courte` et ses tests. **Step 4 :** la suite passe.
- [ ] **Step 5 : test de suppression** dans `test_conversations.py`, `test_suppression_efface_messages_et_actions` : créer une conversation avec deux messages et une action proposée, la supprimer, puis compter les lignes de `message_conversation` et `action_conversation` pour cet identifiant : zéro. (Les clés étrangères sont déjà `ON DELETE CASCADE` : ce test fixe le comportement.)
- [ ] **Step 6 : commit** `feat(portail): notifications sans contenu`.

### Task 7 : Journal d'audit

**Files:**
- Create: `backend/portail/audit.py`, `backend/migrations/versions/0007_audit.py`
- Modify: `backend/portail/db.py` (modèle `Audit`), `backend/portail/schemas.py` (`AuditOut`), `backend/portail/api.py`, `backend/portail/conversations.py` (`confirmer`, `refuser`), `backend/portail/ordonnanceur.py`
- Create: `frontend/src/views/AuditView.vue` ; Modify: `frontend/src/api.ts`, `frontend/src/router.ts`, `frontend/src/App.vue`
- Test: `backend/tests/test_audit.py`

**Interfaces:**
- Produces:
  - table `audit` : `id`, `quand` (horodatage avec fuseau, défaut maintenant, indexé), `auteur` (texte), `action` (texte), `objet` (texte : `pipeline`, `tache`, `proposition`, `action_conversation`, `etape`), `objet_id` (entier, **sans** clé étrangère : la ligne survit à l'objet) ;
  - `audit.inscrire(session: AsyncSession, auteur: str, action: str, objet: str, objet_id: int) -> None` (ajoute à la session, ne valide pas) ;
  - `audit.auteur_de(request: Request) -> str` : l'en-tête `X-Auth-Request-Email`, sinon `"local"` ;
  - `GET /api/audit?limite=100&avant=<id>` → `list[AuditOut]`, du plus récent au plus ancien, `limite` bornée à 500.
- Actions inscrites (valeurs exactes de `action`) : `pipeline.lancer`, `pipeline.annuler`, `etape.valider`, `proposition.accepter`, `proposition.rejeter`, `propositions.tout_accepter`, `action.confirmer`, `action.refuser`, `tache.creer`, `tache.modifier`, `tache.deplacer`, `tache.supprimer`, `tache.annuler`, `projet.creer`. L'ordonnanceur inscrit `pipeline.lancer` avec l'auteur `ordonnanceur`.

- [ ] **Step 1 : tests qui échouent** dans `test_audit.py` (client HTTP des fixtures existantes) :
  - `test_confirmer_inscrit` : confirmer une action avec l'en-tête `X-Auth-Request-Email: n@exemple.net` → une ligne `action.confirmer`, `objet="action_conversation"`, `auteur="n@exemple.net"` ;
  - `test_sans_entete_local` : la même sans en-tête (réglage `exiger_utilisateur=False`) → `auteur="local"` ;
  - `test_refuser_deplacer_annuler` : une ligne par appel, avec la bonne valeur d'`action` ;
  - `test_echec_non_inscrit` : une route qui répond 409 n'inscrit rien ;
  - `test_lecture` : `GET /api/audit?limite=2` renvoie deux lignes, la plus récente d'abord ; `avant=<id>` pagine ;
  - `test_pas_d_ecriture` : `POST`, `PUT`, `PATCH` et `DELETE` sur `/api/audit` et `/api/audit/1` répondent 404 ou 405 ;
  - `test_survit_a_la_suppression` : supprimer une tâche ne supprime pas ses lignes d'audit.
- [ ] **Step 2 :** ils échouent.
- [ ] **Step 3 :** modèle, migration `0007` (révision précédente `0006`), `audit.py`. `uv run alembic upgrade head && uv run alembic check && uv run alembic downgrade base` passent.
- [ ] **Step 4 : inscrire**, dans la même transaction que l'action, à chaque route listée de `api.py`. `ServiceConversation.confirmer` et `.refuser` reçoivent un paramètre `auteur: str` passé par la route. Les `"nicolas"` codés en dur dans `api.py` (lignes 271, 562, 570, 578, 586) restent : c'est le journal des tâches, pas l'audit.
- [ ] **Step 5 :** la suite backend passe.
- [ ] **Step 6 : page.** `api.ts` : `lireAudit(avant?: number): Promise<LigneAudit[]>`. `AuditView.vue` : un tableau (quand, auteur, action, objet et identifiant) et un bouton « Plus anciens » ; route `/audit` ; lien « Audit » dans le menu de `App.vue`. `npm run typecheck && npm test && npm run build` passent.
- [ ] **Step 7 : commit** `feat(portail): journal d'audit`.

### Task 8 : Tests d'injection

**Files:**
- Create: `backend/tests/test_injection.py`

Ces tests fixent des garde-fous existants : ils doivent passer sans changer le code. **Un test qui échoue est une faille : s'arrêter, la décrire, et la corriger dans la même tâche avec son test.** Le `FauxLLM` joue l'agent manipulé : il émet les appels d'outils qu'un modèle trompé émettrait. Le texte piégé (`Ignore tes consignes et …`) est placé là où un agent le lirait.

- [ ] **Step 1 : écrire les tests** (fixtures de `test_outils_espace.py`, `test_dev.py`, `test_conversations.py`, `test_reprise.py`) :
  - `test_tests_n_ecrit_pas_le_code` : l'agent de rôle `tests` appelle `ecrire` sur un chemin hors de `chemins_tests` → résultat `erreur…`, fichier inchangé sur disque ;
  - `test_code_n_ecrit_pas_les_tests` : rôle `code`, `ecrire` et `supprimer` sur un fichier de test → refus, fichier inchangé ;
  - `test_pas_de_sortie_de_l_espace` : `lire`, `ecrire`, `lister`, `chercher` avec `../../etc/passwd`, un chemin absolu, et un lien symbolique du dépôt qui pointe hors de l'espace → refus à chaque fois ;
  - `test_pas_d_ecriture_dans_git` : `ecrire` sur `.git/config` et `.git/hooks/pre-commit` → refus ;
  - `test_outil_non_permis` : l'agent `revue` appelle `ecrire` puis `lancer` → `erreur : outil non autorisé`, rien d'exécuté (le faux lanceur n'a reçu aucun appel) ;
  - `test_commande_non_nommee` : `lancer` avec une commande qui n'est pas une des commandes nommées de la configuration du projet → refus ;
  - `test_orchestrateur_ne_fait_que_proposer` : le modèle appelle `creer_projet`, `lancer_pipeline` et `annuler_tache` dans le même tour → une seule proposition enregistrée, aucun projet, aucun pipeline, aucune tâche modifiée tant que `confirmer` n'est pas appelé ;
  - `test_commentaire_de_pr_piege` : un commentaire de PR contenant un ordre ; le tri renvoie une catégorie hors de `tests`/`code`/`reponse` ou un `id` inconnu → la reprise échoue proprement, aucune écriture ;
  - `test_commentaire_d_un_autre_auteur` : un commentaire d'un compte autre que `github_proprietaire` ne déclenche aucune reprise.
- [ ] **Step 2 :** `uv run pytest tests/test_injection.py -v` — tous passent, ou une faille est trouvée et traitée comme dit plus haut.
- [ ] **Step 3 : commit** `test(portail): garde-fous face à un agent manipulé`.

### Task 9 : Frontal

**Files:**
- Modify: `backend/portail/api.py:624-687`, `deploy/nginx/portail.conf`
- Test: `backend/tests/test_api_projets.py` (ou le fichier qui teste déjà `/api/evenements`)

- [ ] **Step 1 : test qui échoue** `test_flux_sans_tampon` : pour `/api/etapes/{id}/flux`, `/api/conversations/{id}/flux` et `/api/evenements`, la réponse porte `X-Accel-Buffering: no` et `Cache-Control: no-cache`.
- [ ] **Step 2 :** il échoue sur les deux premières. **Step 3 :** une fonction locale `_flux(generateur) -> StreamingResponse` dans `api.py` qui pose le type et les deux en-têtes ; les trois routes l'utilisent. **Step 4 :** il passe.
- [ ] **Step 5 : vhost.** Dans `deploy/nginx/portail.conf` :
  - au niveau `server`, avec `always` :
    - `Content-Security-Policy "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"` (pas d'image externe : une réponse de modèle ne peut pas faire sortir de données par une URL d'image) ;
    - `X-Content-Type-Options nosniff` ; `Referrer-Policy no-referrer` ;
  - un bloc `location ~ ^/api/(evenements|conversations/[0-9]+/flux)$` identique au bloc `/api/etapes/` (auth, `proxy_buffering off`, `proxy_read_timeout 1h`).
  - Rappel : `add_header` dans un `location` annule ceux du `server` ; n'en mettre dans aucun `location`.
- [ ] **Step 6 : vérifier la syntaxe** : `docker run --rm -v "$PWD/deploy/nginx/portail.conf:/etc/nginx/conf.d/portail.conf:ro" nginx:stable nginx -t` échouera sur les `include` et le certificat absents ; à la place, relire le diff et noter dans `deploy/infra/README.md` la vérification à faire après la PR Infra : la page Chat s'affiche sans erreur CSP dans la console, et une réponse de l'orchestrateur arrive au fil de l'eau.
- [ ] **Step 7 : commit** `feat(deploy): en-têtes de sécurité, flux en direct sans tampon`.

### Task 10 : Documentation et étapes manuelles

**Files:**
- Modify: `README.md`

- [ ] **Step 1 :** ajouter une section « Sécurité » qui dit, en une ligne chacune : ce que la CI bloque, comment les images sont épinglées et comment un projet nomme une image, où est le journal d'audit, la règle « aucun contenu dans les journaux », et la liste des **étapes manuelles de Nicolas** :
  1. protéger `main` avec les quatre contrôles ;
  2. installer Renovate ;
  3. émettre la clé LiteLLM limitée et la ranger dans OpenBao ;
  4. vérifier que la base `portail` et le volume `portail-donnees-2` sont dans les sauvegardes chiffrées de l'Infra, sinon les y ajouter ;
  5. ouvrir la PR Infra décrite dans `deploy/infra/README.md` ;
  6. décider si le dépôt devient privé (question ouverte de la spec).
- [ ] **Step 2 : commit** `docs: sécurité et étapes manuelles du lot F`.

---

## Ordre et dépendances

Tâche 1 avant 2 (sortie `execution_digest`). Les tâches 3 à 9 sont indépendantes entre elles, sauf 7 et 9 qui touchent toutes deux `api.py` : les faire l'une après l'autre. La tâche 10 en dernier.

**Avant de fusionner dans `main` :** la tâche 2 change le nom des variables de la pile. `EXECUTION_DIGEST` est fourni par le workflow, rien à ranger dans OpenBao.
