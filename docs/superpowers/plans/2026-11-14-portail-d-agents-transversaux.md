# Portail — D : agents transversaux : plan d'implémentation

> **Pour les agents qui exécutent :** SOUS-SKILL REQUIS : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans, tâche par tâche. Les étapes utilisent des cases `- [ ]`.

**But :** ajouter les agents de contrôle et de suivi.
- Dans le pipeline `dev` : un **challenger** qui s'appuie sur des faits vérifiés par du code, la **sécurité** et la **documentation**.
- Sur les brouillons de spec et de plan : les **avis** de l'**architecte** et du challenger.
- Un **PM** en chat, avec un résumé du matin envoyé par ntfy.
- Un **arbitre** qui partage les modèles locaux en donnant la priorité à l'interactif.

**Architecture :** on étend ce qui existe, sans nouveau service.
- L'orchestrateur de C généralise sa phase `revue` en une **suite d'étapes de contrôle**, lue dans `pipelines.dev`, avec un compteur de renvois partagé.
- Un module `faits` fait les vérifications sans modèle.
- Les avis sont des lignes en base, produites en tâche de fond.
- Le PM est un pipeline de type `pm`, sans projet, avec des outils de lecture sur la base du portail.
- Le lanceur gagne deux règles de rôle : `doc` et `revue` en lecture seule.

**Pile :** celle de A, B et C. Aucune nouvelle dépendance (`zoneinfo` vient de la bibliothèque standard).

**Spec :** `docs/superpowers/specs/2026-11-14-portail-d-agents-transversaux-design.md`. Ce plan s'appuie sur les plans de A, B et C (`docs/superpowers/plans/2026-11-14-portail-{socle,b-plan-taches,c-boucle-dev}.md`), dont il reprend les interfaces. **On suppose que A, B et C sont construits et fusionnés.**

## Contraintes globales

- Toutes les contraintes de A, B et C s'appliquent toujours.
- **Verdict de contrôle**, commun à tous les agents de contrôle : `{"decision": "ok" | "renvoyer_tests" | "renvoyer_code", "remarques": [str], "notes": [str]}`. Les `remarques` accompagnent un renvoi. Les `notes` ne bloquent jamais.
- **Un seul compteur de renvois** par exécution `dev` : `renvois_max` vaut 2 (`PORTAIL_RENVOIS_MAX`). Il est remis à 0 à chaque reprise sur commentaires. Une fois la limite atteinte, les contrôles restants **tournent quand même**. Une décision de renvoi est alors convertie en « remarque non résolue » dans la PR.
- **Ordre du pipeline `dev`** dans `agents.yaml` : `pipelines.dev: [tests, code, revue, challenger, securite, doc]`. Les contrôles sont les agents qui suivent `code`. En retirer un de la liste le désactive.
- **Challenger** : son modèle est `modele_si_meme` quand `modele` est égal à celui de l'**auteur principal** (l'agent `code` dans `dev`, l'agent qui rédige pour un avis). `modele` et `modele_si_meme` doivent être différents, sinon le démarrage échoue.
- **Rôle `doc`** : il écrit **seulement** dans `chemins_doc` (par défaut `["README.md", "docs/**", "CHANGELOG.md"]`). Auteur `agent-doc <agent-doc@portail.local>`.
- **Rôle `revue`** pour `lancer` : l'espace est monté **entièrement en lecture seule**.
- **Arbitre** : au plus un appel en cours par modèle. L'interactif (chat, avis, PM) passe avant le fond (`dev`, résumé). Après **3** passages interactifs consécutifs pendant qu'un appel de fond attend, c'est au tour du fond.
- **Résumé du matin** : `PORTAIL_RESUME_HEURE` vaut `"07:00"` par défaut, dans le fuseau `America/Toronto`. Au plus un par jour. Si le serveur était arrêté à l'heure prévue, le résumé est envoyé au démarrage, s'il n'a pas déjà été envoyé ce jour-là. Pas d'envoi sans activité depuis le dernier résumé. Le texte envoyé par ntfy est coupé à 4000 caractères.
- Les outils du PM sont en **lecture seule** sur la base : aucune requête `INSERT`, `UPDATE` ou `DELETE`.

