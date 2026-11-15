# Portail d'orchestration IA — F à I : sécurité, monitoring, bureau des agents, agents en conteneurs : design

Date : 2026-11-14 · Statut : approuvée par Nicolas le 2026-11-14
S'appuie sur : socle, B, C1, C2 et E, **construits et fusionnés dans `main`** (commit `82529fc`).
D (agents transversaux) a sa spec et son plan mais n'est pas construit ; rien ici n'en dépend.

Ce document couvre quatre lots. Chacun se planifie et se livre seul, dans l'ordre F, G, H, I.

| Lot | Sujet | Dépend de |
|-----|-------|-----------|
| F | Sécurité et confidentialité | — |
| G | Monitoring complet et tableaux de bord | — |
| H | Bureau des agents | G (table d'usage) |
| I | Un conteneur par agent, en Rust | F, G |

## Intention

Le portail a été construit en une journée, lot par lot. Le code est testé, mais ce qui l'entoure est
mince : le déploiement n'attend pas la CI, rien ne mesure ce que font les agents, et Nicolas ne voit
pas d'un coup d'œil qui travaille sur quoi. Nicolas veut :

1. un **haut niveau de sécurité et de confidentialité** ;
2. un **monitoring complet** de l'application, avec des tableaux de bord ;
3. un **bureau des agents** : un schéma vivant où chaque agent a son poste ;
4. **un conteneur par agent**, pour pouvoir écrire du code Rust sur mesure dans chaque agent.

## Objectifs

- **F** : la chaîne de livraison, les conteneurs et les données du portail résistent à une dépendance
  compromise, à un agent manipulé par le contenu qu'il lit, et à une fuite par les journaux.
- **G** : Nicolas voit dans Grafana la santé du portail, l'avancement de la boucle de dev, la
  consommation de chaque agent et l'activité du lanceur ; il est prévenu par ntfy quand ça casse.
- **H** : une page « Bureau » du portail montre en direct l'état de chaque agent.
- **I** : chaque agent tourne dans son conteneur, écrit en Rust, et peut porter du code propre à lui,
  sans que le portail perde le contrôle de ce que l'agent a le droit de faire.

## Non-objectifs

- Pas de multi-utilisateur : le portail reste à l'usage de Nicolas seul.
- Pas de traces distribuées (OpenTelemetry vers Tempo) dans G. Les journaux portent un identifiant de
  mission qui permet de suivre un travail de bout en bout. *(Choix de Claude : à ajouter si les
  journaux ne suffisent pas.)*
- Pas de conservation automatique limitée des conversations : elles restent jusqu'à ce que Nicolas
  les supprime. *(Choix de Claude.)*
- Pas de chiffrement des données dans la base du portail : la protection vient du réseau, de
  l'authentification et des sauvegardes chiffrées.
- Pas de réécriture du portail en Rust : seuls les agents changent de langage.
- Pas de conteneur jetable par mission d'agent en I (voir Approches).
- Pas de refonte de `dev.py` ni de `api.py`, ni de construction de D : ce sont d'autres chantiers.

## Anti-objectifs

- Un contenu de prompt, de spec, de code ou de conversation qui se retrouve dans un journal, une
  métrique, une étiquette Prometheus ou une notification ntfy.
- Un appel vers un modèle hébergé hors de la maison.
- Un agent qui applique lui-même ses propres limites : c'est toujours le portail qui autorise.
- Un agent en conteneur qui voit la base, le socket Docker, le dépôt cloné ou le reste du réseau de
  l'Infra.
- Un tableau de bord ou un schéma tenu à la main, qui ment dès que `agents.yaml` change.
- Une migration des agents en bloc : chaque agent migre seul et peut revenir en arrière.

## Contraintes

- Celles des lots précédents : français partout, Portainer, OpenBao, `infra-net`, oauth2-proxy.
- L'Infra fournit déjà Prometheus, Loki, Tempo, Alloy, cAdvisor et Grafana (provisionnement par
  fichiers : `monitoring/grafana/provisioning/{dashboards,alerting,datasources}`). Alloy ramasse déjà
  les journaux de tous les conteneurs Docker vers Loki. Les cibles Prometheus sont statiques
  (`monitoring/prometheus/prometheus.yml`).
- Tout changement côté Infra passe par une PR séparée sur le dépôt Infra, comme pour le vhost NGINX :
  le fichier source vit dans ce dépôt (`deploy/`), la copie dans Infra.
- Tous les modèles de LiteLLM sont locaux (Ollama) aujourd'hui. LiteLLM a une base, donc sait
  émettre des clés limitées à certains modèles.
