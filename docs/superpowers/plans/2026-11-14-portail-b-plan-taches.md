# Portail — B : spec → plan → kanban : plan d'implémentation

> **Pour les agents qui exécutent :** SOUS-SKILL REQUIS : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans, tâche par tâche. Les étapes utilisent des cases `- [ ]`.

**But :** lier un projet à un dépôt GitHub, faire rédiger un plan par un agent qui lit le dépôt en lecture seule, découper le plan validé en tâches proposées, et gérer ces tâches dans un kanban éditable par projet.

**Architecture :** on garde le service `portail` de A et on l'étend.
- Un module `depots` gère, avec `git` en sous-processus, un clone nu par projet et un arbre de travail détaché par étape, fixé sur un SHA.
- Un module `outils` donne les trois outils en lecture seule, confinés à cet arbre.
- Une boucle d'outils (`boucle`), non streamée, sert aux agents qui déclarent des outils.
- Les propositions de tâches sont des lignes en base, que Nicolas accepte ou rejette.
- Le kanban est une vue Vue avec le glisser-déposer natif du navigateur.

**Pile :** celle de A, sans aucune nouvelle dépendance. Le glisser-déposer est natif HTML5 et git est appelé en sous-processus. Il faut ajouter `git` à l'image.

**Spec :** `docs/superpowers/specs/2026-11-14-portail-b-plan-taches-design.md`. Elle s'appuie sur le design de A (`2026-11-14-portail-socle-design.md`) et sur le plan de A (`docs/superpowers/plans/2026-11-14-portail-socle.md`), dont les interfaces sont reprises ici. **On suppose que A est construit et fusionné.**

## Contraintes globales

- Toutes les contraintes globales du plan de A s'appliquent toujours : noms en français, agents seulement dans `agents.yaml`, aucun framework d'agents ni worker, jauge à 0,75 et 0,90, `<think>` retiré, DOMPurify.
- **Lecture seule, sans exception.** Les seules commandes git permises sont `clone --bare`, `fetch`, `rev-parse`, `symbolic-ref`, `worktree add|remove|prune` et `grep`. Aucun outil n'écrit ni n'exécute rien dans l'arbre.
- **Jeton GitHub** (`PORTAIL_GITHUB_JETON`, en lecture seule) : il est passé seulement par `git -c http.extraHeader="Authorization: Basic <base64("x-access-token:" + jeton)>"`. Il n'apparaît jamais dans une URL, dans `.git/config`, dans un message d'erreur ni dans un journal. Les messages d'erreur de git sont nettoyés de ce jeton avant d'être enregistrés.
- `depot_url` doit correspondre à `^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?(\.git)?$`, sinon `422`.
- **Volume de données** : `PORTAIL_DONNEES_DIR` (par défaut `/donnees`). Le clone nu va dans `depots/<projet_id>.git`, et l'arbre de chaque étape dans `arbres/<etape_id>`.
- Délais git : `fetch` et `clone` 120 s, les autres commandes 30 s. Au-delà, l'opération lève `ErreurDepot`.
- Fichiers de secrets refusés, comparés au **nom de fichier** : `.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`.
- Limites des outils :
  - `lister` : profondeur 2, au plus 300 entrées ;
  - `lire` : au plus 2000 lignes **et** 100 000 octets, avec la ligne `[… tronqué : <n> lignes au total]` ;
  - `chercher` : au plus 100 résultats ;
  - binaire : un octet NUL dans les 8 192 premiers octets ;
  - extrait enregistré pour chaque appel d'outil : 2000 caractères.