## Points à surveiller en revue

1. **Un avis encore en cours quand Nicolas valide** : il est abandonné et n'est jamais rattaché au document validé. *Test : tâche 6.*
2. **Une négation dans le message d'un agent** (« les tests ne passent pas encore ») : ce n'est pas une affirmation à prouver, et rien n'est renvoyé à tort. *Test : tâche 5.*
3. **Une ligne d'import supprimée dans le diff** : on ne vérifie que les lignes **ajoutées**, jamais celles qui sont retirées. *Test : tâche 5.*
4. **Le serveur arrêté à 7 h** : le résumé part une seule fois au démarrage, jamais deux fois le même jour. *Test : tâche 8.*
5. **Un appel de fond qui attend pendant que les chats s'enchaînent** : il passe au plus tard après 3 appels interactifs. *Test : tâche 2.*

---

### Task 1: catalogue de D

**Fichiers :**
- Modifier : `backend/portail/agents.py`, `agents.yaml`, `backend/tests/test_agents.py`

**Interfaces :**
- **Change C** : `Agent` gagne les champs suivants :
  - `modele_si_meme: str | None = None` ;
  - `consigne_avis: str | None = None` ;
  - `produit` accepte aussi `"avis"` et `"chat"` ;
  - `role` accepte aussi `"doc"` ;
  - `outils` accepte aussi les outils du PM : `projets`, `pipelines`, `taches`, `pipeline`, `en_attente_de_nicolas` et `activite`.
- `Catalogue` gagne `avis: dict[Literal["spec", "plan"], list[str]] = {}`.
- Nouvelles validations, chacune avec un message qui nomme l'agent :
  - `modele_si_meme == modele` est refusé ;
  - chaque agent nommé dans `avis` doit exister et avoir une `consigne_avis` ;
  - un agent `role: doc` ne peut pas avoir `lancer` ;
  - les outils du PM sont réservés à un agent `produit: chat`, et un agent `chat` ne peut avoir que ceux-là.
- `agents.yaml` :
  - `architecte` : `produit: avis`, outils `lister`, `lire`, `chercher` ;
  - `challenger` : `produit: verdict`, `role: revue`, `modele: qwen3.8:27b-mlx`, `modele_si_meme: mlx-community/GLM-4.7-Flash-8bit`, outils `lister`, `lire`, `chercher`, avec une `consigne_avis` ;
  - `securite` : `produit: verdict`, `role: revue`, outils `lister`, `lire`, `chercher`, `lancer` ;
  - `doc` : `produit: travail`, `role: doc`, outils `lister`, `lire`, `chercher`, `ecrire`, `supprimer` ;
  - `pm` : `produit: chat`, avec les six outils du PM. Son prompt lui interdit d'affirmer ce que les outils n'ont pas renvoyé, et demande de citer les dates ;
  - `pipelines.dev: [tests, code, revue, challenger, securite, doc]`, `pipelines.pm: [pm]` et `avis: {spec: [challenger], plan: [architecte, challenger]}`.

