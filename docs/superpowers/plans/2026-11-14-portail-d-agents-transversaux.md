# Portail — D : agents transversaux : plan d'implémentation

> **Pour les agents qui exécutent :** SOUS-SKILL REQUIS : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans, tâche par tâche. Les étapes utilisent des cases `- [ ]`.

**But :** ajouter les agents de contrôle et de suivi.
- Dans le pipeline `dev` : un **challenger** qui s'appuie sur des faits vérifiés par du code, la **sécurité** et la **documentation**.
- Sur les brouillons de spec et de plan : les **avis** de l'**architecte** et du challenger.
- Un **PM** en chat (une conversation d'agent `pm`, sur le modèle du chat de E), avec un résumé du matin envoyé par ntfy.
- Un **arbitre** qui partage les modèles locaux en donnant la priorité à l'interactif.

**Architecture :** on étend ce qui existe, sans nouveau service.
- L'`Orchestrateur` de `dev.py` généralise sa phase `revue` en une phase **`controles`** qui parcourt les agents placés après `code` dans `pipelines.dev`, avec le compteur de renvois existant (`ExecutionDev.renvois`).
- Un module `faits` fait les vérifications sans modèle.
- Les avis sont des lignes en base (table `avis`), produites en tâche de fond par un `ServiceAvis`.
- Le PM est une `Conversation` (table de E) avec une nouvelle colonne `agent`, servie par `ServiceConversation` et `OutilsPortail` (outils de lecture seulement).
- Les règles d'écriture du rôle `doc` vivent dans `OutilsEspace` (`backend/portail/outils.py`), comme celles des rôles `tests` et `code`. Le lanceur Rust ne gagne qu'un champ : monter tout `/travail` en lecture seule.

**Pile :** celle de A, B, C et E. Aucune nouvelle dépendance (`zoneinfo` vient de la bibliothèque standard).

**Spec :** `docs/superpowers/specs/2026-11-14-portail-d-agents-transversaux-design.md`. Ce plan s'appuie sur le code fusionné de A, B, C1, C2 (tâches 1 à 5) et E.

## Révision du 2026-11-14

Le plan initial précédait C1, C2 et E. Écarts corrigés contre le code de `main` (82529fc) :
- Migration : `0004` à `0006` existent ; celle de D est `backend/migrations/versions/0007_agents_transversaux.py` (`down_revision = "0006"`).
- `backend/portail/outils_espace.py` n'existe pas : `OutilsEspace` est dans `backend/portail/outils.py`, ses tests dans `backend/tests/test_outils_espace.py`.
- `verifier_commits_code(espace, depuis, cfg)` garde son nom et sa signature (pas de `client`) ; on l'étend aux commits `agent-doc`, sans renommer (les tests de `test_dev.py` le remplacent par `monkeypatch`).
- Le lanceur n'a ni rôle, ni `chemins.rs`, ni `Regles` : le rôle `doc` est une règle d'`OutilsEspace` ; « revue en lecture seule » devient un champ `tout_lecture_seule` de `DemandeLancer` (le champ `lecture_seule` existant refuse `.`).
- `lancer` est refusé aux agents `verdict` par `agents.py` et `OutilsEspace(role="revue")` n'offre pas `lancer` : les deux s'assouplissent pour la seule commande `securite`.
- `produit: travail` exige `lancer` : le rôle `doc` (sans `lancer`) y fait exception. Pas de `produit` `avis` ni `chat` : un agent d'avis se reconnaît à sa `consigne_avis`, un agent de conversation à ses outils du portail (règle de E).
- PM : plus de pipeline `pm` ni de `Pipeline.projet_id` nullable ; c'est une `Conversation` avec `agent` (défaut `orchestrateur`). Outils : les cinq de lecture de E (`lister_projets`, `lire_projet`, `lister_pipelines`, `lire_pipeline`, `lire_kanban`) plus `en_attente_de_nicolas` et `activite`, jamais d'outil d'action.
- Le test existant `test_agents_yaml_du_depot_a_l_orchestrateur` compare à `OUTILS_PORTAIL` : il exclut désormais les deux outils du PM.
- `ClientLLM` a `flux(modele, messages, temperature)` et `completer(modele, messages, temperature, outils=None, response_format=None)` ; `boucle_outils(llm, agent, messages, outils, sur_appel)` lit `agent.modele` : le modèle du challenger passe par `agent.model_copy(update={"modele": ...})`.
- Le LLM est construit dans le lifespan de `api.py` et partagé par `ServiceChat`, `ServiceConversation` et `Orchestrateur` (via `_orchestrateur(r, sessions, catalogue, llm)`) : c'est là qu'on enveloppe, pas dans `chat.py` ni `dev.py`.
- Phases réelles de `dev.py` : `preparation`, `tests`, `rouge`, `code`, `verification`, `revue`, `pr`, `fini` (reprise : `attente`, `tri`, `reponses`). La phase `revue` est renommée `controles` par une mise à jour de données dans `0007`, sans compatibilité en lecture.
- Une seule phase `controles` (avec `ExecutionDev.controle_courant`) couvre aussi l'agent `doc` : pas de phase `doc` séparée.
- `Verdict` (dans `dev.py`) gagne `notes` ; `_revue` devient `_controles`.
- Vérification « rouge » après un renvoi aux tests : prévue par la spec, absente du plan initial ; ajoutée à la tâche 4 (colonne `fichiers_rouge`). Elle remplace le test C1 `test_revue_renvoie_aux_tests_saute_le_rouge`.
- Installation : `_verification` réinstalle déjà avant les contrôles ; on ne relance pas `installer` avant le challenger. L'échec d'installation en vérification devient un fait `installation` qui renvoie au code (dans la limite des renvois), au lieu d'un blocage immédiat.
- Reprise sur commentaires : C2 n'a construit que `preparation → tri → reponses` (tâche 6 de C2, « travail des agents », non faite) ; D ne touche pas la reprise. Le compteur repart déjà à zéro : chaque reprise est une nouvelle `ExecutionDev` (`renvois = 0`).
- Faux de test réels : `FauxLLM`, `FauxLanceur`, `FauxNotifieur`, `FauxGitHub` (`backend/tests/conftest.py`), `Monde` et `CATALOGUE` (`backend/tests/test_dev.py`). `FauxLanceur.lancer` gagne le paramètre `tout_lecture_seule=False`.
- Avis : l'état `en_cours` est une ligne `avis` (pas un dictionnaire en mémoire), ce qui donne « Avis en cours » au détail du pipeline sans nouvel état de service ; au démarrage, les `en_cours` deviennent `abandonne`.
- Notifications : `Notifieur(url, sujet, jeton).envoyer(titre, message, lien)` n'est construit que dans `_orchestrateur` ; le résumé en construit un dans le lifespan, et utilise `lien_absolu(r.url_publique, f"/chat/{id}")`.
- Résumé du matin : il passe par `ServiceConversation` (priorité interactive), pas par un LLM « fond ».
- Interface : pas de `TiroirPM` ni de `ControlesDev` ; le PM réutilise `ChatView.vue` (lien « Chat » de l'en-tête, déjà sur toutes les pages), les contrôles sont déjà des étapes affichées par `PipelineView.vue`, qui gagne seulement les notes.
- Commandes de vérification : celles de `.github/workflows/ci.yml` (voir Contraintes globales).

## Contraintes globales

- Toutes les contraintes de A, B, C et E s'appliquent toujours.
- **Chaque tâche laisse la CI verte.** Commandes (celles de `.github/workflows/ci.yml`) :
  - `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest` (Postgres de test sur `localhost:5433`, ou `PORTAIL_TEST_DATABASE_URL`) ; dès qu'une tâche touche `db.py` : `uv run alembic upgrade head && uv run alembic check && uv run alembic downgrade base` ;
  - `cd frontend && npm run typecheck && npm test && npm run build` ;
  - `cd lanceur && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test` (et `cargo test -- --ignored` avec Docker, tâche 3).
- **Migration unique** `0007_agents_transversaux.py`, créée à la tâche 4 et complétée par les tâches 6, 7 et 8 : à chaque tâche, `alembic check` ne voit aucun écart avec `db.py`.
- **Verdict de contrôle**, commun à tous les agents de contrôle : `{"decision": "ok" | "renvoyer_tests" | "renvoyer_code", "remarques": [str], "notes": [str]}`. Les `remarques` accompagnent un renvoi. Les `notes` ne bloquent jamais.
- **Un seul compteur de renvois** par exécution `dev` : `ExecutionDev.renvois`, plafonné par `Reglages.renvois_max` (2, `PORTAIL_RENVOIS_MAX`). Une fois la limite atteinte, les contrôles restants **tournent quand même** ; une décision de renvoi devient alors une « remarque non résolue » de la PR.
- **Ordre du pipeline `dev`** dans `agents.yaml` : `pipelines.dev: [tests, code, revue, challenger, securite, doc]`. Les contrôles sont les agents qui suivent `code`. En retirer un de la liste le désactive.
- **Challenger** : son modèle est `modele_si_meme` quand `modele` est égal à celui de l'**auteur principal** (l'agent `code` dans `dev`, l'agent de l'étape qui rédige pour un avis). `modele` et `modele_si_meme` doivent être différents, sinon le catalogue est refusé au démarrage.
- **Rôle `doc`** : il écrit **seulement** dans `ConfigExecution.chemins_doc` (par défaut `["README.md", "docs/**", "CHANGELOG.md"]`), jamais dans `cfg.protege`, et n'a pas `lancer`. Auteur `agent-doc <agent-doc@portail.local>`.
- **Commandes en contrôle** (`securite`, `lint`) : lancées avec `tout_lecture_seule=True`, c'est-à-dire tout `/travail` monté en lecture seule par le lanceur. Un outil qui écrit un cache doit le tolérer (à noter dans l'exemple de config).
- **Arbitre** : au plus un appel en cours par modèle. L'interactif (chat d'étape, conversations, avis, résumé) passe avant le fond (`dev`). Après **3** passages interactifs consécutifs pendant qu'un appel de fond attend, c'est au tour du fond.
- **Résumé du matin** : `PORTAIL_RESUME_HEURE` vaut `"07:00"` par défaut, dans le fuseau `America/Toronto`. Au plus un par jour. Si le serveur était arrêté à l'heure prévue, le résumé part au démarrage s'il n'a pas déjà été fait ce jour-là. Pas d'envoi sans activité depuis le dernier résumé. Le texte envoyé par ntfy est coupé à 4000 caractères.
- Les outils du PM sont en **lecture seule** sur la base : aucune requête `INSERT`, `UPDATE` ou `DELETE`.