- Le dépôt est **public** et un runner auto-hébergé (`ai`) y est attaché.
- L'Infra épingle ses images par digest avec Renovate (`docker:pinDigests`).

## Approches envisagées

### Pour I — où tourne un agent

1. **Services permanents, outils et modèle servis par le portail** *(retenue)*. Un conteneur par
   agent, toujours en marche, sur un réseau interne où il ne voit que le portail. Il reçoit une
   mission, raisonne, et demande au portail chaque appel au modèle et chaque outil. Simple à
   surveiller, aucun secret dans l'agent hormis le sien, aucun usage de plus du socket Docker. Le
   portail reste un point de passage obligé, donc une panne du portail arrête tout — c'est déjà vrai.
2. **Conteneur jetable par mission, démarré par le lanceur.** Meilleure isolation entre deux missions,
   mais un démarrage à chaque mission, un usage élargi du socket Docker, et un bureau où les postes
   apparaissent et disparaissent. Écarté pour l'instant ; le contrat de l'approche 1 ne l'empêche pas
   plus tard.
3. **Agents autonomes** : chaque agent clone le dépôt, appelle LiteLLM et exécute ses outils lui-même.
   Écarté : les protections de chemin (`protections.py`) passeraient du côté de l'agent, ce qui est
   l'anti-objectif principal.

### Pour G — d'où viennent les chiffres

1. **Une table d'usage dans la base du portail + un point `/metrics`** *(retenue)*. La table sert aussi
   le bureau (H) et survit aux redémarrages ; `/metrics` sert Prometheus.
2. Tout tirer de LiteLLM (ses propres métriques). Écarté : LiteLLM ne connaît ni l'agent, ni la tâche,
   ni le pipeline.

### Pour H — la forme du bureau

Une page du portail, alimentée par le flux d'événements existant *(retenue)*. Un panneau Grafana ne
permet pas de cliquer vers la tâche ; un schéma statique ne dit pas qui travaille.

## Ce qui est décidé

Sauf mention « Nicolas », chaque décision est un choix de Claude, à corriger à la lecture.

### F — Sécurité et confidentialité

**Chaîne de livraison**
- `main` est protégée et exige les trois jobs de `ci.yml` ; le job `deploy` ne part que si la CI du
  même commit est verte (aujourd'hui `deploy.yml` n'attend rien).