- [ ] **Étape 1 : tests**
  - `test_modele_si_meme_identique_refuse` ;
  - `test_avis_agent_sans_consigne_refuse` ;
  - `test_avis_agent_inconnu_refuse` ;
  - `test_doc_avec_lancer_refuse` ;
  - `test_outils_pm_hors_chat_refuses` ;
  - `test_agents_yaml_du_depot_est_valide` (l'ordre de `dev`, `avis`, et `pm`).
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): agents transversaux dans le catalogue`.

### Task 2: arbitre des modèles

**Fichiers :**
- Créer : `backend/portail/arbitre.py`, `backend/tests/test_arbitre.py`
- Modifier : `backend/portail/api.py` (construction), `backend/portail/chat.py`, `backend/portail/dev.py`

**Interfaces :**
- `class Arbitre`, avec `def tour(self, modele: str, priorite: Literal["interactif", "fond"]) -> AbstractAsyncContextManager[None]`. Pour chaque modèle, on garde : l'occupation, les files d'attente des deux priorités, et un compteur de passages interactifs consécutifs pendant qu'un fond attend. À la libération :
  - le fond passe si le compteur vaut 3 ;
  - sinon, l'interactif passe s'il attend ;
  - sinon, le fond passe.

  On utilise des `asyncio.Future` dans des `deque`, sans thread.
- `class LLMArbitre(llm, arbitre, priorite)` expose la **même interface** que `ClientLLM` (`flux`, `completer`) et entoure chaque appel de `arbitre.tour(modele, priorite)`. Pour `flux`, le tour dure tout le flux.
- **Change A, B et C** : `ServiceChat` utilise `LLMArbitre(..., "interactif")`, et `Orchestrateur` utilise `LLMArbitre(..., "fond")`.

- [ ] **Étape 1 : tests** (pytest en async, avec des événements pour ordonner) :
  - `test_un_appel_a_la_fois_par_modele` ;
  - `test_modeles_differents_en_parallele` ;
  - `test_interactif_passe_devant` : pendant que A (fond) tient le modèle, B (fond) puis C (interactif) attendent. À la libération, c'est C qui passe ;
  - `test_pas_de_famine` (point de revue n° 5) : un fond attend pendant que 5 interactifs arrivent. Le fond passe en 4e position ;
  - `test_annulation_libere_le_tour` : une tâche annulée pendant son attente ou pendant son tour ne bloque pas le modèle.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): arbitre des modèles avec priorité à l'interactif`.

### Task 3: rôles `doc` et `revue` dans le lanceur et dans la config

**Fichiers :**
- Modifier : `lanceur/src/chemins.rs`, `lanceur/src/conteneurs.rs`, `lanceur/tests/docker.rs`, `backend/portail/execution.py`, `backend/portail/outils_espace.py`, `backend/portail/protections.py`, et les tests correspondants

**Interfaces :**
- **Change C, côté lanceur** :
  - `Role` gagne `Doc` ;
  - `Regles` gagne `chemins_doc: Vec<String>`, avec la valeur par défaut des contraintes globales si le champ est absent ;
  - `peut_ecrire(Doc, chemin, …)` est vrai **seulement** pour `chemins_doc` ;
  - dans `specification`, pour le rôle `Revue`, le montage `/travail` est `read_only: true`. Pour `Doc`, `lancer` est refusé (403).
- **Change C, côté portail** :
  - `ConfigExecution` gagne `chemins_doc: list[str]` (avec la même valeur par défaut) et `regles: str | None`, un chemin relatif vers un fichier de règles du dépôt ;
  - `commandes` peut contenir `securite` et `lint`. `OutilsEspace` accepte `role="doc"` et transmet `chemins_doc` dans `Regles` à la création de l'espace ;
  - `verifier_commits_code` devient `verifier_commits(client, espace, depuis, cfg) -> list[str]`, qui vérifie **en plus** que chaque commit `agent-doc@portail.local` ne touche que `chemins_doc`. Sinon, la violation est `"<fichier> (hors des chemins de doc)"`.

- [ ] **Étape 1 : tests**
  - Rust : `role_doc` (`README.md` et `docs/a.md` sont permis, `src/a.py` et `tests/x.py` sont refusés) ; `revue_monte_tout_en_lecture_seule` ; `doc_lancer_refuse`. Côté Docker (`#[ignore]`) : `revue_ne_peut_pas_ecrire` (`touch x` échoue) ;
  - Python : `test_config_chemins_doc_defaut` ; `test_outils_espace_role_doc` ; `test_commit_doc_hors_chemins_viole`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** `cargo test`, `cargo test -- --ignored` et pytest donnent PASS.
- [ ] **Étape 5 : commit** `feat(lanceur,portail): rôle doc et revue en lecture seule`.

### Task 4: suite de contrôles dans le pipeline `dev`