## Points à surveiller en revue

1. **Un avis encore en cours quand Nicolas valide** : il est abandonné et n'est jamais rattaché au document validé. *Test : tâche 6.*
2. **Une négation dans le message d'un agent** (« les tests ne passent pas encore ») : ce n'est pas une affirmation à prouver, et rien n'est renvoyé à tort. *Test : tâche 5.*
3. **Une ligne d'import supprimée dans le diff** : on ne vérifie que les lignes **ajoutées**, jamais celles qui sont retirées. *Test : tâche 5.*
4. **Le serveur arrêté à 7 h** : le résumé part une seule fois au démarrage, jamais deux fois le même jour. *Test : tâche 8.*
5. **Un appel de fond qui attend pendant que les chats s'enchaînent** : il passe au plus tard après 3 appels interactifs. *Test : tâche 2.*
6. **Une exécution arrêtée en pleine phase `controles`** : elle reprend au contrôle `controle_courant`, sans rejouer les précédents ni perdre un renvoi. *Test : tâche 4.*

---

### Task 1: catalogue de D

**Fichiers :**
- Modifier : `backend/portail/agents.py`, `agents.yaml`, `backend/tests/test_agents.py`

**Interfaces :**
- `OUTILS_SUIVI = ("en_attente_de_nicolas", "activite")` (créer), ajoutés à `OUTILS_LECTURE_PORTAIL` (donc à `OUTILS_PORTAIL`) et au `Literal` de `Agent.outils`.
- `Agent` gagne :
  - `modele_si_meme: str | None = None` ;
  - `consigne_avis: str | None = None` ;
  - `role` accepte aussi `"doc"`.