- Point de départ (aperçu du dépôt) : au plus **25 %** de `contexte_max`, estimé avec `estimer_jetons`.
- Boucle : `tours_max` vaut 20 par défaut. Après **3** appels mal formés consécutifs (JSON d'arguments invalide ou outil inconnu), l'étape échoue avec « le modèle <modele> ne gère pas correctement les outils ». On élague quand le contexte atteint 0,90 × `contexte_max`, jusqu'à redescendre à 0,75. Le texte de remplacement est exactement `[résultat retiré : relire si besoin]`.
- Colonnes du kanban (valeurs) : `a_faire`, `prete`, `en_cours`, `en_revue`, `terminee`, `bloquee`. Libellés : « À faire », « Prête », « En cours », « En revue », « Terminée », « Bloquée ».
- Rang : après chaque déplacement, toute la colonne est renumérotée `1000, 2000, 3000, …`.
- Auteur dans le journal : `"nicolas"` ou `"agent:<nom>"`.

## Points à surveiller en revue

1. **Branche de référence inexistante, ou dépôt vide** : l'étape passe à `echouee` avec « branche <b> introuvable dans le dépôt », jamais une trace Python. *Test : tâche 3.*
2. **Un fichier énorme ou d'une seule ligne de plusieurs Mo** (JS minifié) : `lire` coupe par octets et répond vite. Un motif d'expression régulière invalide dans `chercher` donne un texte d'erreur pour le modèle, pas une exception. *Tests : tâche 4.*
3. **Une proposition dont `depend_de` cite une clé inconnue, ou se cite elle-même** : la réponse est invalide. Le modèle est relancé une fois avec l'erreur, puis l'étape échoue. *Test : tâche 9.*
4. **Nicolas modifie une tâche visée par une proposition de modification ouverte** : accepter cette proposition donne `409` « proposition périmée », et la tâche garde la version de Nicolas. *Test : tâche 9.*
5. **Deux déplacements concurrents dans la même colonne** : après les deux, les rangs de la colonne sont distincts et contigus (1000, 2000…). *Test : tâche 8.*

---

### Task 1: catalogue, agents à outils, de plan et de tâches

**Fichiers :**
- Modifier : `backend/portail/agents.py`, `agents.yaml`, `backend/tests/test_agents.py`

**Interfaces :**
- **Change A** : `Agent` gagne les champs suivants :
  - `produit: Literal["spec", "plan", "taches"] = "spec"` : le type de document produit, ou `taches` pour des propositions ;
  - `auto: bool = False` : l'étape démarre seule, par une rédaction ou une génération ;
  - `outils: list[Literal["lister", "lire", "chercher"]] = []` ;
  - `tours_max: int = 20` (> 0).
- Nouvelles règles de validation, chacune avec un message qui nomme l'agent :
  - un agent `auto` doit avoir une `consigne_redaction` ;
  - un agent `produit: taches` ne peut pas avoir d'`outils`.
- Dans `agents.yaml` :
  - l'agent `spec` gagne `outils: [lister, lire, chercher]`. Ils ne servent que si le projet a un dépôt (tâche 7) ;
  - on ajoute l'agent `plan` : `produit: plan`, `auto: true`, `outils: [lister, lire, chercher]`, `tours_max: 20` ;
  - on ajoute l'agent `taches` : `produit: taches`, `auto: true`, sans outils ;
  - on ajoute `pipelines.planification: [plan, taches]`.

  Le prompt de `plan` rédige un plan d'implémentation en markdown, fondé sur la spec et sur le code lu (fichiers, modules, ordre des étapes, risques). Il indique le SHA lu. En révision, il part du plan précédent. La `consigne_redaction` de `taches` demande un JSON conforme au schéma de la tâche 9 : une tâche = un comportement testable.

- [ ] **Étape 1 : tests**
  - `test_agent_auto_sans_consigne_refuse` ;
  - `test_agent_taches_avec_outils_refuse` ;
  - `test_outil_inconnu_refuse` : `outils: [ecrire]` lève `CatalogueInvalide`, avec « ecrire » dans le message ;
  - `test_valeurs_par_defaut` : `produit == "spec"`, `auto is False`, `outils == []`, `tours_max == 20` ;
  - `test_agents_yaml_du_depot_est_valide` (déjà présent) vérifie maintenant aussi que `pipelines["planification"] == ["plan", "taches"]`.
- [ ] **Étape 2 :** pytest échoue. **Étape 3 :** implémenter. **Étape 4 :** pytest donne PASS, ruff OK.
- [ ] **Étape 5 : commit** `feat(portail): agents à outils, agents de plan et de tâches`.

### Task 2: modèle de données de B et dépôt du projet

**Fichiers :**
- Modifier : `backend/portail/db.py`, `backend/portail/api.py`, `backend/portail/schemas.py`, `backend/portail/config.py`
- Créer : `backend/migrations/versions/0002_plan_taches.py`, `backend/tests/test_api_projet_depot.py`

**Interfaces :**
- **Change A** : `Reglages` gagne `github_jeton: str = ""` et `donnees_dir: Path = Path("/donnees")`.
- **Change A** :
  - `Projet` gagne `depot_url: str | None` et `branche_ref: str | None`. Si `branche_ref` est nul, on prend la branche par défaut du dépôt ;
  - `Etape` gagne `sha: str | None` et `apercu: str | None` (le point de départ calculé une fois, voir la tâche 4) ;
  - `Message` gagne `outil: str | None`, le libellé de l'appel, par exemple `lire(src/a.py)`. Le rôle `tool` est maintenant permis.
- Nouvelles tables :
  - `Tache` : `id`, `projet_id`, `titre` (String 200), `description` (Text), `criteres` (JSON, liste de str), `fichiers` (JSON, liste de str), `colonne`, `rang` (int), `origine` (`"agent"` | `"manuel"`), `document_id` (nullable : le plan d'origine), `protegee` (bool, défaut false), `verrou` (pipeline_id nullable), `version` (int, défaut 1), `cree_le`, `maj_le`.
  - `TacheDependance` : `tache_id` et `depend_de_id`, avec une clé primaire composite et `ON DELETE CASCADE` des deux côtés.
  - `TacheEvenement` : `id`, `projet_id`, `tache_id` (int **sans** clé étrangère, pour que le journal survive à la suppression), `type` (`creation` | `modification` | `deplacement` | `suppression`), `auteur`, `donnees` (JSON), `cree_le`.
  - `Proposition` : `id`, `pipeline_id`, `etape_id`, `projet_id`, `sorte` (`nouvelle` | `modification` | `retrait`), `cle` (str nullable), `tache_id` (nullable), `version_tache` (int nullable), `donnees` (JSON), `etat` (`ouverte` | `acceptee` | `rejetee` | `perimee`), `tache_creee_id` (nullable), `cree_le`.
- API :
  - `POST /api/projets` et le nouveau `PATCH /api/projets/{id}` acceptent `depot_url?` et `branche_ref?`. L'URL est validée par l'expression des contraintes globales, sinon `422` « URL de dépôt GitHub invalide » ;
  - `GET /api/projets/{id}` renvoie aussi ces deux champs.

- [ ] **Étape 1 : tests** dans `test_api_projet_depot.py` :
  - `test_projet_avec_depot` : `https://github.com/nicolaslallier/EA` est accepté et relu tel quel ;
  - `test_url_invalide_422`, paramétré : `http://github.com/a/b`, `https://gitlab.com/a/b`, `https://github.com/a`, `https://x:y@github.com/a/b`, `file:///etc` ;
  - `test_patch_retire_le_depot` : `{"depot_url": null}` donne `null`.
- [ ] **Étape 2 :** pytest échoue.
- [ ] **Étape 3 : implémenter** les modèles, la migration `0002` écrite à la main, avec un `downgrade` complet, et les routes.
- [ ] **Étape 4 :** `alembic upgrade head`, puis `downgrade -1`, puis `upgrade head` réussissent sur la base de tests, et pytest donne PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): tables du kanban et des propositions, dépôt du projet`.

### Task 3: clones et arbres de travail par étape

**Fichiers :**
- Créer : `backend/portail/depots.py`, `backend/tests/test_depots.py`

**Interfaces :**
- Produit :
  - `class ErreurDepot(Exception)`.
  - `class Depots`, avec `__init__(self, donnees_dir: Path, jeton: str)`.
  - `async def preparer(self, projet_id: int, depot_url: str, branche_ref: str | None, etape_id: int, sha: str | None) -> tuple[Path, str]`. Elle renvoie le chemin de l'arbre et son SHA :
    - si l'arbre `arbres/<etape_id>` existe déjà, elle le renvoie tel quel ;
    - sinon, sous un `asyncio.Lock` propre au projet, elle fait un `clone --bare` si le clone n'existe pas, puis `fetch origin '+refs/heads/*:refs/heads/*' --prune` ;
    - si `sha` est donné, elle le réutilise ; sinon, elle prend `rev-parse <branche_ref>`, ou la branche donnée par `symbolic-ref HEAD` si `branche_ref` est nul ;
    - enfin, `worktree add --detach arbres/<etape_id> <sha>`.
  - `async def liberer(self, etape_id: int) -> None` : `worktree remove --force`, puis suppression du dossier s'il reste. Elle ne fait rien si l'arbre n'existe pas.
  - `async def nettoyer(self, garder: set[int]) -> None` : elle supprime chaque `arbres/<id>` dont l'id n'est pas dans `garder`, puis fait `worktree prune` sur chaque clone.
  - `def _git(self, *args, cwd, delai) -> str` : un `asyncio.create_subprocess_exec("git", *opts, *args)`, avec l'en-tête d'authentification **seulement** si `jeton` n'est pas vide, et `GIT_TERMINAL_PROMPT=0`. Un code de retour non nul lève `ErreurDepot(stderr nettoyé du jeton)`.

- [ ] **Étape 1 : tests** (pytest en async). Chaque test construit un dépôt d'origine local dans `tmp_path` (`git init -b main`, deux commits) et passe son chemin `file://` comme `depot_url` :
  - `test_preparer_cree_un_arbre_sur_la_branche` : l'arbre contient le fichier du dernier commit, et le SHA vaut le `rev-parse main` de l'origine ;
  - `test_sha_fige_pour_l_etape` : on ajoute un commit à l'origine, puis on rappelle `preparer` pour la même étape ; le SHA et le contenu n'ont pas changé ;
  - `test_nouvelle_etape_voit_le_nouveau_commit` ;
  - `test_sha_donne_recree_l_arbre` : après `liberer`, `preparer(..., sha=<ancien>)` recrée l'arbre sur ce SHA (c'est le cas de « Réessayer ») ;
  - `test_branche_par_defaut` : avec `branche_ref=None` et une origine sur `main`, on obtient le SHA de `main` ;
  - `test_branche_introuvable` : `ErreurDepot`, dont le message contient « branche inexistante introuvable dans le dépôt » ;
  - `test_depot_injoignable` : avec `file:///nexiste/pas`, on obtient `ErreurDepot` ;
  - `test_jeton_jamais_ecrit` : avec `jeton="SECRET123"`, après `preparer`, aucun fichier du clone nu ne contient `SECRET123`. Avec une URL injoignable, `str(exc)` ne le contient pas non plus ;
  - `test_nettoyer_garde_seulement_les_etapes_demandees`.