**Fichiers :**
- Modifier : `backend/portail/dev.py`, `backend/portail/db.py` (`ExecutionDev` gagne `controle_courant: int`, `notes: JSON` et `lint_base_ok: bool | None`), `backend/migrations/versions/0004_agents_transversaux.py` (créée ici et complétée par les tâches 5 à 8), `backend/tests/test_dev.py`

**Interfaces :**
- **Change C** : la phase `revue` devient la phase **`controles`**. `ExecutionDev.phase` accepte `controles` et `doc`. On garde `revue` en lecture, pour la migration de données : une exécution en phase `revue` reprend en `controles` avec l'index 0.
  - Pour chaque agent `a` de `pipelines.dev`, à partir de l'index `controle_courant`, en ignorant `tests` et `code` :
    - si `a.produit == "verdict"` : on lance la boucle avec `OutilsEspace(role="revue")`, dont le `lancer` est limité au nom `securite` s'il est déclaré. L'agent reçoit le diff `depuis=base_sha`, la tâche, et les **faits** (tâche 5) si `a` est le challenger. Les `notes` s'ajoutent à `ExecutionDev.notes`, sous la forme `{agent, texte}` ;
    - pour une décision de renvoi : si `renvois < renvois_max`, on fait `renvois += 1` et `controle_courant = 0`, puis on va à la phase `tests` ou `code` avec les remarques. La suite reprend ensuite par `verification`, puis tous les contrôles depuis l'index 0. Sinon, les remarques s'ajoutent aux « remarques non résolues » et on passe au contrôle suivant ;
    - si `a.produit == "travail"` et `a.role == "doc"`, c'est la phase **`doc`** : la boucle avec `OutilsEspace(role="doc")`, la tâche et le diff. S'il y a des changements, `commit(agent-doc)`. Cette phase ne renvoie jamais le travail.
  - Le modèle du challenger vient de `def modele_pour(agent: Agent, auteur: Agent) -> str` (dans `agents.py`).
  - Le verdict est validé par `Verdict(BaseModel)`, avec une relance en cas de JSON invalide. Une deuxième réponse invalide devient une **note** « verdict illisible de <agent> », et ne bloque pas.
  - Après le dernier contrôle, on lance `verifier_commits` (tâche 3), puis la phase `pr`. Le corps de la PR gagne les sections « Notes des contrôles » (par agent) et « Remarques non résolues ».
- **Change C** (reprise) : l'agent `tri` peut classer un commentaire en `doc`. Les commentaires `doc` passent par la phase `doc`, avec ces commentaires comme remarques, et toute la suite de contrôles revient.