- Toutes les actions GitHub sont épinglées par SHA de commit (seul le job `deploy` l'est).
- Les images de base des trois Dockerfile et les images de `LANCEUR_IMAGES` et
  `LANCEUR_IMAGES_SERVICES` sont épinglées par digest (`nom:tag@sha256:…`). Les projets continuent
  de nommer leurs images par `nom:tag` dans leur configuration d'exécution : le lanceur fait
  correspondre ce nom à l'entrée épinglée et démarre le digest. Pour `ai-execution`, le digest est
  celui que le déploiement vient de construire.
- Renovate tient à jour digests, actions, `uv.lock`, `package-lock.json` et `Cargo.lock`, avec la même
  configuration de base que l'Infra. Pas de fusion automatique.
- La CI gagne trois contrôles bloquants : audit des dépendances (Python, npm, cargo), analyse des
  trois images construites, détection de secrets dans le dépôt.

**Conteneurs**
- `portail` et `lanceur` : système de fichiers racine en lecture seule (avec `tmpfs` où il faut),
  `cap_drop: ALL`, `no-new-privileges`. `lanceur` garde le socket Docker, rien d'autre.
- Les conteneurs que le lanceur démarre sont déjà durcis (`cap_drop: ALL`, `no-new-privileges`,
  limites de mémoire, de CPU et de processus) : ils restent tels quels. Pas de racine en lecture
  seule pour eux, les commandes d'installation des projets en ont besoin. Les conteneurs de service
  (postgres, minio) gardent leurs cinq capacités de démarrage.
- **Journaux des conteneurs d'exécution.** Aujourd'hui Alloy ramasse tous les conteneurs sans filtre :
  la sortie des tests et des installations, donc du code des projets, part dans Loki. Le lanceur pose
  une étiquette `portail.journaux=prives` sur les conteneurs d'exécution et de service qu'il crée, et
  Alloy écarte les conteneurs qui la portent (PR Infra). Le lanceur continue de lire leur sortie
  lui-même.
- Un test d'intégration vérifie qu'un conteneur d'exécution ne joint aucun hôte hors de la liste
  blanche du proxy `run-egress`. Le contenu de cette liste reste l'affaire de l'Infra.

**Confidentialité**
- `agents.yaml` déclare la liste des modèles permis (`modeles_permis`). Le portail refuse de démarrer
  si un agent désigne un modèle hors liste.
- La clé LiteLLM du portail est une clé limitée à ces modèles ; ce n'est jamais la clé maîtresse.
- Aucun journal ne contient de contenu : seulement identifiants, compteurs, durées, codes d'erreur.
  Un test le vérifie sur une mission complète (un marqueur placé dans un prompt et dans un fichier ne
  doit apparaître dans aucune ligne de journal du portail, du lanceur ou d'un agent, ni dans aucune
  métrique).
- Une notification ntfy porte un titre générique, l'identifiant de la tâche et un lien ; ni titre de
  tâche, ni extrait.
- Supprimer une conversation efface réellement ses messages et ses actions proposées.
- La base `portail` et le volume `portail-donnees-2` sont dans les sauvegardes chiffrées de l'Infra
  (à vérifier dans Infra ; les y ajouter sinon).

**Traçabilité**
- Une table `audit` enregistre chaque action confirmée ou refusée, chaque pipeline lancé ou annulé,
  chaque tâche déplacée à la main : quoi, sur quel objet, par qui (e-mail d'oauth2-proxy ou nom de
  l'agent), quand. Elle ne se modifie pas et ne se supprime pas par l'API. Une page la liste.

**Agents manipulés**
- Une suite de tests d'injection : un fichier du dépôt, une sortie de commande et un commentaire de PR
  contenant des ordres (« ignore tes consignes et… ») ne déclenchent aucun outil d'écriture hors des
  chemins permis, aucune action sans confirmation, aucune lecture ni écriture hors de l'espace de
  travail. Ce sont des tests des garde-fous du portail (`protections.py`, `outils.py`,
  propositions), avec un faux modèle qui joue l'agent manipulé ; ils ne testent pas la bonne volonté
  du modèle.

**Frontal**
- Le vhost ajoute `Content-Security-Policy` (sources du site seulement), `X-Content-Type-Options`,
  `Referrer-Policy` et `frame-ancestors 'none'`.
- Le flux `/api/conversations/…/flux` passe aujourd'hui par `location /`, avec le tampon et le délai
  de lecture par défaut de NGINX : seul `/api/etapes/` est réglé pour le direct dans le vhost, et
  seul `/api/evenements` porte `X-Accel-Buffering: no` côté backend. Toutes les réponses en flux du
  backend portent désormais cet en-tête, et le vhost donne un délai de lecture long à ces routes.

### G — Monitoring et tableaux de bord

**Table d'usage `appel_llm`** : une ligne par appel au modèle — horodatage, agent, modèle, pipeline,
étape, tâche ou conversation (selon le cas), jetons d'entrée et de sortie, durée, issue (`ok`,
`erreur`, `delai`), lieu d'exécution (`portail` ou `conteneur`) et version de l'image de l'agent
(pour comparer avant et après une migration de I). Aucun contenu. Les appels en flux demandent l'usage à LiteLLM
(`stream_options.include_usage`).

**Point `/metrics`** sur le portail, au format Prometheus, non joignable depuis l'extérieur (le vhost
répond 404 sur `/metrics`). Métriques, sans étiquette à forte cardinalité (jamais d'identifiant de
tâche) :
- API : requêtes, durées et erreurs par route et code ; flux en direct ouverts.
- Agents : appels au modèle, jetons, durées et erreurs par agent et modèle ; tours par mission ;
  remplissage du contexte ; appels d'outils par outil et issue.
- Boucle de dev : tâches par état ; exécutions par phase et par issue ; renvois ; causes de blocage ;
  durée d'une tâche de « prête » à « en revue » ; reprises sur commentaires.
- Lanceur : commandes lancées, durées, codes de sortie, délais dépassés. Le portail les émet à partir
  des réponses du lanceur : le lanceur reste sans port et sans `/metrics`. cAdvisor couvre déjà
  mémoire et CPU des conteneurs.
- Échéances : âge du dernier déploiement, pour alerter avant l'expiration du jeton OpenBao (32 jours).

**Journaux** : une ligne JSON par événement sur la sortie standard, avec niveau, module, et
identifiants de pipeline, d'étape, de tâche et de mission quand ils existent. Alloy les envoie déjà à
Loki.

**Quatre tableaux de bord Grafana**, en JSON dans `deploy/grafana/`, copiés dans le provisionnement de
l'Infra :
1. **Santé** : disponibilité, latence, erreurs, base, flux ouverts, mémoire et CPU des conteneurs.
2. **Boucle de dev** : tâches par état, taux d'arrivée en revue, renvois, blocages par cause, durées.
3. **Agents et modèles** : jetons et durées par agent, contexte, erreurs LiteLLM, appels d'outils.
4. **Lanceur** : commandes, durées, codes de sortie, délais dépassés.