- [ ] **Étape 2 :** pytest échoue. **Étape 3 :** implémenter. **Étape 4 :** PASS.
- [ ] **Étape 5 : commit** `feat(portail): clones nus et arbres de travail figés par étape`.

### Task 4: outils en lecture seule et aperçu du dépôt

**Fichiers :**
- Créer : `backend/portail/outils.py`, `backend/tests/test_outils.py`

**Interfaces :**
- Produit :
  - `SCHEMAS_OUTILS: dict[str, dict]` : la définition OpenAI (`{"type": "function", "function": {...}}`) de `lister(chemin="." )`, `lire(chemin, debut?, fin?)` et `chercher(motif, chemin?)`, avec des descriptions en français.
  - `class OutilsDepot`, avec `__init__(self, racine: Path)` :
    - `lister(chemin: str = ".") -> str` ;
    - `lire(chemin: str, debut: int | None = None, fin: int | None = None) -> str` ;
    - `async chercher(motif: str, chemin: str | None = None) -> str` ;
    - `async executer(nom: str, arguments: str) -> tuple[str, bool]` : elle renvoie le texte du résultat et `True` si l'appel était **mal formé** (JSON invalide, outil inconnu, arguments manquants).

    Un refus (chemin hors de l'arbre, secret, binaire, fichier absent) n'est **pas** un appel mal formé. Il renvoie un texte qui commence par `"erreur : "` et n'interrompt jamais la boucle.
  - `def _resoudre(self, chemin: str) -> Path` : un chemin absolu, `..` qui sort de l'arbre, un chemin dont la résolution (liens symboliques compris) sort de `racine.resolve()`, ou un chemin qui contient un composant `.git`, sont refusés. Le refus lève une erreur interne, transformée en `"erreur : chemin interdit"`.
  - `chercher` lance `git grep -n -I -E --no-color -e <motif> -- <chemin|.>`, avec une exclusion `:(exclude,glob)**/<motif>` pour chaque motif de secret. On ne garde que les 100 premières lignes et on ajoute `[… <n> résultats au total]` s'il y en a plus. Si `git grep` sort avec le code 1, la réponse est `"aucun résultat"`. Avec le code 128 (motif invalide), c'est `"erreur : motif invalide : …"`.
  - `def apercu(racine: Path, budget_jetons: int) -> str` assemble, dans cet ordre :
    1. l'arborescence sur deux niveaux (avec `lister`) ;
    2. puis, s'ils existent, `README*`, `CLAUDE.md`, `AGENTS.md`, `pyproject.toml`, `package.json` et `Cargo.toml` à la racine, chacun sous un titre `### <nom>`.

    Elle arrête d'ajouter dès que `estimer_jetons([{"content": texte}])` dépasserait `budget_jetons`. Le dernier fichier est alors coupé, avec `[… tronqué]`.

- [ ] **Étape 1 : tests** dans un arbre temporaire, avec `git init` et un commit, pour que `git grep` fonctionne :
  - `test_lire_simple` ;
  - `test_lire_plage_de_lignes` : `debut=2, fin=3` ne renvoie que ces lignes ;
  - `test_lire_tronque_par_lignes` : 2500 lignes, la réponse finit par `[… tronqué : 2500 lignes au total]` ;
  - `test_lire_ligne_geante_tronquee_par_octets` : une seule ligne de 5 Mo donne une réponse de 100 000 octets au plus ;
  - un test paramétré `test_chemins_interdits` : `../x`, `/etc/passwd`, `.git/config`, `sous/../../x`, et un lien symbolique `lien -> /etc` puis `lien/passwd`. Tous donnent `"erreur : chemin interdit"` ;
  - un test paramétré `test_secrets_refuses` : `.env`, `.env.prod`, `cle.pem`, `a/b/serveur.key`, `id_rsa`. On écrit chacun des fichiers, `lire` renvoie un texte qui commence par `"erreur : "`, et `chercher` ne trouve pas son contenu ;
  - `test_binaire_refuse` ;
  - `test_lister_profondeur_et_plafond` : 400 fichiers donnent au plus 300 entrées, avec une mention, et rien au-delà de la profondeur 2 ;
  - `test_chercher_trouve_et_plafonne` ;
  - `test_chercher_motif_invalide` : `"("` donne un texte qui commence par `"erreur : motif invalide"` ;
  - `test_executer_mal_forme` : `executer("lire", "pas du json")` et `executer("ecrire", "{}")` renvoient chacun `(…, True)`. `executer("lire", '{"chemin": "../x"}')` renvoie `("erreur : chemin interdit", False)` ;
  - `test_apercu_respecte_le_budget` : avec un README de 100 000 caractères et un budget de 500, `estimer_jetons` de l'aperçu est au plus 500, et l'aperçu contient l'arborescence.
- [ ] **Étape 2 :** pytest échoue. **Étape 3 :** implémenter. **Étape 4 :** PASS.
- [ ] **Étape 5 : commit** `feat(portail): outils de lecture confinés et aperçu du dépôt`.

### Task 5: appel non streamé et boucle d'outils

**Fichiers :**
- Modifier : `backend/portail/llm.py`, `backend/portail/contexte.py`, `backend/tests/conftest.py` (le `FauxLLM` gagne `completer`)
- Créer : `backend/portail/boucle.py`, `backend/tests/test_boucle.py`

**Interfaces :**
- **Change A** : `ClientLLM` gagne `async def completer(self, modele: str, messages: list[dict], temperature: float | None, outils: list[dict] | None = None, response_format: dict | None = None) -> dict`. C'est un appel non streamé, qui renvoie `choices[0].message`. Les erreurs sont les mêmes que pour `flux` : `ErreurLLM`. `tools` et `response_format` ne sont envoyés que s'ils ne sont pas `None`.
- **Change A** : `contexte.py` gagne `def elaguer_resultats_outils(messages: list[dict], contexte_max: int) -> int`. Si `estimer_jetons(messages) >= 0.90 * contexte_max`, elle remplace le contenu des messages `role == "tool"`, du plus ancien au plus récent, par `[résultat retiré : relire si besoin]`, jusqu'à passer sous `0.75 * contexte_max` ou jusqu'à ce qu'il n'en reste plus. Elle renvoie le nombre de messages remplacés. Elle ne touche jamais un autre rôle.
- Produit, dans `boucle.py` :
  - `class ErreurOutils(Exception)` ;
  - `class ResultatBoucle(BaseModel)`, avec `texte: str` et `limite_atteinte: bool` ;
  - `async def boucle_outils(llm, agent: Agent, messages: list[dict], outils: OutilsDepot, sur_appel: Callable[[str, str], Awaitable[None]]) -> ResultatBoucle`.

  Le déroulement de la boucle, au plus `agent.tours_max` tours :
  1. On élague, puis on appelle `completer(..., outils=[SCHEMAS_OUTILS[n] for n in agent.outils])`.
  2. Si la réponse contient des `tool_calls`, on ajoute le message assistant à `messages`, puis on traite chaque appel :
     - on lance `outils.executer` ;
     - on ajoute `{"role": "tool", "tool_call_id": id, "content": resultat}` ;
     - on appelle `await sur_appel(libelle, resultat)`, où `libelle` vaut `nom(<valeurs des arguments, jointes par ", ">)`. Si les arguments ne sont pas lisibles, `libelle` vaut le nom de l'outil.
  3. Un compteur des appels mal formés **consécutifs** est remis à 0 dès qu'un appel est bien formé. Arrivé à 3, la boucle lève `ErreurOutils("le modèle <modele> ne gère pas correctement les outils")`.
  4. Si la réponse ne contient pas de `tool_calls`, on renvoie `ResultatBoucle(texte=retirer_reflexion(content), limite_atteinte=False)`.
  5. Une fois `tours_max` atteint, on ajoute `{"role": "user", "content": "Limite d'outils atteinte : conclus maintenant avec ce que tu as, sans appeler d'outil."}`, on fait un dernier appel **sans** outils, et on renvoie `limite_atteinte=True`.

- [ ] **Étape 1 : tests** avec le `FauxLLM`, dont on règle à l'avance la suite des réponses de `completer` :
  - `test_completer_envoie_tools_et_lit_le_message`, avec `httpx.MockTransport` : vérifier le corps envoyé (`tools`, `stream` absent ou faux) et le `dict` renvoyé ;
  - `test_boucle_execute_les_outils_puis_repond` : un appel à `lire(README.md)`, puis un texte final. Le message `tool` contient le contenu du README, `sur_appel` est appelé une fois avec `"lire(README.md)"`, et le texte est retourné ;
  - `test_boucle_limite_tours` : avec `tours_max=2`, le faux modèle appelle toujours un outil. On obtient `limite_atteinte is True`, le dernier appel est fait sans `tools`, et le dernier message `user` est la consigne exacte ci-dessus ;
  - `test_trois_appels_mal_formes_echouent` : trois `tool_calls` avec `arguments: "{{"` lèvent `ErreurOutils` ;
  - `test_mal_forme_puis_bien_forme_remet_a_zero` : la séquence mal formé, mal formé, correct, mal formé, mal formé, puis un texte final ne lève rien ;
  - `test_elagage` : avec `contexte_max=1000` et trois messages `tool` de 1200 caractères chacun, on obtient au moins un remplacement, le plus ancien en premier, et les messages `user` et `system` sont intacts.
- [ ] **Étape 2 :** pytest échoue. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): appel non streamé et boucle d'outils en lecture seule`.