- [ ] **Étape 1 : tests**, avec les faux de C :
  - `test_tous_les_controles_tournent_dans_l_ordre` : les étapes créées sont, dans l'ordre, `revue`, `challenger`, `securite`, puis `doc` ;
  - `test_renvoi_du_challenger_reprend_tout` : le challenger renvoie au code. On obtient ensuite `code`, `verification`, `revue`, `challenger`, `securite`, `doc`, et `renvois == 1` ;
  - `test_compteur_partage` : la revue renvoie une fois et la sécurité une fois, puis le challenger renvoie encore. Ce dernier renvoi devient une remarque non résolue, et `securite` et `doc` tournent quand même ;
  - `test_modele_du_challenger` : avec `code` sur le modèle X et un challenger dont `modele` vaut X, l'appel utilise `modele_si_meme` ;
  - `test_doc_commit_seulement_si_changement` ;
  - `test_verdict_illisible_devient_note` ;
  - `test_reprise_commentaire_doc_et_compteur_remis_a_zero`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): suite de contrôles avec compteur de renvois partagé`.

### Task 5: faits vérifiés sans modèle

**Fichiers :**
- Créer : `backend/portail/faits.py`, `backend/tests/test_faits.py`
- Modifier : `backend/portail/dev.py` (lint sur la base, appel avant le challenger)

**Interfaces :**
- `class Fait(BaseModel)` : `type: Literal["reference", "affirmation", "lint", "installation"]`, `role: Literal["tests", "code"]`, `bloquant: bool`, `texte: str`.
- `def references_ajoutees(diff: str) -> list[tuple[str, str, str]]` renvoie des triplets `(fichier, langage, cible)`, **en ne lisant que les lignes `+`** (pas `+++`) :
  - en Python : `^\+\s*(?:from\s+(\.*[\w.]+)\s+import|import\s+([\w.]+))` ;
  - en TS, JS et Vue : `^\+.*\bfrom\s+['"](\.{1,2}/[^'"]+)['"]`, seulement pour les imports relatifs.
- `async def verifier_references(client, espace, refs) -> list[Fait]`, avec deux règles :
  - **Python** : si le premier segment du module correspond à un dossier ou à un fichier `.py` de la racine de l'espace (ou de `backend/` et `src/`, les racines de paquets courantes), le module **local** doit exister (`<chemin>.py` ou `<chemin>/__init__.py`). Sinon, on a un fait bloquant « import <m> introuvable ». Un module tiers n'est pas vérifié ici (voir l'installation) ;
  - **TS** : le chemin relatif, résolu depuis le fichier, doit exister avec l'une de ces extensions : `""`, `.ts`, `.tsx`, `.js`, `.vue`, `/index.ts`.

  Le `role` d'un fait est celui de l'auteur du commit qui a ajouté la ligne : `tests` si le fichier est un chemin de tests, sinon `code`.
- `AFFIRMATIONS` est une table qui associe un motif à des commandes. Les motifs sont insensibles à la casse et cherchés dans le dernier message de l'agent :
  - `tests? (?:passent|réussissent|sont verts)|all tests pass|tests pass` correspond à `{tests, tests_cibles}` ;
  - `lint (?:ok|passe)` correspond à `{lint}` ;
  - `build (?:ok|passe|réussit)` correspond à `{build}`.

  Une phrase qui contient `ne … pas`, `n'… pas`, `not` ou `don't` dans les 30 caractères avant le motif est ignorée.
- `def verifier_affirmations(texte: str, commandes: list[CommandeLancee], role) -> list[Fait]` : chaque affirmation trouvée exige, parmi les commandes de l'étape, **la dernière** commande de l'ensemble avec `code == 0`. Sinon, on a un fait bloquant « affirmation « … » sans commande qui la prouve ».
- **Lint et installation** :
  - à la phase `preparation`, si `lint` est déclaré, on le lance avec le rôle `revue` et on enregistre `ExecutionDev.lint_base_ok` ;
  - avant le challenger, on relance `installer` (rôle `systeme`). S'il échoue, on a un fait bloquant de type `installation`, rôle `code` : « installation des dépendances échouée (paquet inventé ?) » ;
  - on relance aussi `lint` (rôle `revue`) : s'il échoue, le fait est **bloquant seulement si `lint_base_ok`**, sinon c'est une note.
- `async def verifier_faits(...) -> list[Fait]` regroupe tout ça. Les faits bloquants **renvoient d'eux-mêmes**, avant même d'appeler le challenger : on renvoie au `role` du premier fait bloquant, avec tous les faits comme remarques, et ce renvoi compte dans le compteur. Une fois la limite atteinte, ils deviennent des remarques non résolues. Tous les faits sont aussi donnés au challenger, en annexe.

- [ ] **Étape 1 : tests**
  - `test_references_lignes_ajoutees_seulement` (point de revue n° 3) : une ligne `-import inexistant` n'est pas vérifiée ;
  - `test_import_local_inexistant_bloque` ;
  - `test_import_tiers_ignore` ;
  - `test_import_ts_relatif_resolu_avec_extensions` ;
  - `test_affirmation_prouvee` ;
  - `test_affirmation_sans_preuve_bloque` ;
  - `test_affirmation_dont_la_derniere_commande_echoue_bloque` ;
  - `test_negation_ignoree` (point de revue n° 2), paramétré : « les tests ne passent pas encore », « tests don't pass yet » ;
  - `test_lint_dette_existante_note_seulement` ;
  - `test_lint_nouveau_bloque` ;
  - `test_installation_echouee_bloque_code` ;
  - `test_faits_bloquants_renvoient_avant_le_challenger` (dans `test_dev.py`) : le challenger n'est pas appelé à ce passage.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): faits vérifiés sans modèle avant le challenger`.