**Alertes** par le mécanisme d'alerte Grafana de l'Infra, vers ntfy : portail injoignable 5 min ;
taux d'erreurs du modèle élevé ; tâche « en cours » au-delà de `duree_max_tache_s` ; trois échecs
d'exécution de suite ; aucun déploiement depuis 25 jours. Les règles vivent dans `deploy/grafana/`.

**Côté Infra** (une PR) : cible Prometheus `portail:8000`, tableaux de bord, règles d'alerte.

### H — Bureau des agents

Une page « Bureau », au menu du portail :

```
 ACCUEIL            PLANIFICATION            ATELIER DEV
┌──────────────┐   ┌────────┐  ┌────────┐   ┌───────┐  ┌───────┐  ┌───────┐
│orchestrateur │   │ plan   │→ │ taches │   │ tests │→ │ code  │→ │ revue │
│ ● en discus. │   │ ○ libre│  │ ○ libre│   │ ● T12 │  │ ○     │  │ ○     │
│ ctx ▓▓▓░ 61 %│   └────────┘  └────────┘   │tour 7 │  └───────┘  └───────┘
└──────────────┘   ┌────────┐               └───────┘  ┌───────┐
                   │ spec   │                          │ tri   │ ← commentaires PR
                   └────────┘                          └───────┘
```

- Les postes et leur rangement viennent de `agents.yaml` : un groupe par pipeline, dans l'ordre des
  étapes, avec une flèche entre deux étapes qui se suivent. Un agent hors pipeline (`orchestrateur`,
  `tri`) va dans un groupe à part. Aucun agent n'est codé en dur dans la page.
- Un poste montre : nom, état (`libre`, `au travail`, `en attente de Nicolas`, `en erreur`), ce sur
  quoi il travaille (tâche, étape ou conversation, avec un lien), le tour en cours, la jauge de
  contexte (composant `JaugeContexte` existant), et son activité du jour tirée de `appel_llm` (appels,
  jetons).
- Un clic ouvre le détail : modèle, outils permis, dernières missions avec leur issue et leur durée.
- Le portail expose `GET /api/bureau` ; la page se rafraîchit sur les signaux de `/api/evenements`.
- Un même agent peut avoir plusieurs travaux en cours (deux conversations) : le poste les liste.
- Après I, le poste montre aussi si le conteneur de l'agent répond et quelle version il fait tourner.
- Le même rangement produit un schéma des pipelines (Mermaid) généré depuis `agents.yaml` par une
  commande, repris dans le README ; la CI échoue s'il n'est plus à jour.

### I — Un conteneur par agent, en Rust

**Rôles.** Le portail garde la base, le kanban, les pipelines, l'exécution des outils et les
protections. L'agent garde le raisonnement : construire le contexte, choisir quoi lire, interpréter
les résultats, décider quand conclure. C'est là que vit le code sur mesure.

**Réseau et secrets.** Un réseau interne `portail-agents` relie le portail et les agents ; un agent
n'est sur aucun autre réseau et ne monte aucun volume. Chaque agent a un secret à lui (32 caractères
au moins, dans OpenBao), que le portail présente pour lui parler. L'agent ne détient ni clé LiteLLM,
ni jeton GitHub, ni secret du lanceur.

**Contrat** (version `v1`, HTTP et JSON, décrit dans `docs/` et vérifié par une suite de conformité) :
- Portail → agent, `POST /missions` : identifiant de mission, nom de l'agent, messages de départ,
  schémas des outils permis, paramètres de l'agent tirés du YAML, format de réponse attendu s'il y
  en a un (schéma JSON), et un **jeton de mission**. La réponse est un flux de lignes JSON : morceaux
  de texte au fil de l'eau, puis une ligne finale (texte complet, historique des messages, limite
  atteinte ou non) ou une erreur. Fermer la connexion annule la mission.
- Agent → portail, avec le jeton de mission :
  - `POST /interne/modele` : un appel au modèle, avec `response_format` au besoin. Le portail impose
    le modèle de l'agent, compte l'appel, l'inscrit dans `appel_llm`, relaie à LiteLLM et retire les
    blocs `<think>` de la réponse. Requête et réponse simples ; une option `flux` renvoie le texte
    au fil de l'eau, permise seulement quand aucun outil n'est offert (comme aujourd'hui, où seuls
    les agents sans outils diffusent).
  - `POST /interne/outils` : un appel d'outil. Le portail vérifie que l'outil est permis à cet agent,
    applique les protections de chemin, exécute, journalise et répond.