- `Agent._coherent` change :
  - `modele_si_meme == modele` est refusé ;
  - `produit == "travail"` exige un `role`, et `lancer` sauf pour `role: doc` ; un agent `role: doc` ne peut pas avoir `lancer` ;
  - `produit == "verdict"` : toujours `role: revue` sans `ecrire` ni `supprimer`, mais `lancer` est désormais permis (`OutilsEspace` ne l'offre que pour `securite`, tâche 3).
- `Catalogue` gagne `avis: dict[Literal["spec", "plan"], list[str]] = {}` ; `charger_catalogue` le lit dans `brut.get("avis") or {}`.
- Nouvelles validations dans `charger_catalogue`, chacune avec un message qui nomme l'agent :
  - chaque agent nommé dans `avis` existe et a une `consigne_avis` ;
  - un agent `pm`, s'il existe, n'a aucun outil de `OUTILS_ACTIONS_PORTAIL`.
- `agents.yaml` :
  - `revue` : son prompt mentionne `notes` dans le JSON attendu ;
  - `architecte` : outils `lister`, `lire`, `chercher`, une `consigne_avis` ;
  - `challenger` : `produit: verdict`, `role: revue`, `modele: qwen3.8:27b-mlx`, `modele_si_meme: mlx-community/GLM-4.7-Flash-8bit`, outils `lister`, `lire`, `chercher`, avec une `consigne_avis` ;
  - `securite` : `produit: verdict`, `role: revue`, outils `lister`, `lire`, `chercher`, `lancer` ;
  - `doc` : `produit: travail`, `role: doc`, outils `lister`, `lire`, `chercher`, `ecrire`, `supprimer` ;
  - `pm` : outils `lister_projets`, `lire_projet`, `lister_pipelines`, `lire_pipeline`, `lire_kanban`, `en_attente_de_nicolas`, `activite`, `tours_max: 10`. Son prompt lui interdit d'affirmer ce que les outils n'ont pas renvoyé et demande de citer les dates ;
  - `pipelines.dev: [tests, code, revue, challenger, securite, doc]` et `avis: {spec: [challenger], plan: [architecte, challenger]}`. Pas de `pipelines.pm`.
- Tant que la tâche 4 n'est pas faite, `dev.py` n'exécute que `tests`, `code` et `revue` : les nouveaux agents de `pipelines.dev` sont ignorés.

- [ ] **Étape 1 : tests** (`backend/tests/test_agents.py`)
  - `test_modele_si_meme_identique_refuse` ;
  - `test_avis_agent_sans_consigne_refuse` ;
  - `test_avis_agent_inconnu_refuse` ;
  - `test_doc_avec_lancer_refuse` et `test_doc_sans_lancer_accepte` ;
  - `test_verdict_avec_lancer_accepte` (remplace la boucle `lancer` de `test_verdict_exige_revue_sans_ecriture`, qui garde `ecrire` et `supprimer`) ;
  - `test_pm_avec_outil_d_action_refuse` ;
  - `test_agents_yaml_du_depot_est_valide` mis à jour : l'ordre de `dev`, `avis`, et `pm` sans outil d'action ;
  - `test_agents_yaml_du_depot_a_l_orchestrateur` : `set(a.outils) == set(OUTILS_PORTAIL) - set(OUTILS_SUIVI)`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (toute la suite backend).
- [ ] **Étape 5 : commit** `feat(portail): agents transversaux dans le catalogue`.

### Task 2: arbitre des modèles

**Fichiers :**
- Créer : `backend/portail/arbitre.py`, `backend/tests/test_arbitre.py`
- Modifier : `backend/portail/api.py` (lifespan et `_orchestrateur`)

**Interfaces :**
- `class Arbitre`, avec `def tour(self, modele: str, priorite: Literal["interactif", "fond"]) -> AbstractAsyncContextManager[None]`. Pour chaque modèle, on garde : l'occupation, une `deque` d'`asyncio.Future` par priorité, et un compteur de passages interactifs consécutifs pendant qu'un fond attend. À la libération :
  - le fond passe si le compteur vaut 3 ;
  - sinon, l'interactif passe s'il attend ;
  - sinon, le fond passe.

  Sans thread. Une tâche annulée pendant son attente retire sa `Future` ; annulée pendant son tour, elle libère.
- `class LLMArbitre(llm, arbitre: Arbitre, priorite)` expose la **même interface** que `ClientLLM` : `flux(modele, messages, temperature)` (générateur asynchrone ; le tour dure tout le flux) et `completer(modele, messages, temperature, outils=None, response_format=None)`.
- Lifespan de `create_app` : un `Arbitre`, puis `interactif = LLMArbitre(app.state.llm, arbitre, "interactif")` passé à `ServiceChat` et `ServiceConversation`, et `fond = LLMArbitre(..., "fond")` passé à `_orchestrateur(r, sessions, catalogue, fond)`. Un `orchestrateur` injecté (tests) n'est pas enveloppé. `app.state.llm` reste le client brut (les tests y injectent `FauxLLM`).

- [ ] **Étape 1 : tests** (`backend/tests/test_arbitre.py`, pytest async, avec des `asyncio.Event` pour ordonner) :
  - `test_un_appel_a_la_fois_par_modele` ;
  - `test_modeles_differents_en_parallele` ;
  - `test_interactif_passe_devant` : pendant que A (fond) tient le modèle, B (fond) puis C (interactif) attendent. À la libération, c'est C qui passe ;
  - `test_pas_de_famine` (point de revue n° 5) : un fond attend pendant que 5 interactifs arrivent. Le fond passe en 4e position ;
  - `test_annulation_libere_le_tour` : une tâche annulée pendant son attente ou pendant son tour ne bloque pas le modèle ;
  - `test_llm_arbitre_flux_tient_le_tour` : avec `FauxLLM` dont `morceaux` contient un `Event`, un `completer` du même modèle attend la fin du flux.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (toute la suite backend ; `test_chat.py`, `test_conversations.py` et `test_dev.py` inchangés).
- [ ] **Étape 5 : commit** `feat(portail): arbitre des modèles avec priorité à l'interactif`.

### Task 3: rôle `doc` et commandes de contrôle en lecture seule

**Fichiers :**
- Modifier : `lanceur/src/conteneurs.rs`, `lanceur/tests/docker.rs`, `backend/portail/lanceur.py`, `backend/portail/execution.py`, `backend/portail/outils.py`, `backend/portail/protections.py`, `backend/tests/conftest.py` (`FauxLanceur`), `backend/tests/test_lanceur.py`, `backend/tests/test_execution.py`, `backend/tests/test_outils_espace.py`, `backend/tests/test_protections.py`

**Interfaces :**
- **Lanceur (Rust)** :
  - `DemandeLancer` gagne `#[serde(default)] pub tout_lecture_seule: bool` ;
  - `specification(cfg, espace, image, commande, lecture_seule, tout_lecture_seule: bool, reseau_services, services)` : avec `true`, le montage `/travail` est `read_only: Some(true)` (les autres montages sont inchangés) ; `Docker::lancer` passe `d.tout_lecture_seule`. Mettre à jour les appels de `specification` dans les tests de `conteneurs.rs` et le littéral `DemandeLancer` de `Banc::lancer` (`docker.rs`).
- **Portail** :
  - `ClientLanceur.lancer(espace, image, commande, delai_s, lecture_seule, tout_lecture_seule: bool = False)` : le champ `tout_lecture_seule` n'est ajouté au corps que s'il est vrai (les corps attendus par `test_lanceur.py` restent identiques). `FauxLanceur.lancer` accepte et enregistre le même paramètre ;
  - `ConfigExecution` gagne `chemins_doc: list[str] = ["README.md", "docs/**", "CHANGELOG.md"]` et `regles: str | None = None` (chemin relatif d'un fichier de règles du dépôt). `commandes` accepte déjà `lint` et `securite` (noms libres) ;
  - `OutilsEspace(racine, role: Literal["tests", "code", "revue", "doc"], cfg, lancer)` :
    - `revue` : lecture, plus `lancer` avec `enum: ["securite"]` si `securite` est déclarée (`boucle_outils` ne l'offre qu'aux agents qui listent `lancer`) ;
    - `doc` : lecture, `ecrire` et `supprimer`, sans `lancer` ; dans `_cible`, permis seulement si `correspond(rel, cfg.chemins_doc)` et pas `correspond(rel, cfg.protege)` ;
  - `protections.py` : `COURRIEL_DOC = "agent-doc@portail.local"` ; `verifier_commits_code(espace, depuis, cfg)` vérifie **en plus** que chaque commit `COURRIEL_DOC` ne touche que `chemins_doc` hors `cfg.protege`, sinon la violation `"<fichier> (hors des chemins de doc)"`.

- [ ] **Étape 1 : tests**
  - Rust (`conteneurs.rs`) : `travail_en_lecture_seule` (`/travail` en `read_only: Some(true)`, `.git` toujours en lecture seule) et `travail_modifiable_par_defaut` ; `docker.rs` (`#[ignore]`) : `tout_lecture_seule_ecriture_echoue` (`touch x` échoue, `cat` d'un fichier existant réussit) ;
  - Python : `test_client_lanceur_tout_lecture_seule` (`test_lanceur.py`) ; `test_config_chemins_doc_defaut` (`test_execution.py`) ; `test_role_doc_ecrit_seulement_la_doc` (`README.md` et `docs/a.md` permis, `src/a.py` et `tests/test_x.py` refusés) et `test_revue_lancer_seulement_securite` (`test_outils_espace.py`) ; `test_commit_doc_hors_chemins_viole` et `test_commit_doc_dans_docs_permis` (`test_protections.py`).
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test`, `cargo test -- --ignored` et la suite backend donnent PASS.
- [ ] **Étape 5 : commit** `feat(lanceur,portail): rôle doc et commandes de contrôle en lecture seule`.

### Task 4: suite de contrôles dans le pipeline `dev`

**Fichiers :**
- Créer : `backend/migrations/versions/0007_agents_transversaux.py` (complétée par les tâches 6 à 8)
- Modifier : `backend/portail/agents.py` (`modele_pour`), `backend/portail/dev.py`, `backend/portail/db.py`, `backend/portail/schemas.py` (`ExecutionVue.notes`), `backend/tests/test_dev.py`, `backend/tests/test_agents.py`

**Interfaces :**
- `db.py`, `ExecutionDev` gagne `controle_courant: int` (défaut 0), `notes: list` (JSON, défaut `[]`, éléments `{agent, texte}`), `lint_base_ok: bool | None` (utilisé tâche 5) et `fichiers_rouge: list` (JSON, défaut `[]`). Le commentaire des phases devient `preparation | tests | rouge | code | verification | controles | pr | fini`.
- `0007` : ces quatre colonnes, puis `UPDATE execution_dev SET phase = 'controles' WHERE phase = 'revue'` (et l'inverse au `downgrade`).
- `agents.py` : `def modele_pour(agent: Agent, auteur: Agent) -> str` : `agent.modele_si_meme` si `agent.modele == auteur.modele` et `modele_si_meme` est défini, sinon `agent.modele`.
- `dev.py` :
  - `Verdict` gagne `notes: list[str] = []` (`FORMAT_VERDICT` suit) ; `AUTEUR_DOC = ("agent-doc", COURRIEL_DOC)` ;
  - `Orchestrateur._agent(ctx, nom, annexes, consigne, outils, modele: str | None = None)` : avec `modele`, la boucle reçoit `agent.model_copy(update={"modele": modele})` ;
  - `_commande(ctx, nom, fichiers=(), tout_lecture_seule=False)` transmet le drapeau au lanceur ;
  - `_verification` passe à `controles` avec `controle_courant=0` (au lieu de `revue`) ;
  - `_revue` devient `_controles(ctx)`. `controles = agents de pipelines["dev"] après "code"`. À partir de `controle_courant` :
    - agent `produit: verdict` : boucle avec `OutilsEspace(ctx.racine, "revue", cfg, lancer)` où `lancer` appelle `_commande(..., tout_lecture_seule=True)`. Annexes : la tâche, le diff `ctx.espace.diff(ctx.ex.base_sha)`, et pour `challenger` les faits (tâche 5) et les règles. Modèle : `modele_pour(agent, agents["code"])`. Verdict lu par `_lire_verdict`, une relance avec `response_format=FORMAT_VERDICT` (sur le même modèle), puis, encore illisible, une **note** « verdict illisible de <agent> » sans blocage (remplace `ILLISIBLE` en remarque). Les `notes` s'ajoutent à `ex.notes` ;
    - décision de renvoi et `renvois < renvois_max` : `_transition(ctx, "tests" | "code", renvois=+1, remarques=..., controle_courant=0, notes=...)` ; ensuite `verification` ramène à `controles` depuis l'index 0. Sinon, les remarques s'ajoutent aux remarques non résolues (`ex.remarques`) et on passe au contrôle suivant ;
    - agent `role: doc` : boucle avec `OutilsEspace(ctx.racine, "doc", cfg, ...)`, la tâche et le diff ; puis `ctx.espace.restaurer(lambda c: correspond(c, cfg.chemins_doc) and not correspond(c, cfg.protege))` ; `commiter(*AUTEUR_DOC, f"docs: {titre}")` (vide : rien). Jamais de renvoi ;
    - après chaque contrôle : `_maj(ctx, controle_courant=i + 1, notes=..., remarques=...)`, pour qu'une reprise après arrêt reparte au bon contrôle ;
    - après le dernier : `_transition(ctx, "pr")`.
  - `_derouler` : table de phases avec `"controles": self._controles` (plus de `"revue"`), et la liste des phases qui réinstallent à la relance contient `controles` au lieu de `revue`.
  - `_tests` après un renvoi : `fichiers_rouge` = les fichiers de tests changés dans cette passe (`espace.changements()` filtré par `chemins_tests`), puis `rouge` s'il y en a, sinon `code`. `_rouge` lance `tests_cibles` sur `fichiers_rouge or fichiers_tests` ; `_transition` vers `code` remet `fichiers_rouge=[]`.
  - `_pr` : `_corps` gagne une section « ## Notes des contrôles » (par agent) ; « ## Remarques non résolues » existe déjà. `_pousser_si_commits` compte aussi `AUTEUR_DOC`.
- `schemas.py` : `ExecutionVue.notes: list[dict] = []`.
- **Reprise (C2)** : rien dans D. La tâche 6 de C2 (« travail des agents »), quand elle sera faite, passera par `controles` au lieu de `revue` et pourra ajouter la catégorie `doc` au tri.

- [ ] **Étape 1 : tests** (`test_dev.py`, avec `Monde`, `FauxLLM`, `FauxLanceur`, et un `CATALOGUE_D` qui ajoute `challenger`, `securite` et `doc` à `CATALOGUE`) :
  - `test_tous_les_controles_tournent_dans_l_ordre` : les étapes créées après `verification` sont, dans l'ordre, `revue`, `challenger`, `securite`, `doc`, puis `pr` ;
  - `test_renvoi_du_challenger_reprend_tout` : le challenger renvoie au code. On obtient ensuite `code`, `verification`, `revue`, `challenger`, `securite`, `doc`, et `renvois == 1` ;
  - `test_compteur_partage` : la revue renvoie une fois et la sécurité une fois, puis le challenger renvoie encore. Ce dernier renvoi devient une remarque non résolue, et `securite` et `doc` tournent quand même ;
  - `test_modele_du_challenger` : avec `code` sur le modèle X et un challenger dont `modele` vaut X, l'appel (`FauxLLM.appels`) utilise `modele_si_meme` ;
  - `test_securite_lance_en_lecture_seule` : `FauxLanceur.appels` montre `tout_lecture_seule=True` pour `securite` ;
  - `test_doc_commit_seulement_si_changement` et `test_doc_hors_chemins_restaure` ;
  - `test_verdict_illisible_devient_note` (remplace `test_revue_illisible_ouvre_avec_remarque`) ;
  - `test_relance_en_controles_reprend_au_bon_index` (point de revue n° 6) ;
  - `test_renvoi_aux_tests_rouge_sur_les_seuls_fichiers_du_renvoi` (remplace `test_revue_renvoie_aux_tests_saute_le_rouge`) ;
  - `test_modele_pour` (`test_agents.py`) ;
  - les autres tests C1 et `test_reprise.py` passent sans changement de fond.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (toute la suite backend) ; `alembic upgrade head`, `check`, `downgrade base`.
- [ ] **Étape 5 : commit** `feat(portail): suite de contrôles avec compteur de renvois partagé`.

### Task 5: faits vérifiés sans modèle

**Fichiers :**
- Créer : `backend/portail/faits.py`, `backend/tests/test_faits.py`
- Modifier : `backend/portail/dev.py` (lint sur la base, installation en vérification, faits avant le challenger), `backend/tests/test_dev.py`

**Interfaces :**
- `class Fait(BaseModel)` : `type: Literal["reference", "affirmation", "lint", "installation"]`, `role: Literal["tests", "code"]`, `bloquant: bool`, `texte: str`.
- `def references_ajoutees(diff: str) -> list[tuple[str, str, str]]` renvoie des triplets `(fichier, langage, cible)`, **en ne lisant que les lignes `+`** (pas `+++`), le fichier venant de l'en-tête `+++ b/<chemin>` :
  - en Python : `^\+\s*(?:from\s+(\.*[\w.]+)\s+import|import\s+([\w.]+))` ;
  - en TS, JS et Vue : `^\+.*\bfrom\s+['"](\.{1,2}/[^'"]+)['"]`, seulement pour les imports relatifs.
- `def verifier_references(racine: Path, refs, cfg: ConfigExecution) -> list[Fait]`, deux règles :
  - **Python** : si le premier segment du module correspond à un dossier ou à un fichier `.py` de la racine de l'espace (ou de `backend/` et `src/`), le module **local** doit exister (`<chemin>.py` ou `<chemin>/__init__.py`), sinon un fait bloquant « import <m> introuvable ». Un module tiers n'est pas vérifié ici (l'installation le fait) ;
  - **TS** : le chemin relatif, résolu depuis le fichier, doit exister avec l'une de ces extensions : `""`, `.ts`, `.tsx`, `.js`, `.vue`, `/index.ts`.

  Le `role` d'un fait est `tests` si le fichier correspond à `cfg.chemins_tests`, sinon `code`.
- `AFFIRMATIONS` associe un motif à des noms de commandes. Motifs insensibles à la casse, cherchés dans le dernier message `assistant` de l'étape de l'agent :
  - `tests? (?:passent|réussissent|sont verts)|all tests pass|tests pass` → `{tests, tests_cibles}` ;
  - `lint (?:ok|passe)` → `{lint}` ;
  - `build (?:ok|passe|réussit)` → `{build}`.

  Une phrase qui contient `ne … pas`, `n'… pas`, `not` ou `don't` dans les 30 caractères avant le motif est ignorée.
- `def verifier_affirmations(texte: str, commandes: list[CommandeLancee], role) -> list[Fait]` : chaque affirmation trouvée exige, parmi les `CommandeLancee` de l'étape (même `etape_id`), que **la dernière** commande de l'ensemble ait `code == 0`. Sinon, un fait bloquant « affirmation « … » sans commande qui la prouve ».
- **Lint et installation** (`dev.py`) :
  - à la phase `preparation` (mode normal), si `lint` est déclaré : `_commande(ctx, "lint", tout_lecture_seule=True)` et `lint_base_ok = code == 0` ;
  - à la phase `verification`, un échec d'`installer` (après `remettre_a_zero`) devient un fait bloquant `installation`, rôle `code` : « installation des dépendances échouée (paquet inventé ?) », qui renvoie au code selon la règle ci-dessous ; une fois la limite atteinte, c'est le blocage actuel (`_Blocage("installation échouée …")`) ;
  - avant le challenger, si `lint` est déclaré : on le relance (`tout_lecture_seule=True`). S'il échoue, le fait est **bloquant seulement si `lint_base_ok`**, sinon c'est une note.
- `async def verifier_faits(...) -> list[Fait]` regroupe références, affirmations (dernières étapes `tests` et `code` de ce pipeline) et lint. Dans `_controles`, avant l'agent `challenger` : les faits sont écrits dans une étape `portail` d'action `faits` (un message `system`) ; les faits bloquants **renvoient d'eux-mêmes**, sans appeler le challenger, au `role` du premier fait bloquant, avec tous les faits comme remarques, et ce renvoi compte. Une fois la limite atteinte, ils deviennent des remarques non résolues. Tous les faits sont donnés au challenger en annexe.

- [ ] **Étape 1 : tests**
  - `test_faits.py` : `test_references_lignes_ajoutees_seulement` (point de revue n° 3 : une ligne `-import inexistant` n'est pas vérifiée) ; `test_import_local_inexistant_bloque` ; `test_import_tiers_ignore` ; `test_import_ts_relatif_resolu_avec_extensions` ; `test_affirmation_prouvee` ; `test_affirmation_sans_preuve_bloque` ; `test_affirmation_dont_la_derniere_commande_echoue_bloque` ; `test_negation_ignoree` (point de revue n° 2), paramétré : « les tests ne passent pas encore », « tests don't pass yet » ;
  - `test_dev.py` : `test_lint_dette_existante_note_seulement` ; `test_lint_nouveau_bloque` ; `test_installation_echouee_renvoie_au_code` ; `test_faits_bloquants_renvoient_avant_le_challenger` (le challenger n'est pas appelé à ce passage). `test_installation_echouee_en_verification_bloque` (C1) est adapté : le blocage n'arrive qu'après `renvois_max` renvois.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (toute la suite backend).
- [ ] **Étape 5 : commit** `feat(portail): faits vérifiés sans modèle avant le challenger`.

### Task 6: avis sur les brouillons de spec et de plan

**Fichiers :**
- Créer : `backend/portail/avis.py`, `backend/tests/test_avis.py`
- Modifier : `backend/portail/db.py` (`Document.version`, table `Avis`), la migration `0007`, `backend/portail/chat.py`, `backend/portail/api.py`, `backend/portail/schemas.py`

**Interfaces :**
- `Document.version: int` (défaut 1) : incrémentée dans `ServiceChat._ecrire_document` (rédaction par l'agent) et dans `ServiceChat.corriger` (`PUT` de Nicolas).
- `Avis` (table `avis`) : `id`, `document_id` (FK `document`, `CASCADE`), `version` (la version lue), `agent`, `contenu` (texte, défaut `""`), `etat` (`en_cours` | `ouvert` | `pris_en_compte` | `ecarte` | `abandonne`), `cree_le`.
- `class ServiceAvis(sessions, catalogue, llm, depots: Depots)` (`avis.py`) :
  - `lancer(document_id: int) -> None` : pour chaque agent de `catalogue.avis.get(document.type, [])`, une ligne `Avis(etat="en_cours", version=v)` est commitée, puis une tâche de fond, gardée dans `taches[(document_id, agent)]` ; une tâche déjà en cours pour cette paire est annulée et sa ligne passe `abandonne`. La tâche :
    - construit la demande avec `construire(agent, [], None, agent.consigne_avis, annexes)` (`contexte.py`), les annexes étant le brouillon (version `v`), la spec courante (`spec_courante`) pour un plan, et `etape.apercu` s'il existe ;
    - si l'agent a des outils et le projet un dépôt : `boucle_outils` sur `OutilsDepot(arbre)`, avec `arbre` de `depots.preparer(projet.id, depot_url, branche_ref, etape.id, etape.sha)` (le même arbre que l'étape) ; sinon `llm.completer` ;
    - utilise `modele_pour(agent, agent_de_l_etape)` (par `model_copy`) ;
    - remplit l'avis (`contenu`, `etat="ouvert"`) **seulement si** le document est toujours en `brouillon` et la ligne encore `en_cours` ; sinon `abandonne` ;
  - `abandonner(document_id) -> None` : annule les tâches de ce document et passe ses lignes `en_cours` à `abandonne` ;
  - `recuperer_interrompues(s)` : au démarrage, `en_cours` → `abandonne`.
- `ServiceChat(..., depots, avis: ServiceAvis | None = None)` :
  - dans `_tache`, après `_ecrire_document` et le commit (action `rediger`), `avis.lancer(doc.id)`. `corriger` ne déclenche rien ;
  - dans `valider`, `await avis.abandonner(doc.id)` avant `depots.liberer` ;
  - `annexes(s, agent, etape, projet_id)` ajoute les avis `ouvert` du document de l'étape : `"Avis ouverts à prendre en compte :\n\n- <agent> : <contenu>"`.
- Lifespan : `ServiceAvis(sessions, catalogue, interactif, depots)` passé à `ServiceChat`, `recuperer_interrompues` au démarrage, ses tâches annulées à l'arrêt.
- Routes :
  - `POST /api/documents/{id}/avis` relance les avis à la main (`409` si le document n'est pas en `brouillon`), et renvoie `202` ;
  - `PATCH /api/avis/{id} {etat: "pris_en_compte" | "ecarte" | "ouvert"}` ;
  - `DocumentOut` gagne `version` et `avis: list[AvisOut]` (`id`, `agent`, `contenu`, `etat`, `version`, `ancienne: bool` = `version < document.version`), chargés dans `_detail` ; les `abandonne` ne sont pas renvoyés.

- [ ] **Étape 1 : tests** (`test_avis.py`, avec `client`, `FauxLLM` et un catalogue de test qui a `architecte`, `challenger` et `avis`)
  - `test_redaction_declenche_les_avis_du_plan` : `architecte` et `challenger` donnent deux avis `ouvert`, avec `version == 1` ;
  - `test_put_de_nicolas_ne_declenche_rien` ;
  - `test_avis_marque_ancien_apres_correction` ;
  - `test_avis_ouverts_donnes_a_la_redaction_suivante` ;
  - `test_valider_abandonne_les_avis_en_cours` (point de revue n° 1) : avec `FauxLLM.reponses` bloqué par un `Event`, après `valider`, aucun avis `ouvert` n'est enregistré, même une fois le modèle libéré ;
  - `test_challenger_change_de_modele_si_meme_que_le_redacteur` ;
  - `test_demande_manuelle` ;
  - `test_avis_ne_bloque_pas_la_validation` ;
  - `test_redemarrage_abandonne_les_avis_en_cours`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (toute la suite backend) ; `alembic upgrade head`, `check`, `downgrade base`.
- [ ] **Étape 5 : commit** `feat(portail): avis de l'architecte et du challenger sur les brouillons`.

### Task 7: le PM

**Fichiers :**
- Modifier : `backend/portail/db.py` (`Conversation.agent`), la migration `0007`, `backend/portail/outils_portail.py`, `backend/portail/conversations.py`, `backend/portail/schemas.py`, `backend/portail/api.py`, `backend/tests/test_outils_portail.py`, `backend/tests/test_conversations.py`

**Interfaces :**
- `Conversation.agent: str` (défaut et `server_default` `"orchestrateur"`).
- `outils_portail.py` :
  - `SCHEMAS_PORTAIL` et `_ARGS` gagnent `en_attente_de_nicolas` (`_Vide`) et `activite` (`_Activite`, `depuis: datetime`, ISO) ;
  - `async def activite_depuis(s, depuis: datetime, limite: int = 200) -> list[str]` (créer) : les `TacheEvenement` et les pipelines dont `maj_le >= depuis`, du plus récent au plus ancien, chaque ligne datée en ISO ;
  - `_en_attente_de_nicolas` : les étapes `en_attente`, les propositions `ouverte`, les tâches `en_revue` (avec le `pr_url` de leur dernière `ExecutionDev`) et les tâches `bloquee` (avec leur `resume_blocage` tronqué), datées ;
  - `_activite` appelle `activite_depuis` ;
  - `_lister_pipelines` et `_lire_pipeline` ajoutent `maj_le` en ISO (faits datés de la spec ; adapter les assertions de `test_outils_portail.py`).
- `conversations.py` :
  - `AGENTS = ("orchestrateur", "pm")` remplace `AGENT` ;
  - `creer(agent: str = "orchestrateur")` : `Refus(422)` hors de `AGENTS`, `Refus(409)` si l'agent manque au catalogue ;
  - `_agent(c: Conversation)` lit `c.agent` ; `detail`, `envoyer`, `reessayer` et `_tache` l'utilisent ;
  - `OutilsPortail(self._sessions, agent.outils, self._catalogue, cid)` est inchangé : sans outil d'action dans `agent.outils`, le PM ne peut rien proposer.
- `schemas.py` : `ConversationResume` et `ConversationDetail` gagnent `agent: str` ; `ConversationIn(agent: str = "orchestrateur")` (créer).
- `api.py` : `POST /api/conversations` accepte un corps facultatif `ConversationIn`.

- [ ] **Étape 1 : tests**
  - `test_outils_portail.py` : `test_outils_pm_lecture_seule` (chaque outil de `OUTILS_LECTURE_PORTAIL` appelé sous un écouteur SQLAlchemy `before_cursor_execute` qui échoue sur tout `INSERT`, `UPDATE` ou `DELETE`) ; `test_en_attente_de_nicolas` (une étape en attente, une proposition ouverte, une tâche en revue et une tâche bloquée : les quatre apparaissent) ; `test_activite_depuis` ;
  - `test_conversations.py` : `test_conversation_pm` (création avec `{"agent": "pm"}` ; le faux modèle appelle `en_attente_de_nicolas`, puis répond ; le message `tool` est enregistré ; `agent == "pm"` au détail et à la liste) ; `test_pm_ne_peut_rien_proposer` (un appel `creer_tache` du modèle est refusé, aucune `ActionConversation`) ; `test_agent_inconnu_422` ; `test_conversation_par_defaut_orchestrateur`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (toute la suite backend) ; `alembic upgrade head`, `check`, `downgrade base`.
- [ ] **Étape 5 : commit** `feat(portail): le PM, une conversation en lecture seule sur l'état du portail`.

### Task 8: résumé du matin

**Fichiers :**
- Créer : `backend/portail/resume.py`, `backend/tests/test_resume.py`
- Modifier : `backend/portail/api.py` (lifespan), `backend/portail/config.py` (`resume_heure: str = "07:00"`), `backend/portail/db.py` et la migration `0007` (table `resume` : `id`, `jour` (date, unique), `conversation_id` (FK `conversation`, `SET NULL`, nullable), `cree_le`)

**Interfaces :**
- `def prochaine_echeance(maintenant: datetime, heure: str) -> datetime`, en `America/Toronto` (`zoneinfo`) : aujourd'hui à `heure` si elle n'est pas encore passée, sinon demain.
- `async def resumer_si_du(sessions, conversations: ServiceConversation, notifieur, maintenant: datetime, heure: str, url_publique: str) -> bool`. Si **aujourd'hui** (date de Toronto) n'a pas de `Resume`, que `maintenant >= aujourd'hui à heure`, et que `activite_depuis(s, depuis, 1)` n'est pas vide (`depuis` = `cree_le` du dernier `Resume`, ou 24 h avant) :
  - `conversations.creer("pm")`, renommée « Résumé du <jour> » (`renommer`) ;
  - `conversations.envoyer(cid, CONSIGNE)` avec la consigne fixe « Ce qui s'est passé depuis le dernier résumé, ce qui est bloqué, ce qui attend Nicolas. Court, en puces. », puis `await conversations.taches[cid]` ;
  - on enregistre `Resume(jour, conversation_id)` **avant** l'envoi ;
  - `notifieur.envoyer("Résumé du matin", texte[:4000], lien_absolu(url_publique, f"/chat/{cid}"))`, `texte` étant le dernier message `assistant` (rien n'est envoyé si la conversation finit en `erreur`).

  Renvoie `True` si un résumé a été envoyé. Sans activité, on enregistre quand même `Resume(jour)`, sans conversation ni envoi, et on renvoie `False`.
- Lifespan : si l'agent `pm` est au catalogue, une tâche appelle `resumer_si_du` **une fois au démarrage**, puis dort jusqu'à `prochaine_echeance` ; elle utilise `Notifieur(r.ntfy_url, r.ntfy_sujet, r.ntfy_jeton)` (sans jeton, `envoyer` ne fait rien) et est annulée à l'arrêt. Une erreur est journalisée et la boucle continue.

- [ ] **Étape 1 : tests** (`test_resume.py`, avec une horloge injectée, `FauxLLM` et `FauxNotifieur`) :
  - `test_prochaine_echeance`, paramétré : 06:59 donne aujourd'hui à 07:00, 07:01 donne demain à 07:00, et le passage à l'heure d'été (8 mars 2026) donne 07:00 heure locale ;
  - `test_pas_d_envoi_sans_activite` ;
  - `test_envoi_avec_activite_et_une_seule_fois_par_jour` (point de revue n° 4) : un démarrage à 09:00 envoie, et un deuxième appel le même jour n'envoie rien ; la conversation d'agent `pm` existe ;
  - `test_avant_l_heure_rien` ;
  - `test_texte_coupe_a_4000`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (toute la suite backend). La migration `0007` monte et descend (`alembic upgrade head`, `check`, `downgrade base`).
- [ ] **Étape 5 : commit** `feat(portail): résumé du matin par ntfy`.

### Task 9: interface de D

**Fichiers :**
- Créer : `frontend/src/components/PanneauAvis.vue`, `frontend/src/avis.ts`, `frontend/src/avis.test.ts`
- Modifier : `frontend/src/api.ts`, `frontend/src/views/PipelineView.vue`, `frontend/src/views/ChatView.vue`, `frontend/src/components/ConfigExecution.vue`

**Interfaces :**
- `api.ts` : `Avis` (`id`, `agent`, `contenu`, `etat`, `version`, `ancienne`) ; `Document` gagne `version` et `avis` ; `demanderAvis(documentId)` (`POST /documents/{id}/avis`) ; `changerEtatAvis(id, etat)` (`PATCH /avis/{id}`) ; le type `execution` de `PipelineDetail` gagne `notes: { agent: string; texte: string }[]` ; `ConversationResume` et `ConversationDetail` gagnent `agent` ; `creerConversation(agent = 'orchestrateur')`.
- `avis.ts` : fonction pure `trierAvis(avis: Avis[]): Avis[]` : les `en_cours` puis les `ouvert` d'abord, les plus récents (`id` décroissant) en tête dans chaque groupe.
- `PanneauAvis` (props : le `Document`), placé sous `EditeurDocument` dans `PipelineView` pour une étape de produit `spec` ou `plan` :
  - une carte par avis (`trierAvis`), avec l'agent, le contenu rendu par `rendreMarkdown`, et un badge « sur une version antérieure » si `ancienne` ;
  - les boutons « Pris en compte », « Écarté » et « Rouvrir » ;
  - « Avis en cours : … » tant qu'un avis est `en_cours` ;
  - le bouton « Demander un avis », tant que le document est en `brouillon`.
- `ChatView` : un second bouton « + PM » à côté de « + Nouvelle » (`creerConversation('pm')`) et un badge « PM » dans la liste et le titre pour `agent === 'pm'`. Les résumés du matin y apparaissent comme les autres conversations. L'accès « partout » est le lien « Chat » de l'en-tête de `App.vue`, déjà présent.
- `PipelineView`, pour un pipeline `dev` : sous la carte de l'exécution, les notes regroupées par agent. Les contrôles, les faits (étape `portail`, action `faits`) et les verdicts sont déjà des étapes affichées.
- `ConfigExecution` : l'exemple commenté `EXEMPLE` inclut `chemins_doc`, `regles` et les commandes `lint` et `securite`, avec la mention qu'elles tournent sur un espace en lecture seule.

- [ ] **Étape 1 : test** `avis.test.ts` de `trierAvis`. **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** `npm run typecheck`, `npm test` et `npm run build` donnent PASS.
- [ ] **Étape 5 : vérification manuelle**, si LiteLLM est joignable :
  1. rédiger un plan : deux avis apparaissent, et un badge « sur une version antérieure » après une correction ;
  2. ouvrir une conversation PM et demander « qu'est-ce qui m'attend ? » ;
  3. une tâche `dev` montre les étapes de contrôle et leurs notes.

  Sinon, le noter comme non vérifié.
- [ ] **Étape 6 : commit** `feat(portail): interface des avis, du PM et des notes de contrôle`.

*Aucune tâche dans le dépôt Infra :* le sujet ntfy et le lanceur sont déjà en place depuis C.