### Task 6: avis sur les brouillons de spec et de plan

**Fichiers :**
- Créer : `backend/portail/avis.py`, `backend/tests/test_avis.py`
- Modifier : `backend/portail/db.py` (`Document.version: int`, défaut 1 ; une nouvelle table `Avis`), `backend/portail/chat.py`, `backend/portail/api.py`, `backend/portail/schemas.py`, la migration `0004`

**Interfaces :**
- **Change A** : `Document.version` est incrémentée à chaque changement de contenu, que ce soit une rédaction de l'agent ou un `PUT` de Nicolas.
- `Avis` : `id`, `document_id`, `version` (la version lue), `agent`, `contenu`, `etat` (`ouvert` | `pris_en_compte` | `ecarte` | `abandonne`), `cree_le`.
- `class ServiceAvis(sessions, catalogue, llm_interactif, depots)` :
  - `lancer(document_id: int) -> None` : pour chaque agent de `catalogue.avis[document.type]`, elle lance une tâche de fond, gardée dans `en_cours[(document_id, agent)]`. Une tâche déjà en cours pour cette paire est annulée et remplacée. La tâche :
    - construit le contexte : `prompt_systeme`, plus les annexes, c'est-à-dire le brouillon (version `v`), la spec courante (pour un plan), et l'aperçu ou les outils du dépôt (comme en B, sur le SHA de l'étape) si l'agent a des outils et le projet un dépôt ;
    - termine par `consigne_avis` ;
    - utilise `modele_pour(agent, agent_redacteur)` ;
    - enregistre l'`Avis(version=v, etat="ouvert")`, **seulement si** le document est toujours en `brouillon` ;
  - `abandonner(document_id) -> None` : elle annule les tâches en cours pour ce document ;
  - `en_cours_pour(document_id) -> list[str]` : les noms des agents.
- **Change A** :
  - dans `ServiceChat`, à la fin d'une **rédaction par l'agent** (action `rediger`), on appelle `avis.lancer(document_id)`. Un `PUT` de Nicolas ne déclenche rien ;
  - à `valider`, on appelle `avis.abandonner(document_id)` ;
  - à la rédaction suivante, les avis `ouvert` du document sont ajoutés en annexe, avec le texte `"Avis ouverts à prendre en compte :\n\n- <agent> : <contenu>"`.
- Routes :
  - `POST /api/documents/{id}/avis` relance les avis à la main, et renvoie `202` ;
  - `PATCH /api/avis/{id} {etat: "pris_en_compte" | "ecarte" | "ouvert"}` ;
  - dans le détail d'un pipeline, `document` gagne `version`, `avis: [{id, agent, contenu, etat, version, ancienne: bool}]` (`ancienne` vaut `version < document.version`) et `avis_en_cours: [str]`.

- [ ] **Étape 1 : tests**
  - `test_redaction_declenche_les_avis_du_plan` : `architecte` et `challenger` donnent deux avis `ouvert`, avec `version == 1` ;
  - `test_put_de_nicolas_ne_declenche_rien` ;
  - `test_avis_marque_ancien_apres_correction` ;
  - `test_avis_ouverts_donnes_a_la_redaction_suivante` ;
  - `test_valider_abandonne_les_avis_en_cours` (point de revue n° 1) : avec le faux modèle bloqué, après `valider`, aucun avis n'est enregistré, même une fois le modèle libéré ;
  - `test_challenger_change_de_modele_si_meme_que_le_redacteur` ;
  - `test_demande_manuelle` ;
  - `test_avis_ne_bloque_pas_la_validation`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): avis de l'architecte et du challenger sur les brouillons`.

### Task 7: le PM