### Task 6: moteur, démarrage automatique et pipeline de planification

**Fichiers :**
- Modifier : `backend/portail/moteur.py`, `backend/tests/test_moteur.py`, `backend/portail/contexte.py`, `backend/tests/test_contexte.py`

**Interfaces :**
- **Change A**, avec leurs appelants dans `api.py` et `chat.py` à mettre à jour :
  - `demarrer_etape(session, catalogue, etape) -> bool`. Si l'agent est `auto`, l'étape passe à `en_cours` avec `action = "taches"` si `produit == "taches"`, sinon `action = "rediger"`, et la fonction renvoie `True` : l'appelant doit lancer la tâche de fond **après** le commit. Sinon, l'étape passe à `en_attente` et la fonction renvoie `False`.
  - `terminer_etape(session, catalogue, etape) -> Etape | None` : elle renvoie l'étape suivante si celle-ci doit être lancée.
  - `creer_pipeline(session, catalogue, projet_id, type_) -> tuple[Pipeline, Etape | None]` : elle renvoie aussi l'étape à lancer. Pour le type `planification`, elle lève :
    - `Refus(409, "aucune spec validée pour ce projet")` s'il n'y a pas de spec courante ;
    - `Refus(409, "une planification est déjà en cours pour ce projet")` si un autre pipeline `planification` du projet n'est ni `terminee` ni `echouee`.
  - Nouvelle fonction : `annuler_pipeline(session, pipeline) -> None`. L'étape active (`en_cours` ou `en_attente`) passe à `echouee` avec l'erreur « annulé », et les `Proposition` `ouverte` du pipeline passent à `rejetee`. Elle lève `Refus(409, "pipeline déjà terminé")` si le pipeline est `terminee` ou `echouee`.
