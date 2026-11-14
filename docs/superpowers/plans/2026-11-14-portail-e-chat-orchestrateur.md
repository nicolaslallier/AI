# Portail — E : chat avec l'orchestrateur : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** une page *Chat* hors projet où Nicolas parle à l'agent `orchestrateur` (LiteLLM), qui lit l'état du portail et propose des actions exécutées seulement après confirmation.

**Architecture :** nouvelles tables (`conversation`, `message_conversation`, `action_conversation`), un `ServiceConversation` calqué sur `ServiceChat` qui réutilise `ClientLLM`, `boucle_outils`, `Diffuseur` (instance à part) et la jauge ; un objet d'outils `OutilsPortail` qui suit le protocole d'outils de C (`schemas()` + `executer`). Une action proposée n'est qu'une ligne en base ; la route de confirmation l'exécute avec les fonctions existantes du portail.

**Tech Stack :** Python 3.12, FastAPI, SQLAlchemy async, Alembic, Postgres, pytest ; Vue 3, TypeScript, vitest.

**Spec :** `docs/superpowers/specs/2026-11-14-portail-e-chat-orchestrateur-design.md`

## Global Constraints

- **Point de départ : `main` après la fusion de C** (PR #22, `e81030b`), vérifié : `boucle_outils(llm, agent, messages, outils, sur_appel)` lit `outils.schemas() -> list[dict]` et appelle `async outils.executer(nom, arguments) -> tuple[str, bool]` ; `pipelines.dev` existe ; `app.state.orchestrateur` est **déjà pris** par l'orchestrateur `dev` de C (le service de E s'appelle `app.state.conversations`) ; il n'y a **pas** de canal d'événements global (`publier_global` n'existe pas) : E n'en publie pas ; `api._annuler(request, s, pipeline_id, clos)` et `api._reveiller(request)` (réveil de l'`Ordonnanceur`) existent. Si une autre interface diffère, suivre le code fusionné et le noter dans le rapport de tâche.
- Migrations : E commence à `0004`, après `0003_boucle_dev`.
- Livré en deux temps : tâches 1 à 4 (temps 1, l'orchestrateur répond), tâches 5 à 7 (temps 2, il agit). Le temps 1 est utilisable seul.
- Le chat d'étape (`ServiceChat`, `ChatEtape.vue`, routes `/api/etapes/…`) garde exactement son comportement : ses tests existants passent sans modification.
- Tous les textes vus par Nicolas ou par le modèle sont en français.
- Une action ne s'exécute **que** par `POST /api/actions/{id}/confirmer`. Aucun autre chemin.
- Auteur des écritures faites par une action confirmée : `"nicolas"`.
- Nom de l'agent : `orchestrateur`. Type de pipeline refusé dans `lancer_pipeline` : `dev` (« pour démarrer une tâche, déplace-la dans Prête »).
- Migrations : une par temps, `down_revision` = la tête existante au moment de la tâche. La CI exécute `alembic upgrade head`, `alembic check`, `alembic downgrade base`.
- Vérifications : `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest` ; `cd frontend && npm test && npm run build`.

## Review Focus

- **Double confirmation** (double clic, deux onglets) : l'action s'exécute une seule fois, le second appel reçoit 409. → test `test_confirmer_deux_fois_en_parallele` (tâche 6).
- **État changé entre proposition et confirmation** (tâche verrouillée par un pipeline `dev`, planification déjà en cours, projet supprimé) : l'action passe `echouee` avec le message du refus, aucune écriture partielle, et le modèle est relancé avec ce refus. → `test_confirmer_refus_du_portail` (tâche 5) et `test_confirmer_refus_relance_le_modele` (tâche 6).
- **Le modèle propose une action puis enchaîne d'autres appels** dans le même tour : les appels suivants sont ignorés, une seule action est proposée. → `test_arret_apres_proposition` (tâche 6).
- **Redémarrage pendant une réponse** : la conversation ne reste pas bloquée `en_cours` ; elle passe `erreur` et « Réessayer » fonctionne ; les actions `proposee` restent confirmables. → `test_redemarrage_marque_erreur` (tâche 3), `test_action_proposee_survit_au_redemarrage` (tâche 6).
- **Confirmer pendant que le modèle termine sa réponse** : 409 « attends la fin de la réponse », l'action reste `proposee`. → `test_confirmer_pendant_reponse_409` (tâche 6).

---

## Temps 1 — l'orchestrateur répond

### Task 1 : tables des conversations et agent `orchestrateur`

**Files :**
- Modify : `backend/portail/db.py`, `backend/portail/agents.py`, `agents.yaml`, `backend/tests/conftest.py` (catalogue de test)
- Create : `backend/migrations/versions/0004_conversations.py`
- Test : `backend/tests/test_agents.py`

**Interfaces :**
- Produces :
  - `class Conversation(Base)`, table `conversation` : `id`, `titre: str` (String(200), défaut `""`), `etat: str` (`"pret" | "en_cours" | "erreur"`, défaut `"pret"`), `erreur: str | None` (Text), `cree_le`, `maj_le` (`_horodatage(onupdate=func.now())`).
  - `class MessageConversation(Base)`, table `message_conversation` : `id`, `conversation_id` (FK cascade), `role: str` (`user | assistant | system | tool`), `contenu: Text`, `outil: str | None`, `cree_le`. Index sur `conversation_id`.
  - `OUTILS_LECTURE_PORTAIL = ("lister_projets", "lire_projet", "lister_pipelines", "lire_pipeline", "lire_kanban")` dans `agents.py` ; `Agent.outils` accepte ces noms en plus de ceux de C.
  - Règles du catalogue (dans `charger_catalogue`, `CatalogueInvalide`) : un agent ne mélange pas outils du portail et outils de dépôt/espace ; un agent qui a des outils du portail ne figure dans aucun pipeline.

- [ ] **Step 1 : tests qui échouent** dans `test_agents.py` :
  - `test_outils_portail_acceptes` : un agent avec `outils: [lister_projets, lire_kanban]` se charge.
  - `test_outils_portail_et_depot_melanges_refuses` : `outils: [lire, lister_projets]` → `CatalogueInvalide`, message contenant `« x »`.
  - `test_agent_portail_dans_un_pipeline_refuse` : `pipelines: {spec: [x]}` avec `x` qui a `lister_projets` → `CatalogueInvalide`.
  - `test_agents_yaml_du_depot_charge` (existe peut-être déjà) : `charger_catalogue("agents.yaml")` contient `orchestrateur` avec les 5 outils de lecture.
- [ ] **Step 2 :** `uv run pytest tests/test_agents.py` → FAIL.
- [ ] **Step 3 : implémenter** les modèles, les règles du catalogue, et l'agent `orchestrateur` dans `agents.yaml` : modèle et `contexte_max` comme l'agent `spec`, `temperature: 0.3`, les 5 outils de lecture, `tours_max: 10`. Prompt système, en français : il répond aux questions de Nicolas ; pour une spec, il pose une question à la fois et ne rédige que sur demande ; il ne parle des projets, pipelines et tâches qu'à partir de ses outils ; il ne prétend jamais avoir fait une action. Ajouter `orchestrateur` au catalogue de test de `conftest.py`.
- [ ] **Step 4 :** migration `0004_conversations.py` (`alembic revision --autogenerate`, relue à la main). Puis `uv run alembic upgrade head && uv run alembic check && uv run alembic downgrade base && uv run alembic upgrade head` → sans erreur ; `uv run pytest` → PASS.
- [ ] **Step 5 : commit** `feat(portail): tables des conversations et agent orchestrateur`.

### Task 2 : outils de lecture du portail

**Files :**
- Create : `backend/portail/outils_portail.py`
- Test : `backend/tests/test_outils_portail.py`

**Interfaces :**
- Consumes : `Agent.outils`, les modèles `Projet`, `Pipeline`, `Etape`, `Tache`, `spec_courante` (moteur).
- Produces : `class OutilsPortail(sessions: async_sessionmaker, noms: list[str])` avec `schemas() -> list[dict]` (seulement les outils de `noms`) et `async executer(nom: str, arguments: str) -> tuple[str, bool]`. Le module expose `SCHEMAS_PORTAIL: dict[str, dict]` ; la tâche 6 y ajoute les actions. Le PM de D réutilisera ce module.

Outils et paramètres :
`lister_projets()` · `lire_projet(projet_id: int)` (avec la spec courante, tronquée) · `lister_pipelines(projet_id?: int, etat?: str)` · `lire_pipeline(pipeline_id: int)` (étapes : ordre, agent, état, erreur) · `lire_kanban(projet_id: int)` (tâches par colonne : id, titre, protégée, verrou).

Règles : sortie texte compacte, une ligne par élément, au plus **8 000 caractères** puis `… (tronqué)` ; un id inconnu → `("erreur : projet 12 introuvable", False)` ; JSON invalide, argument manquant ou de mauvais type → `("erreur : arguments invalides : …", True)`.

- [ ] **Step 1 : tests qui échouent** (base de test, données créées par les modèles) :
  - `test_schemas_filtres_par_noms` : `OutilsPortail(sessions, ["lister_projets"]).schemas()` a un seul élément, nommé `lister_projets`.
  - `test_lister_projets` : deux projets `EA` et `Glee` → le texte contient les deux noms et leurs ids.
  - `test_lire_projet_avec_spec_courante` : un `Document` `spec` `validee` → son contenu apparaît.
  - `test_lire_kanban_par_colonne` : une tâche `prete` → la ligne est sous `prete`.
  - `test_id_inconnu_n_est_pas_mal_forme` : `executer("lire_projet", '{"projet_id": 999}')` → `("erreur : projet 999 introuvable", False)`.
  - `test_arguments_invalides_mal_formes` : `executer("lire_projet", "pas du json")` → second élément `True`.
  - `test_sortie_bornee` : 500 projets → `len(texte) <= 8000 + 20` et finit par `(tronqué)`.
- [ ] **Step 2 :** `uv run pytest tests/test_outils_portail.py` → FAIL.
- [ ] **Step 3 : implémenter** `outils_portail.py`. Valider les arguments avec un petit `BaseModel` pydantic par outil.
- [ ] **Step 4 :** `uv run pytest` → PASS.
- [ ] **Step 5 : commit** `feat(portail): outils de lecture du portail pour l'orchestrateur`.

### Task 3 : service des conversations et routes

**Files :**
- Create : `backend/portail/conversations.py`, `backend/tests/test_conversations.py`
- Modify : `backend/portail/api.py` (lifespan + routes), `backend/portail/schemas.py`

**Interfaces :**
- Consumes : `OutilsPortail` (tâche 2), `boucle_outils`, `ClientLLM.flux`, `FiltreReflexion`, `retirer_reflexion`, `jauge`, `Diffuseur`, `_sse` (à importer de `chat.py`).
- Produces :
  - `construire_conversation(agent: Agent, messages: list[MessageConversation]) -> list[dict]` : prompt système, puis les messages `user`, `assistant` et `system` dans l'ordre (les `tool` ne sont **pas** rejoués : ils servent à l'affichage, comme dans le chat d'étape).
  - `class ServiceConversation(sessions, catalogue, llm, diffuseur: Diffuseur)` avec `taches: dict[int, asyncio.Task]` et les méthodes `creer() -> Conversation`, `envoyer(conversation_id, contenu)`, `reessayer(conversation_id)`, `lancer(conversation_id)`, `supprimer(conversation_id)`, `flux(conversation_id) -> AsyncIterator[str]`, `recuperer_interrompues(s) -> int`.
  - Routes : `GET /api/conversations` → `list[ConversationResume]` (`id, titre, etat, maj_le`, tri `maj_le` décroissant) ; `POST /api/conversations` → 201 `ConversationDetail` ; `GET /api/conversations/{id}` → `ConversationDetail` (`id, titre, etat, erreur, messages: list[MessageOut], jauge: Jauge`) ; `PATCH /api/conversations/{id}` `{titre}` ; `DELETE /api/conversations/{id}` → 204 ; `POST /api/conversations/{id}/messages` `{contenu}` → 202 ; `POST /api/conversations/{id}/reessayer` → 202 ; `GET /api/conversations/{id}/flux` (SSE, mêmes événements que le chat d'étape : `partiel`, `delta`, `outil`, `fin`, `erreur`).
  - `app.state.conversations`, avec **son propre** `Diffuseur()`.

Comportement (sur le modèle de `ServiceChat`) :
- `envoyer` : verrou `FOR UPDATE` sur la conversation ; 404 si absente ; 409 « une réponse est déjà en cours » si `en_cours` ; 422 « le message est vide » ; 409 « contexte plein : ouvre une nouvelle conversation » si la jauge est `plein` avec le nouveau message ; titre vide → les 60 premiers caractères du message ; passe `en_cours`, `erreur = None` ; commit, puis `lancer`. Accepté depuis `pret` **et** `erreur`.
- `reessayer` : 409 « rien à relancer » sauf si `erreur`.
- Tâche de fond : agent sans outils → streaming par `flux` (comme `_streamer`) ; avec outils → `boucle_outils` avec `OutilsPortail(sessions, agent.outils)`, chaque appel enregistré en message `tool` (`outil` = libellé, contenu tronqué à 2000) et publié `{"type": "outil", "libelle": …}`. Fin : message `assistant`, état `pret`, `{"type": "fin"}`. Réponse vide → `erreur` « réponse vide du modèle ». Toute exception → `erreur` avec le message, et l'événement `erreur` part même si l'écriture échoue.
- `supprimer` : 409 si `en_cours`.
- Agent absent du catalogue → 409 « agent « orchestrateur » absent de agents.yaml ».
- Lifespan : `recuperer_interrompues` passe les conversations `en_cours` à `erreur` « interrompue par un redémarrage du serveur » ; à l'arrêt, les tâches de fond sont annulées comme celles de `ServiceChat`.

- [ ] **Step 1 : tests qui échouent** (`client`, `faux_llm` de `conftest.py`) :
  - `test_echange_complet` : créer, envoyer « Bonjour », réponse `FauxLLM` → détail avec 2 messages (`user`, `assistant`), état `pret`, titre « Bonjour ».
  - `test_message_enregistre_avant_l_appel` : `FauxLLM.exception = ErreurLLM("boom")` → état `erreur`, `erreur` contient `boom`, le message `user` est enregistré ; `reessayer` → `pret` après une réponse valide.
  - `test_double_envoi_409`, `test_message_vide_422`, `test_reponse_vide_erreur`, `test_contexte_plein_409`.
  - `test_outils_de_lecture` : `FauxLLM.reponses` = un appel `lister_projets` puis un texte → un message `tool` de libellé `lister_projets` entre `user` et `assistant`.
  - `test_outils_non_rejoues` : au 2ᵉ envoi, les messages passés à `completer` ne contiennent aucun `role: tool` des tours précédents.
  - `test_flux_sse` (calqué sur `test_flux_sse_et_reprise_en_cours`).
  - `test_supprimer_en_cours_409`, `test_supprimer`.
  - `test_redemarrage_marque_erreur` : une conversation `en_cours` en base, nouveau `LifespanManager` → `erreur` « interrompue par un redémarrage du serveur ».
  - `test_chat_d_etape_inchange` : rien à écrire, `tests/test_chat.py` doit passer tel quel.
- [ ] **Step 2 :** `uv run pytest tests/test_conversations.py` → FAIL.
- [ ] **Step 3 : implémenter** `conversations.py`, les schémas et les routes.
- [ ] **Step 4 :** `uv run pytest` → PASS (tout le dossier, `test_chat.py` compris).
- [ ] **Step 5 : commit** `feat(portail): conversations libres avec l'orchestrateur`.

### Task 4 : page Chat

**Files :**
- Create : `frontend/src/views/ChatView.vue`, `frontend/src/conversations.ts`, `frontend/src/conversations.test.ts`
- Modify : `frontend/src/flux.ts`, `frontend/src/flux.test.ts`, `frontend/src/views/PipelineView.vue`, `frontend/src/api.ts`, `frontend/src/router.ts`, `frontend/src/App.vue`

**Interfaces :**
- Consumes : les routes de la tâche 3.
- Produces :
  - `ecouterFlux(url: string, rappels: RappelsFlux)` : prend l'URL au lieu de l'id d'étape. `PipelineView.vue` passe `` `/api/etapes/${etapeId}/flux` ``.
  - `api.ts` : `ConversationResume`, `ConversationDetail` (réutilise `Message` et `Jauge`), `listerConversations`, `creerConversation`, `lireConversation`, `renommerConversation`, `supprimerConversation`, `envoyerMessageConversation`, `reessayerConversation`.
  - `conversations.ts` : `trier(liste: ConversationResume[]): ConversationResume[]` (par `maj_le` décroissant). La tâche 7 y ajoute `fil`.
  - Routes `/chat` (name `chat`) et `/chat/:id` (name `conversation`, `props: true`) vers `ChatView`. Lien **Chat** dans l'en-tête, après *Projets*.

Page : colonne de gauche (*+ Nouvelle*, puis la liste) ; à droite, la conversation affichée comme dans `ChatEtape.vue` (bulles, `rendreMarkdown`, appels d'outils repliés, `JaugeContexte`, bulle en cours avec le partiel), la saisie (Entrée envoie, sauf composition IME), « Réessayer » si `erreur`, et un bouton *Supprimer*. *+ Nouvelle* crée la conversation et navigue vers `/chat/:id`.

- [ ] **Step 1 : tests qui échouent** : `flux.test.ts` adapté (l'`EventSource` reçoit l'URL passée) ; `conversations.test.ts` : `trier` met la plus récente en premier.
- [ ] **Step 2 :** `npm test` → FAIL.
- [ ] **Step 3 : implémenter.**
- [ ] **Step 4 :** `npm test && npm run build` → PASS. Puis lancer le portail en local avec un vrai LiteLLM ou le `FauxLLM`, et vérifier dans le navigateur : créer une conversation, recevoir une réponse en streaming, recharger la page, la conversation est toujours là.
- [ ] **Step 5 : commit** `feat(portail): page Chat`.

---

## Temps 2 — l'orchestrateur agit, avec confirmation

### Task 5 : actions — table, validation et exécution

**Files :**
- Create : `backend/portail/actions.py`, `backend/migrations/versions/0005_actions_conversation.py`, `backend/tests/test_actions.py`
- Modify : `backend/portail/db.py`, `backend/portail/schemas.py` (`verifier_depot` déplacé depuis `api.py`), `backend/portail/api.py`

**Interfaces :**
- Produces :
  - `class ActionConversation(Base)`, table `action_conversation` : `id`, `conversation_id` (FK cascade), `nom: str`, `parametres: dict` (JSON), `etat: str` (`proposee | confirmee | refusee | echouee | perimee`, défaut `proposee`), `resultat: str | None`, `lien: str | None` (ex. `/projets/12`, `/pipelines/34`, `/projets/12/kanban`), `cree_le`, `maj_le`.
  - `ACTIONS: dict[str, type[BaseModel]]`, les paramètres de chaque action : `creer_projet(nom, description="", depot_url=None, branche_ref=None)`, `deposer_spec(projet_id, contenu)`, `lancer_pipeline(projet_id, type)`, `creer_tache(projet_id, titre, description="", criteres=[], depend_de=[])`, `modifier_tache(tache_id, titre?, description?, criteres?)`, `deplacer_tache(tache_id, colonne)`, `annuler_tache(tache_id)`. Réutiliser `ProjetIn`, `DonneesTache` et `DonneesTachePartielles` là où c'est possible.
  - `async def valider_action(s, catalogue, nom: str, parametres: dict) -> dict` : renvoie les paramètres normalisés ou lève `Refus(422, …)`. Elle vérifie ce qu'on peut vérifier à la proposition : projet ou tâche existant, type de pipeline connu et différent de `dev`, colonne dans `COLONNES`, URL de dépôt (`verifier_depot`), contenu de spec non vide, aucun pipeline `spec` ouvert pour `deposer_spec` (« un pipeline de spec est déjà ouvert : finis-le ou annule-le »).
  - `@dataclass class Execution` : `resultat: str`, `lien: str | None`, `etapes_a_lancer: list[int]` (passées à `ServiceChat.lancer` après le commit).
  - `async def executer_action(s, catalogue, action: ActionConversation) -> Execution` : appelle les fonctions existantes avec l'auteur `"nicolas"`. `creer_projet` → `Projet` ; `deposer_spec` → `creer_pipeline(..., "spec")`, puis un `Document(type="spec", contenu, etat="validee")` sur l'étape, puis `terminer_etape` ; `lancer_pipeline` → `creer_pipeline` (l'étape auto va dans `etapes_a_lancer`) ; `creer_tache`, `modifier_tache`, `deplacer_tache` (en fin de colonne, `avant_id=None`). **`annuler_tache` n'est pas exécutée ici** : elle ouvre et ferme ses propres transactions (`_annuler` fait `rollback` puis `commit`), voir tâche 6. Toute vérification refaite au moment de l'exécution lève `Refus`.

- [ ] **Step 1 : tests qui échouent**, appels directs avec une session :
  - `test_valider_lancer_pipeline_dev_refuse` → `Refus` 422 dont le message contient « Prête ».
  - `test_valider_projet_inconnu`, `test_valider_colonne_inconnue`, `test_valider_spec_vide`, `test_valider_spec_deja_ouverte`.
  - `test_executer_creer_projet` → le projet existe, `lien == f"/projets/{id}"`.
  - `test_executer_deposer_spec_validee` → `spec_courante(s, projet_id).contenu == contenu`, le pipeline `spec` est `terminee`, puis `creer_pipeline(..., "planification")` passe.
  - `test_executer_lancer_planification` → `etapes_a_lancer` contient l'étape `plan`.
  - `test_executer_deplacer_vers_prete` → la tâche est en `prete`, et le journal a `auteur == "nicolas"`.
  - `test_executer_modifier_tache_la_protege` → `protegee is True`.
  - `test_confirmer_refus_du_portail` : une tâche verrouillée (`verrou` posé) puis `deplacer_tache` → `Refus` ; dans un `begin_nested()`, rien n'est écrit.
- [ ] **Step 2 :** `uv run pytest tests/test_actions.py` → FAIL.
- [ ] **Step 3 : implémenter.** Migration `0005` comme à la tâche 1.
- [ ] **Step 4 :** `uv run alembic upgrade head && uv run alembic check` → OK ; `uv run pytest` → PASS.
- [ ] **Step 5 : commit** `feat(portail): actions de l'orchestrateur, validation et exécution`.

### Task 6 : propositions dans la boucle, confirmation et refus

**Files :**
- Modify : `backend/portail/boucle.py`, `backend/portail/outils_portail.py`, `backend/portail/agents.py`, `agents.yaml`, `backend/portail/conversations.py`, `backend/portail/api.py`, `backend/portail/schemas.py`
- Test : `backend/tests/test_boucle.py`, `backend/tests/test_conversations.py`

**Interfaces :**
- Consumes : `ACTIONS`, `valider_action`, `executer_action`, `Execution` (tâche 5).
- Produces :
  - `boucle_outils` : après chaque appel exécuté, si `getattr(outils, "arret", False)` devient vrai, les appels restants du même message reçoivent `"ignoré : une action attend la confirmation de Nicolas"`. Puis un dernier `completer` **sans outils** donne le texte final, et la boucle renvoie `ResultatBoucle(texte, limite_atteinte=False)`. Sans `arret`, le comportement ne change pas.
  - `OutilsPortail(sessions, noms, catalogue=None, conversation_id=None)` : pour un nom de `ACTIONS`, `executer` appelle `valider_action`. Un `Refus` donne `("erreur : <message>", False)`. Sinon, l'action est insérée `proposee` (et commitée), `self.arret = True`, et le résultat vaut `"action n°<id> proposée, en attente de la confirmation de Nicolas. Termine ta réponse sans appeler d'outil."`. Une 2ᵉ proposition dans le même tour donne `"ignoré : …"`.
  - `agents.py` : `OUTILS_ACTIONS_PORTAIL` = les 7 noms d'actions, comptés comme outils du portail dans les règles de la tâche 1. `agents.yaml` : l'orchestrateur reçoit les 7 actions, et son prompt explique qu'une action n'est faite qu'après confirmation, et qu'une spec déposée est validée.
  - `ServiceConversation.confirmer(action_id)` et `refuser(action_id)` ; routes `POST /api/actions/{id}/confirmer` et `POST /api/actions/{id}/refuser` → 202. `ConversationDetail` gagne `actions: list[ActionOut]` (`id, nom, parametres, etat, resultat, lien, cree_le`).
  - `ServiceConversation` reçoit le `ServiceChat` (pour `lancer`) et deux rappels construits dans `api.py` : `annuler_tache(tache_id) -> None`, qui reprend exactement le corps de la route `POST /api/taches/{id}/annuler` (`_tache`, refus 409 « rien à annuler » sans verrou, `_annuler(..., clos=False)`), et `reveiller() -> None` (`_reveiller`). Pour cela, `_annuler` et `_reveiller` prennent l'état de l'app (`request.app.state`) au lieu de la `Request` ; les routes existantes passent `request.app.state`.

Comportement :
- `confirmer` : verrou sur la conversation, puis sur l'action (`FOR UPDATE`). Conversation `en_cours` → 409 « attends la fin de la réponse ». Action autre que `proposee` → 409 « action déjà traitée » (ou « action périmée »). Ensuite `executer_action` dans `begin_nested()` :
  - si ça réussit : `confirmee`, `resultat`, `lien`, et un message `system` « Action n°<id> (<nom>) confirmée par Nicolas : <resultat> » ;
  - si un `Refus` est levé : `echouee`, `resultat` = le message, et un message `system` « Action n°<id> (<nom>) refusée par le portail : <message> ».
  
  Dans les deux cas, la conversation passe `en_cours`, puis commit. Après le commit : `ServiceChat.lancer` pour chaque étape à lancer, `reveiller()` (une tâche a pu entrer dans *Prête*), et enfin `lancer(conversation_id)`, qui relance le modèle pour qu'il commente le résultat. **Cas `annuler_tache`** : l'action est d'abord verrouillée et passée `confirmee` (commit, ce qui empêche une double exécution), puis le rappel `annuler_tache` s'exécute ; s'il lève `Refus`, l'action passe `echouee` avec le message. Le message `system` et la relance suivent comme pour les autres actions.
- `refuser` : mêmes vérifications. L'action passe `refusee`, un message `system` « Nicolas a refusé l'action n°<id> (<nom>) » est ajouté, et le modèle est relancé.
- `envoyer` : les actions `proposee` de la conversation passent `perimee`, dans la même transaction que le nouveau message.

- [ ] **Step 1 : tests qui échouent :**
  - `test_boucle.py::test_arret_apres_proposition` : avec un faux objet d'outils qui pose `arret` au 1ᵉʳ appel, un message de 3 appels → le 2ᵉ et le 3ᵉ reçoivent « ignoré », le dernier `completer` a `outils=None`, et le texte final est renvoyé.
  - `test_boucle.py::test_sans_arret_inchange` : les tests de boucle existants passent tels quels.
  - `test_proposition_cree_une_carte` : le modèle appelle `creer_projet` → le détail a 1 action `proposee`, aucun projet n'est créé, et la conversation est `pret`.
  - `test_proposition_invalide_sans_carte` : `lancer_pipeline` avec `type: dev` → aucune action, et le message `tool` contient « Prête ».
  - `test_confirmer_execute_et_relance` : confirmer → le projet existe, l'action est `confirmee` avec un `lien`, un message `system` est ajouté, puis un nouveau message `assistant` après la relance.
  - `test_refuser_relance` : l'action passe `refusee`, aucun projet n'est créé, et le message `system` « Nicolas a refusé » est ajouté.
  - `test_confirmer_deux_fois_en_parallele` : `asyncio.gather` de deux `confirmer` → un seul projet créé, un 202 et un 409.
  - `test_confirmer_pendant_reponse_409` : `FauxLLM` bloqué par un `Event` après la proposition → 409, et l'action reste `proposee`.
  - `test_confirmer_refus_relance_le_modele` : la tâche est verrouillée entre la proposition et la confirmation → l'action passe `echouee`, et le message `system` de refus figure dans la demande suivante au modèle.
  - `test_nouveau_message_perime_l_action` : envoyer un message → l'action passe `perimee`, et la confirmer ensuite renvoie 409.
  - `test_action_proposee_survit_au_redemarrage` : nouveau `LifespanManager` → la confirmation fonctionne.
  - `test_lancer_planification_lance_l_etape_auto` : après confirmation, `app.state.chat.taches` contient l'étape `plan`.
  - `test_confirmer_annuler_tache` : une tâche verrouillée par un pipeline `spec` en cours → après confirmation, la tâche est en `a_faire` sans verrou et l'action est `confirmee` ; sans verrou → l'action est `echouee` avec « rien à annuler ».
- [ ] **Step 2 :** `uv run pytest tests/test_boucle.py tests/test_conversations.py` → FAIL.
- [ ] **Step 3 : implémenter.**
- [ ] **Step 4 :** `uv run pytest` → PASS (tous les tests, ceux de C compris).
- [ ] **Step 5 : commit** `feat(portail): l'orchestrateur propose des actions confirmées par Nicolas`.

### Task 7 : cartes d'action

**Files :**
- Create : `frontend/src/components/CarteAction.vue`
- Modify : `frontend/src/conversations.ts`, `frontend/src/conversations.test.ts`, `frontend/src/api.ts`, `frontend/src/views/ChatView.vue`

**Interfaces :**
- Consumes : `ActionOut` et les routes de confirmation (tâche 6).
- Produces :
  - `api.ts` : `ActionConversation`, `confirmerAction(id)`, `refuserAction(id)`.
  - `conversations.ts` : `fil(messages: Message[], actions: ActionConversation[]): ({ type: 'message', message: Message } | { type: 'action', action: ActionConversation })[]`, trié par `cree_le` puis par `id`. Et `libelleAction(a: ActionConversation): string`, en français : « Créer le projet « EA » », « Déposer et valider la spec du projet n°3 », « Lancer le pipeline planification sur le projet n°3 », « Créer la tâche « … » », « Modifier la tâche n°7 », « Déplacer la tâche n°7 vers prete », « Annuler la tâche n°7 ».

Carte : le libellé, les paramètres exacts (pour `deposer_spec`, la spec **entière**, rendue avec `rendreMarkdown`), puis selon l'état :
- `proposee` : les boutons *Confirmer* et *Refuser*, désactivés pendant l'appel et quand la conversation est `en_cours` ;
- `confirmee` : le résultat, avec un lien `RouterLink` vers `lien` ;
- `echouee` : le message, en `.erreur` ;
- `refusee` et `perimee` : la carte grisée, avec son état.

Après un clic, la page recharge la conversation et écoute son flux.

- [ ] **Step 1 : tests qui échouent** : `fil` intercale une action entre deux messages selon `cree_le` ; `libelleAction` donne les libellés ci-dessus pour `creer_projet` et `deplacer_tache`.
- [ ] **Step 2 :** `npm test` → FAIL.
- [ ] **Step 3 : implémenter.**
- [ ] **Step 4 :** `npm test && npm run build` → PASS. Puis, dans le navigateur, avec le portail en local : demander « crée un projet Test », voir la carte, confirmer, voir la réponse de l'orchestrateur et suivre le lien vers le projet. Recommencer en refusant.
- [ ] **Step 5 : commit** `feat(portail): cartes de confirmation des actions dans le chat`.