**Fichiers :**
- Créer : `backend/portail/outils_portail.py`, `backend/tests/test_pm.py`
- Modifier : `backend/portail/db.py` (`Pipeline.projet_id` devient nullable), la migration `0004`, `backend/portail/moteur.py`, `backend/portail/chat.py`, `backend/portail/api.py`

**Interfaces :**
- **Change A** :
  - `creer_pipeline` accepte `projet_id=None` **seulement** pour le type `pm`, et l'exige pour tous les autres types (`Refus(422)`) ;
  - `GET /api/pipelines` exclut le type `pm`, sauf avec `?type=pm` ;
  - `POST /api/pipelines {type: "pm"}` crée une conversation.
- `class OutilsPortail(sessions)` suit l'interface d'outils de C (`schemas()`, `executer(nom, arguments) -> tuple[str, bool]`). Chaque outil fait une requête `SELECT` et renvoie du JSON compact, **avec des dates ISO** :
  - `projets()` : `[{id, nom, depot_url, spec_courante: bool}]` ;
  - `pipelines(etat?, projet_id?, depuis?)` : au plus 50, du plus récent au plus ancien ;
  - `taches(projet_id, colonne?)` : `[{id, titre, colonne, verrou, pr_url, resume_blocage}]` ;
  - `pipeline(id)` : le détail, avec les étapes, leurs erreurs, la phase `dev`, les renvois et la PR ;
  - `en_attente_de_nicolas()` : les étapes `en_attente`, les propositions `ouverte`, les tâches `en_revue` avec leur PR, et les tâches `bloquee` ;
  - `activite(depuis)` : les `TacheEvenement` et les changements d'état de pipeline depuis la date `depuis`, au plus 200.
- **Change B** : dans `ServiceChat`, un agent `produit: chat` passe par `boucle_outils` avec `OutilsPortail`, et sans document. Il n'a pas de bouton « Rédiger ». La jauge ne compte que la conversation.

- [ ] **Étape 1 : tests**
  - `test_outils_pm_lecture_seule` : chaque outil est appelé dans une transaction surveillée par un écouteur SQLAlchemy `before_cursor_execute`, qui échoue sur tout `INSERT`, `UPDATE` ou `DELETE` ;
  - `test_en_attente_de_nicolas` : il y a une étape en attente, une proposition ouverte, une tâche en revue et une tâche bloquée. Les quatre apparaissent ;
  - `test_activite_depuis` ;
  - `test_conversation_pm_sans_projet` : le faux modèle appelle `en_attente_de_nicolas`, puis répond. Le message `tool` est enregistré, et le pipeline n'apparaît pas dans `GET /api/pipelines` ;
  - `test_type_autre_sans_projet_422`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): le PM, un chat en lecture seule sur l'état du portail`.

### Task 8: résumé du matin

**Fichiers :**
- Créer : `backend/portail/resume.py`, `backend/tests/test_resume.py`
- Modifier : `backend/portail/api.py` (lifespan), `backend/portail/config.py` (`resume_heure = "07:00"`), `backend/portail/db.py` et la migration `0004` (une table `Resume` : `id`, `jour` (date, unique), `pipeline_id`, `envoye_le`)

**Interfaces :**
- `def prochaine_echeance(maintenant: datetime, heure: str) -> datetime`, en `America/Toronto` (avec `zoneinfo`) : c'est aujourd'hui à `heure` si cette heure n'est pas encore passée, sinon demain.
- `async def resumer_si_du(sessions, catalogue, llm_fond, notifier, maintenant) -> bool`. Si **aujourd'hui** n'a pas de `Resume`, que `maintenant >= aujourd'hui à heure`, et qu'il y a eu de l'activité depuis le dernier `Resume` (ou depuis 24 h s'il n'y en a pas) :
  - on crée un pipeline `pm` intitulé « Résumé du <jour> » ;
  - on lance la boucle du PM avec la consigne fixe « Ce qui s'est passé depuis le dernier résumé, ce qui est bloqué, ce qui attend Nicolas. Court, en puces. » ;
  - on enregistre `Resume(jour)` **avant** l'envoi ;
  - on appelle `notifier("Résumé du matin", texte[:4000], lien vers la conversation)`.

  La fonction renvoie `True` si un résumé a été envoyé. Sans activité, on enregistre quand même `Resume(jour)`, sans envoi, et elle renvoie `False`.