- **Change A** : `construire(agent, messages, document, consigne=None, annexes: list[str] = [])`. Les annexes sont insérées comme messages `system`, dans l'ordre, juste après le prompt système et avant le brouillon. Seuls les messages de rôle `user` et `assistant` sont repris de l'historique. Les messages `tool` et `system` enregistrés servent au suivi seulement et ne sont **jamais** renvoyés au modèle.

- [ ] **Étape 1 : tests**
  - `test_etape_auto_demarre_en_cours`, avec un catalogue de tests qui contient le type `planification: [plan, taches]` : `creer_pipeline` donne une étape 0 `en_cours` avec l'action `rediger`, et renvoie cette étape ;
  - `test_terminer_lance_l_etape_taches` : après `terminer_etape`, l'étape 1 est `en_cours` avec l'action `taches`, et c'est elle qui est renvoyée ;
  - `test_planification_sans_spec_409` ;
  - `test_une_seule_planification_active_409` ;
  - `test_planification_possible_apres_echec` ;
  - `test_annuler_rejette_les_propositions` ;
  - `test_annexes_et_messages_tool_ignores` dans `test_contexte.py` : avec les annexes `["A1", "A2"]` et l'historique `[user, tool, assistant]`, on obtient `[system, system A1, system A2, user, assistant]`.
- [ ] **Étape 2 :** pytest échoue. **Étape 3 :** implémenter, et ajuster les appelants de A. Les tests de A doivent rester verts. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): démarrage automatique des étapes et pipeline de planification`.

### Task 7: exécution des étapes avec dépôt, outils et plan

**Fichiers :**
- Modifier : `backend/portail/chat.py`, `backend/portail/api.py`, `backend/tests/conftest.py` (une fixture `depot_origine` : un dépôt local avec un commit et un README, comme à la tâche 3)
- Créer : `backend/tests/test_etapes_depot.py`

**Interfaces :**
- Consomme : `Depots`, `OutilsDepot`, `apercu`, `boucle_outils`, `construire(..., annexes)`, le nouveau `demarrer_etape` / `terminer_etape` / `creer_pipeline`.
- **Change A** :
  - `ServiceChat.__init__(sessions, catalogue, llm, diffuseur, depots: Depots)` ;
  - `create_app` construit `Depots(reglages.donnees_dir, reglages.github_jeton)`. Au démarrage, après `recuperer_interrompues`, elle appelle `depots.nettoyer(garder={ids des étapes en_attente})`.
- `ServiceChat.lancer(etape_id: int) -> None` : elle lance la tâche de fond d'une étape déjà mise `en_cours`. Les routes `POST /api/pipelines` et `POST /api/etapes/{id}/valider` l'appellent avec l'étape renvoyée par le moteur.
- `POST /api/pipelines/{id}/annuler` : elle annule la tâche asyncio en cours de l'étape, s'il y en a une, appelle `annuler_pipeline` puis `depots.liberer`, et renvoie le détail du pipeline.
- Dans la tâche de fond, une fois l'agent et le projet connus :
  1. **Dépôt** : si le projet a un `depot_url` et que l'agent a des `outils`, on appelle `depots.preparer(..., sha=etape.sha)`, puis on enregistre `etape.sha`. À la première préparation, on enregistre aussi `etape.apercu = apercu(arbre, int(0.25 * agent.contexte_max))`. Une `ErreurDepot` fait échouer l'étape avec `"dépôt : " + message`.
  2. **Annexes**, dans cet ordre :
     - pour `produit == "plan"` : `"Spec courante :\n\n" + spec`, puis, s'il existe un plan validé du projet, `"Plan validé précédent (à réviser) :\n\n" + plan` ;
     - pour `produit == "taches"` : voir la tâche 9 ;
     - puis, si `etape.apercu` existe : `"Aperçu du dépôt (SHA <sha>) :\n\n" + apercu`.
  3. **Exécution** :
     - si l'agent a des outils et le projet un dépôt, on passe par `boucle_outils`. `sur_appel` enregistre un `Message(role="tool", outil=libelle, contenu=resultat[:2000])` et publie `{"type": "outil", "libelle": libelle}`. À la fin, on publie le texte en une fois, avec `{"type": "delta", "texte": ...}`. Si `limite_atteinte`, on enregistre en plus un message `system` : « limite de <tours_max> appels d'outils atteinte : la réponse peut être incomplète ». Une `ErreurOutils` fait échouer l'étape avec son message ;
     - sinon, on garde le chemin streamé de A.
  4. **Résultat** : en `rediger`, on enregistre le `Document` avec `type = agent.produit` (et non plus le type de pipeline, comme en A).
  5. **Libération** : quand l'étape finit `echouee`, puis après `valider`, on appelle `depots.liberer(etape_id)`.
- Le jauge du `GET /api/pipelines/{id}` inclut les annexes.

- [ ] **Étape 1 : tests**, avec `FauxLLM` et `depot_origine`. Le projet est créé avec `depot_url = file://…`, en contournant la validation de l'URL par une écriture directe en base dans la fixture :
  - `test_plan_demarre_seul_et_lit_le_depot` : on valide une spec, puis on fait `POST /api/pipelines {"type": "planification"}` ; on attend la tâche de fond. Le faux modèle a reçu une annexe « Spec courante » et un « Aperçu du dépôt (SHA <sha>) ». Il a appelé `lire(README.md)`, puis répondu `"# Plan"`. On obtient un document `plan` en `brouillon`, `etape.sha` égal au SHA de l'origine, un message `tool` avec `outil == "lire(README.md)"`, et une étape `en_attente` ;
  - `test_plan_revise_le_plan_precedent` : la deuxième planification reçoit l'annexe « Plan validé précédent » ;
  - `test_sha_fige_entre_deux_redactions` : après un commit sur l'origine et un nouveau `rediger`, `etape.sha` n'a pas changé et l'aperçu non plus ;
  - `test_depot_injoignable_echoue_proprement` : l'étape passe à `echouee`, avec une erreur qui commence par `"dépôt : "` ;
  - `test_outils_mal_geres_echoue` ;
  - `test_spec_sans_depot_reste_streamee` : un projet sans dépôt passe par `flux`, et `completer` n'est pas appelé ;
  - `test_annuler_pipeline_en_cours` : avec le faux modèle bloqué, `annuler` donne une étape `echouee` « annulé » et un arbre supprimé ;
  - `test_redemarrage_nettoie_les_arbres` : un arbre d'une étape `terminee` laissé sur le disque est supprimé au démarrage.