- Agent, `GET /sante` : version du contrat, version de l'image.
- Un jeton de mission ne vaut que pour une mission, un agent et la durée de celle-ci. Les routes
  `/interne/` ne sont pas servies par le vhost.

**Limites tenues par le portail**, quel que soit le code de l'agent : nombre d'appels au modèle par
mission (`tours_max` + 1), appels d'outils par tour (8), appels mal formés de suite (3), durée de la
mission. Au-delà, le portail refuse et la mission se termine comme aujourd'hui. L'élagage du contexte
devient l'affaire de l'agent ; le portail refuse seulement un appel qui dépasse `contexte_max`.

**Sorties structurées et relances.** L'agent reçoit le format attendu et rend sa réponse finale. Le
portail la valide comme aujourd'hui (verdict de `revue`, propositions de `taches`, tri). Si elle est
invalide, il envoie une nouvelle mission : l'historique rendu par la précédente, plus le message de
relance. La logique de relance reste donc dans `dev.py` et `chat.py`, sans refonte ; seul l'appel
« faire tourner l'agent » change de destination.

**Affichage.** Le texte affiché dans le chat est ce que l'agent émet sur `/missions` : un agent sur
mesure peut donc dire autre chose que la sortie brute du modèle. Les appels d'outils affichés sont
ceux que le portail exécute sur `/interne/outils`.

**Reprise** : un agent ne garde rien entre deux missions. Si le portail redémarre, les missions en
cours sont perdues et la reprise existante s'applique (`recuperer_interrompues`,
`reprendre_interrompues`). Si un agent tombe, la mission échoue avec une erreur claire et le
mécanisme « réessayer » existant sert.

**Code.** Un espace de travail Cargo `agents/` : une bibliothèque `agent` (serveur de missions, client
du portail, boucle de tours par défaut, journaux JSON) et un binaire par agent. Un agent sans code
sur mesure tient en quelques lignes : il appelle la boucle par défaut. La bibliothèque fournit la
suite de conformité, qui fait tourner un agent contre un faux portail ; chaque agent la passe en CI.
Une seule image `ai-agents` contient tous les binaires ; chaque service de la pile en lance un.

**Migration, un agent à la fois.** `agents.yaml` gagne un champ `service:` par agent (l'adresse de
son conteneur). Sans ce champ, l'agent tourne dans le portail comme aujourd'hui. Ordre : `revue`
(pilote, lecture seule, verdict JSON), `tri`, `plan`, `taches`, `spec`, `orchestrateur`, `tests`,
`code`. Avant chaque migration, les chiffres de G donnent la référence ; après, Nicolas compare dans
Grafana (réussite, renvois, jetons, durée, par lieu d'exécution) et décide de passer à l'agent
suivant ou de revenir en arrière. Pas de banc de tâches rejouables. Revenir en arrière, c'est retirer le champ `service:`. Quand tous ont migré et tenu
deux semaines, `boucle.py` est retirée.

## Questions ouvertes pour Nicolas

1. **Dépôt privé ?** C'est le gain de confidentialité le plus net, et il retire le risque du runner
   auto-hébergé sur un dépôt public. En contrepartie : les images GHCR deviennent privées (Portainer
   a besoin d'identifiants de registre et d'un jeton pour lire le compose), et les minutes d'Actions
   deviennent limitées. Sans réponse, F garde le dépôt public avec les garde-fous décrits.
2. **Quel code sur mesure pour quel agent ?** Le contrat de I laisse à l'agent tout le raisonnement.
   Si tu veux qu'un agent fasse autre chose (lancer un outil local dans son conteneur, garder une
   mémoire d'une mission à l'autre), le contrat doit le prévoir dès `v1`.

## Laissé au constructeur

- Étapes manuelles de Nicolas, à lister dans le plan sans les automatiser : protection de branche,
  clé LiteLLM limitée, secrets dans OpenBao, installation de Renovate.

- Le choix des outils d'audit, d'analyse d'images et de détection de secrets, et la bibliothèque de
  métriques Python.
- Les noms exacts des métriques, des tables et des colonnes ; les seuils d'alerte au-delà de ceux
  donnés ; la mise en page des tableaux de bord et de la page Bureau.
- Les limites de ressources par défaut des conteneurs.
- Le cadre HTTP des agents Rust (le lanceur en utilise déjà un : le reprendre).
- Le découpage de chaque lot en PR.