- Une boucle au lifespan appelle `resumer_si_du` **une fois au démarrage**, puis dort jusqu'à `prochaine_echeance`.

- [ ] **Étape 1 : tests**, avec une horloge injectée :
  - `test_prochaine_echeance`, paramétré : 06:59 donne aujourd'hui à 07:00, 07:01 donne demain à 07:00, et le passage à l'heure d'été (8 mars 2026) donne 07:00 heure locale ;
  - `test_pas_d_envoi_sans_activite` ;
  - `test_envoi_avec_activite_et_une_seule_fois_par_jour` (point de revue n° 4) : un démarrage à 09:00 envoie, et un deuxième appel le même jour n'envoie rien ;
  - `test_avant_l_heure_rien`.
- [ ] **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests). La migration `0004` monte et descend.
- [ ] **Étape 5 : commit** `feat(portail): résumé du matin par ntfy`.

### Task 9: interface de D

**Fichiers :**
- Créer : `frontend/src/components/PanneauAvis.vue`, `frontend/src/components/TiroirPM.vue`, `frontend/src/components/ControlesDev.vue`
- Modifier : `frontend/src/api.ts`, `frontend/src/App.vue`, `frontend/src/components/EditeurDocument.vue`, `frontend/src/views/PipelineView.vue`, `frontend/src/components/ConfigExecution.vue`, et ajouter `frontend/src/avis.test.ts`

**Interfaces :**
- `api.ts` gagne `Avis`, `demanderAvis`, `changerEtatAvis`, `ExecutionDev.notes` et `ExecutionDev.controle_courant`.
- `PanneauAvis`, à côté de `EditeurDocument` :
  - une carte par avis, avec l'agent, le contenu rendu par `rendreMarkdown`, et un badge « sur une version antérieure » si `ancienne` ;
  - les boutons « Pris en compte », « Écarté » et « Rouvrir » ;
  - « Avis en cours : … » tant que `avis_en_cours` n'est pas vide ;
  - le bouton « Demander un avis ».
- `TiroirPM`, ouvert par un bouton « PM » dans l'en-tête de `App.vue`, sur toutes les pages :
  - la liste des conversations PM, dont les résumés du matin, et « Nouvelle conversation » ;
  - le chat réutilise `ChatEtape`, en mode `chat`, sans « Rédiger ».
- `ControlesDev`, dans `PipelineView` pour un pipeline `dev` :
  - le compteur de renvois sous la forme `n / renvois_max` ;
  - pour chaque contrôle, son verdict et ses remarques ;
  - les faits vérifiés (les bloquants en rouge) ;
  - les notes, regroupées par agent.
- `ConfigExecution` : l'exemple pré-rempli inclut `chemins_doc`, `regles` et les commandes `lint` et `securite`, en commentaire.
- `avis.test.ts` porte sur une fonction pure `trierAvis(avis)`, dans `avis.ts` (à créer) : les avis `ouvert` d'abord, les plus récents en tête, et les `abandonne` masqués.

- [ ] **Étape 1 : test** de `trierAvis`. **Étape 2 :** échec. **Étape 3 :** implémenter. **Étape 4 :** `npm test` et `npm run build` donnent PASS.
- [ ] **Étape 5 : vérification manuelle**, si LiteLLM est joignable :
  1. rédiger un plan : deux avis apparaissent, et un badge « ancienne » après une correction ;
  2. demander au PM « qu'est-ce qui m'attend ? » ;
  3. une tâche `dev` montre les contrôles et leurs notes.

  Sinon, le noter comme non vérifié.
- [ ] **Étape 6 : commit** `feat(portail): interface des avis, du PM et des contrôles`.

*Aucune tâche dans le dépôt Infra :* le sujet ntfy et le lanceur sont déjà mis en place par C.