- [ ] **Étape 2 :** pytest échoue. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): étapes qui lisent le dépôt, agent de plan`.

### Task 8: tâches et kanban (API)

**Fichiers :**
- Créer : `backend/portail/taches.py`, `backend/tests/test_taches.py`
- Modifier : `backend/portail/api.py`, `backend/portail/schemas.py`

**Interfaces :**
- Produit, dans `taches.py` (fonctions `async` qui prennent une session ; l'appelant fait le commit) :
  - `creer_tache(session, projet_id, donnees: DonneesTache, auteur: str, origine="manuel", document_id=None, protegee=True) -> Tache` : la tâche est ajoutée en fin de colonne `a_faire`.
  - `modifier_tache(session, tache, donnees: DonneesTachePartielles, auteur) -> Tache` : `version += 1`. `protegee` passe à `True` si `auteur == "nicolas"`.
  - `deplacer_tache(session, tache, colonne: str, avant_id: int | None, auteur) -> None` : elle insère la tâche avant `avant_id`, ou en fin de colonne, puis renumérote toute la colonne. Elle ne touche **ni** `protegee` **ni** `version`.
  - `supprimer_tache(session, tache, auteur) -> None` : le journal garde une copie complète de la tâche.
  - `definir_dependances(session, tache, ids: list[int]) -> None` : elle refuse avec `Refus(422, "cycle de dépendances")` en cas de cycle (parcours en profondeur), et avec `Refus(422, "dépendance hors projet ou inconnue")` pour un id d'un autre projet ou inconnu.
  - `verifier_modifiable(tache) -> None` : si `tache.verrou` est posé, elle lève `Refus(409, "tâche verrouillée par le pipeline <verrou>")`. Toutes les fonctions qui modifient ou suppriment une tâche l'appellent.
  - Chaque opération écrit un `TacheEvenement`.
  - `DonneesTache` (Pydantic) : `titre` (1 à 200 caractères après nettoyage des espaces), `description=""`, `criteres: list[str] = []`, `fichiers: list[str] = []`, `depend_de: list[int] = []`. `DonneesTachePartielles` a les mêmes champs, tous optionnels.
- Routes :
  - `GET /api/projets/{id}/kanban` renvoie `{"taches": [TacheVue], "propositions": [PropositionVue ouvertes]}`. `TacheVue` contient tous les champs de la tâche, plus `depend_de: list[int]` et `dependances_non_terminees: list[int]`. Les tâches sont triées par colonne puis par rang ;
  - `POST /api/projets/{id}/taches` renvoie `201` ;
  - `PATCH /api/taches/{id}` ;
  - `POST /api/taches/{id}/deplacer {colonne, avant_id?}` : une colonne inconnue donne `422` ;
  - `DELETE /api/taches/{id}` renvoie `204` ;
  - `POST /api/taches/{id}/annuler` : sans verrou, `409` « rien à annuler ». Avec un verrou, elle annule ce pipeline (comme `POST /api/pipelines/{id}/annuler`), lève le verrou et remet la tâche dans `a_faire`. C chargera plus tard ce comportement.

- [ ] **Étape 1 : tests**
  - `test_creer_tache_manuelle_protegee` : `protegee`, `origine == "manuel"`, colonne `a_faire`, et un événement `creation` par `nicolas` ;
  - `test_modifier_contenu_protege_et_versionne` : sur une tâche d'agent (créée directement avec `protegee=False`), un `PATCH` du titre donne `protegee`, et `version` vaut 2 ;
  - `test_deplacer_ne_protege_pas` : sur une tâche d'agent, déplacer et réordonner laissent `protegee` à faux et `version` à 1 ;
  - `test_rangs_contigus` : trois tâches, on déplace la troisième avant la première ; l'ordre et les rangs valent `[1000, 2000, 3000]` ;
  - `test_deplacements_concurrents` : deux `deplacer` lancés en même temps (`asyncio.gather`, deux sessions) sur la même colonne laissent des rangs distincts et contigus. La renumérotation verrouille les lignes de la colonne avec `SELECT … FOR UPDATE`, triées par id ;
  - `test_cycle_refuse` : avec `A → B`, définir `B → A` donne `422` ;
  - `test_dependance_autre_projet_refusee` ;
  - `test_verrou_409` : avec un `verrou` posé directement en base, `PATCH`, `deplacer` et `DELETE` donnent `409`, avec « verrouillée par le pipeline » ; `GET kanban` affiche la tâche ;
  - `test_supprimer_garde_le_journal` : l'événement `suppression` contient le titre ;
  - `test_dependances_non_terminees` : la carte signale une dépendance qui est dans `a_faire`, mais le déplacement vers `prete` est accepté.
- [ ] **Étape 2 :** pytest échoue. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): tâches, dépendances et journal du kanban`.

### Task 9: étape de tâches et propositions

**Fichiers :**
- Créer : `backend/portail/propositions.py`, `backend/tests/test_propositions.py`
- Modifier : `backend/portail/chat.py` (action `taches`), `backend/portail/api.py`

**Interfaces :**
- Produit :
  - `SCHEMA_PROPOSITIONS` est envoyé tel quel en `response_format={"type": "json_schema", "json_schema": {"name": "propositions", "schema": …}}`. Sa forme :
    `{"propositions": [ {"sorte": "nouvelle", "cle": str, "titre", "description", "criteres": [str], "fichiers": [str], "depend_de": [str]} | {"sorte": "modification", "tache_id": int, "titre", "description", "criteres", "fichiers", "depend_de"} | {"sorte": "retrait", "tache_id": int, "raison": str} ]}`.

    Dans `depend_de`, chaque élément est soit la `cle` d'une autre proposition `nouvelle` de la même réponse, soit `"T<id>"` pour une tâche existante du projet.
  - `def lire_propositions(texte: str, cles_existantes: set[int]) -> list[PropositionLue]` : elle valide avec Pydantic. Elle lève `ValueError` avec un message utilisable pour :
    - un JSON invalide ;
    - des clés en double ;
    - une `depend_de` inconnue ou qui cite sa propre clé ;
    - un `"T<id>"` qui n'est pas dans `cles_existantes`.
  - `async def enregistrer_propositions(session, etape, lues, auteur) -> list[str]`. Les propositions `modification` et `retrait` qui visent une tâche hors de `a_faire` ou `prete`, protégée, verrouillée ou d'un autre projet sont **écartées**. La fonction renvoie la liste des refus, sous la forme `"T<id> : <raison>"`. Les propositions gardées sont enregistrées `ouverte`, avec `version_tache = tache.version`.
  - `async def accepter(session, proposition, donnees_modifiees: DonneesTache | None) -> None` :
    - `nouvelle` : `creer_tache(origine="agent", document_id=<plan validé du pipeline>, protegee=donnees_modifiees is not None, auteur="nicolas" si modifiée, sinon "agent:taches")` ;
    - pour les dépendances : on résout `depend_de`. Une clé se résout par le `tache_creee_id` d'une proposition déjà acceptée ; une clé encore ouverte ou rejetée est ignorée. Ensuite, pour chaque autre proposition déjà acceptée du même pipeline dont `depend_de` contient cette `cle`, on ajoute la dépendance inverse ;
    - `modification` : si `tache.version != version_tache`, ou si la tâche est protégée, verrouillée, ou n'est plus dans `a_faire` ou `prete`, la proposition passe à `perimee` et on lève `Refus(409, "proposition périmée : la tâche a changé depuis")`. Sinon, on fait `modifier_tache(auteur="agent:taches")` ;
    - `retrait` : mêmes vérifications, puis `supprimer_tache(auteur="agent:taches")`.
  - `async def rejeter(session, proposition) -> None`.
  - Après chaque acceptation ou rejet, s'il ne reste aucune proposition `ouverte` dans l'étape, on appelle `terminer_etape`.
- L'action `taches` dans la tâche de fond :
  1. Annexes : `"Plan validé :\n\n" + plan`, puis `"Tâches existantes (JSON) :\n\n" + <liste des tâches du projet : id, titre, colonne, protegee, verrou>`.
  2. Appel : `completer(response_format=…)`, avec `consigne_redaction`.
  3. Si `lire_propositions` lève une erreur, un **seul** nouvel appel, qui ajoute `{"role": "user", "content": "Réponse invalide : <erreur>. Renvoie uniquement le JSON corrigé."}`. Si la deuxième réponse est encore invalide, l'étape passe à `echouee` avec « propositions invalides : <erreur> ».
  4. Les refus sont enregistrés dans un message `system` « propositions écartées : … ».
  5. S'il reste au moins une proposition, l'étape passe à `en_attente` ; sinon, à `terminee`.
- Routes, qui renvoient toutes le kanban du projet :
  - `POST /api/propositions/{id}/accepter {donnees?}` ;
  - `POST /api/propositions/{id}/rejeter` ;
  - `POST /api/etapes/{id}/propositions/tout-accepter`, qui accepte dans l'ordre des ids, saute les périmées, et renvoie le nombre de périmées.

  Accepter ou rejeter une proposition qui n'est pas `ouverte` donne `409`.

- [ ] **Étape 1 : tests**
  - `test_lire_propositions`, paramétré, pour les cas invalides : JSON cassé, clé en double, `depend_de` qui vise sa propre clé, clé inconnue, `"T999"` absent ;
  - `test_etape_taches_cree_des_propositions` (le pipeline complet, avec `FauxLLM`) : après la validation du plan, l'étape `taches` démarre seule, et 2 propositions `ouverte` mènent à une étape `en_attente` ;
  - `test_reponse_invalide_relance_une_fois` : d'abord invalide puis valide donne des propositions créées, et le faux modèle a reçu « Réponse invalide » ;
  - `test_reponse_invalide_deux_fois_echoue` ;
  - `test_tout_accepter_resout_les_dependances` : avec `n1` et `n2` (`n2` dépend de `n1`), deux tâches sont dans `a_faire`, `n2` dépend de `n1`, et l'étape et le pipeline sont `terminee` ;
  - `test_accepter_dans_le_desordre_relie_quand_meme` : on accepte `n2` avant `n1`, et la dépendance existe à la fin ;
  - `test_modifier_puis_accepter_protege` ;
  - `test_proposition_sur_tache_protegee_ecartee` : une modification visant une tâche protégée n'est pas enregistrée, et le message `system` la cite ;
  - `test_proposition_perimee` : on accepte une modification après un `PATCH` de Nicolas sur la tâche ; on obtient `409` « périmée », l'état `perimee`, et la tâche garde le titre donné par Nicolas ;
  - `test_retrait_accepte_supprime_et_journalise` ;
  - `test_aucune_proposition_termine_l_etape`.
- [ ] **Étape 2 :** pytest échoue. **Étape 3 :** implémenter. **Étape 4 :** PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): étape de tâches et propositions à accepter ou rejeter`.

### Task 10: interface, projet avec dépôt, planification et suivi des outils

**Fichiers :**
- Modifier : `frontend/src/api.ts`, `frontend/src/flux.ts`, `frontend/src/flux.test.ts`, `frontend/src/views/ProjetsView.vue`, `frontend/src/views/ProjetView.vue`, `frontend/src/views/PipelineView.vue`, `frontend/src/components/ChatEtape.vue`, `frontend/src/components/EditeurDocument.vue`

**Interfaces :**
- **Change A** :
  - `api.ts` gagne `modifierProjet`, `annulerPipeline`, les champs `depot_url` et `branche_ref`, `Message.outil` et `Etape.sha` ;
  - `ecouterFlux` gagne le rappel `outil(libelle: string)`.
- `ProjetsView` et `ProjetView` : un formulaire avec « Dépôt GitHub (URL) » et « Branche de référence (vide = branche par défaut) ». Le bouton « Lancer la planification » n'est actif que s'il y a une `spec_courante`. Un `409` affiche son `detail`. Un lien « Kanban » mène à `/projets/:id/kanban`.
- `ChatEtape` :
  - les messages `tool` s'affichent repliés (`<details><summary>🔎 {{outil}}</summary><pre>{{contenu}}</pre></details>`), et les messages `system` en italique gris ;
  - pendant une réponse, chaque événement `outil` ajoute une ligne « 🔎 libellé » sous la bulle provisoire ;
  - l'en-tête de l'étape affiche `SHA <7 premiers caractères>` si `sha` est défini ;
  - pour une étape dont l'agent produit `taches` : à la place du chat, « N propositions à traiter », avec un lien vers le kanban.
- `EditeurDocument` affiche le type (« Spec » ou « Plan ») dans son titre.
- `PipelineView` : un bouton « Annuler le pipeline » quand l'état n'est ni `terminee` ni `echouee`, avec une confirmation `confirm()`.

- [ ] **Étape 1 : test** dans `flux.test.ts` : un événement `outil` appelle `outil("lire(README.md)")`.
- [ ] **Étape 2 :** `npm test` échoue. **Étape 3 :** implémenter. **Étape 4 :** `npm test` et `npm run build` donnent PASS.
- [ ] **Étape 5 : commit** `feat(portail): interface de planification et suivi des appels d'outils`.

### Task 11: interface, kanban et propositions

**Fichiers :**
- Créer : `frontend/src/views/KanbanView.vue`, `frontend/src/components/CarteTache.vue`, `frontend/src/components/EditionTache.vue`, `frontend/src/components/PanneauPropositions.vue`, `frontend/src/kanban.ts`, `frontend/src/kanban.test.ts`
- Modifier : `frontend/src/router.ts`, `frontend/src/api.ts`

**Interfaces :**
- `api.ts` gagne : `lireKanban`, `creerTache`, `modifierTache`, `deplacerTache`, `supprimerTache`, `annulerTache`, `accepterProposition`, `rejeterProposition` et `toutAccepter`, ainsi que les types `Tache` et `Proposition`.
- `kanban.ts`, des fonctions pures :
  - `COLONNES` : la liste ordonnée des `{valeur, libelle}` des contraintes globales ;
  - `grouperParColonne(taches): Record<string, Tache[]>`, triées par rang ;
  - `filtrer(taches, texte): Tache[]` : une recherche sans tenir compte de la casse ni des accents, dans le titre et la description (`normalize("NFD")`).
- `KanbanView` (route `/projets/:id/kanban`) :
  - six colonnes, rafraîchies toutes les **5 s** ; le sondage est suspendu pendant un glissement ;
  - le glisser-déposer est natif (`draggable`, `dragover`, `drop`). On calcule `avant_id` à partir de la carte survolée, on appelle `deplacerTache`, puis on recharge ;
  - un champ de filtre ;
  - un bouton « Nouvelle tâche ».
- `CarteTache` affiche :
  - le titre ;
  - le badge « 🔒 verrouillée (pipeline N) » quand il y a un verrou ;
  - le badge « ✋ protégée » ;
  - « ⚠ dépend de #id non terminée » pour chaque `dependances_non_terminees` ;
  - un `<select>` « Déplacer vers… », pour le clavier et l'accessibilité.

  Une carte verrouillée n'est pas `draggable`, et elle n'affiche que « Annuler » comme action.
- `EditionTache` (une modale) : titre, description (markdown, avec aperçu par `rendreMarkdown`), critères (une ligne par critère), fichiers, et les dépendances en cases à cocher parmi les autres tâches du projet. Elle affiche aussi « Supprimer », avec une confirmation. Un `422` ou un `409` affiche son `detail`.
- `PanneauPropositions` : une carte par proposition ouverte.
  - `nouvelle` : le contenu, avec « Accepter », « Modifier puis accepter » (qui ouvre `EditionTache`, pré-remplie) et « Rejeter » ;
  - `modification` : un affichage avant/après, champ par champ ;
  - `retrait` : la raison.

  Le panneau propose aussi « Tout accepter », qui affiche le nombre de propositions périmées s'il y en a.

- [ ] **Étape 1 : tests** dans `kanban.test.ts` :
  - `grouperParColonne` donne les six clés, même vides, avec les tâches dans l'ordre des rangs ;
  - `filtrer(taches, "etape")` trouve « Étape 2 ».
- [ ] **Étape 2 :** `npm test` échoue. **Étape 3 :** implémenter. **Étape 4 :** `npm test` et `npm run build` donnent PASS.
- [ ] **Étape 5 : vérification manuelle**, en local, sur un dépôt public (par exemple `https://github.com/nicolaslallier/Glee`, s'il est public ; sinon un jeton en lecture seule dans `PORTAIL_GITHUB_JETON`). Le parcours :
  1. spec validée ;
  2. planification : on voit les appels d'outils, puis le plan est validé ;
  3. propositions, et « Tout accepter » ;
  4. on glisse une carte vers « Prête », on modifie une carte (elle devient « protégée »), et on relance une planification : aucune proposition ne touche la carte protégée.

  Si LiteLLM n'est pas accessible, on le note comme non vérifié.
- [ ] **Étape 6 : commit** `feat(portail): kanban éditable et panneau des propositions`.

### Task 12: image et déploiement pour B

**Fichiers :**
- Modifier : `Dockerfile`, `deploy/portainer-stack.yml`, `README.md`

**Interfaces :**
- L'étape Python de l'image installe `git` (`apt-get install -y --no-install-recommends git`, puis on vide le cache apt).
- Dans `deploy/portainer-stack.yml`, le service `portail` gagne :
  - le volume nommé `portail-donnees`, monté sur `/donnees` et accessible en écriture par l'utilisateur non root de l'image (créer `/donnees` avec ce propriétaire dans le `Dockerfile`) ;
  - les variables `PORTAIL_DONNEES_DIR=/donnees` et `PORTAIL_GITHUB_JETON=${PORTAIL_GITHUB_JETON:-}`.
- Dans le README, une section « Jeton GitHub (lecture seule) » : un jeton à grain fin, limité aux dépôts choisis, avec les permissions **Contents : Read** et **Metadata : Read** seulement, et sans aucune permission d'écriture. Il se configure dans les variables de la pile Portainer et ne va jamais dans le dépôt.

- [ ] **Étape 1 :** `docker build -t portail:local .` réussit. `docker run --rm --entrypoint git portail:local --version` affiche une version. `docker run --rm --entrypoint sh portail:local -c 'touch /donnees/x'` réussit.
- [ ] **Étape 2 :** `docker compose -f deploy/portainer-stack.yml config` est valide (avec des valeurs fictives pour les variables obligatoires).
- [ ] **Étape 3 : commit** `feat(portail): git et volume de données dans l'image et la pile`.

*Aucune tâche dans le dépôt Infra :* la pile du portail vit dans ce dépôt, le jeton se règle dans Portainer, et le conteneur sort déjà vers GitHub par `infra-net`. Si ce n'est pas le cas, une PR Infra s'ajoutera, sur le même modèle que la tâche 12 du plan de A.
