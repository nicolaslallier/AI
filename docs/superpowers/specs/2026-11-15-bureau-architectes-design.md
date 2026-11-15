# Portail d'orchestration IA — bureau d'architectes : design

Date : 2026-11-15 · Statut : brouillon, à approuver par Nicolas
S'appuie sur : A à E (`2026-11-14-portail-*-design.md`), construits et fusionnés.

Dans ce document, « **décidé** » marque ce que Nicolas a tranché en discussion et « **proposé** »
marque un choix de Claude que Nicolas peut corriger à la lecture.

## Intention

Nicolas veut discuter d'une **vision** avec un architecte d'entreprise, puis recevoir une
**architecture complète** sans avoir à piloter chaque spécialité. L'architecte d'entreprise mène :
il clarifie la vision avec Nicolas, la fait travailler par six architectes spécialisés, tranche
leurs contradictions et remet un seul document.

Le livrable est un **document d'architecture au format TOGAF**, dont les éléments et les relations
suivent **ArchiMate 3.2**, accompagné d'un **fichier modèle** que Nicolas ouvre dans l'outil Archi
pour voir et retoucher les diagrammes. Le document porte aussi les registres de gouvernance : ADR,
dérogations et dette.

## Objectifs

1. Un pipeline `architecture` dans le portail, lancé depuis un projet.
2. Une discussion avec l'architecte d'entreprise qui aboutit à une vision écrite, validée par Nicolas.
3. Six volets rédigés à la suite, sans intervention : affaires, données, applicatif, technologique,
   sécurité, solution.
4. Un document d'architecture assemblé, validé par Nicolas.
5. Un fichier au format d'échange ArchiMate 3.2 (éléments, relations et vues), téléchargeable,
   qui s'importe dans Archi sans erreur.
6. Trois registres dans le document : ADR, dérogations, dette.
7. Les agents du bureau tournent sur des modèles Anthropic, OpenAI et Google, pour dépasser les
   32k de contexte des modèles locaux.

## Non-objectifs

- Pas de délégation libre : l'architecte d'entreprise n'appelle pas les spécialistes à la demande.
  L'ordre des étapes est fixe (**décidé** : chaîne d'étapes).
- Pas de diagrammes dessinés dans le portail. Les diagrammes se voient dans Archi (**décidé**).
- Pas de registre d'ADR, de dérogations ou de dette qui vit d'une architecture à l'autre : chaque
  document porte ses propres registres, numérotés à partir de 001 (**proposé**).
- Pas de relance d'un seul volet : pour refaire un volet, on relance un pipeline. Avant de valider,
  Nicolas peut demander des retouches à l'architecte d'entreprise sur le document assemblé (**proposé**).
- Pas d'avis du `challenger` sur la vision ou sur le document final dans cette version (**proposé**).
- Pas de lien automatique vers le pipeline `spec` ou `planification`.
- Aucun changement aux agents existants `architecte` et `securite`, qui gardent leur rôle (relire un
  plan, contrôler un diff).

## Anti-objectifs

- Un document qui a l'air TOGAF mais dont les volets se contredisent sans que ce soit dit : toute
  contradiction tranchée par l'architecte d'entreprise devient un ADR.
- Un modèle ArchiMate que Archi refuse d'ouvrir, ou dont les vues sont vides.
- Un architecte qui invente l'existant : l'état actuel ne se décrit qu'à partir de ce que Nicolas a
  dit ou de ce que l'agent a lu dans le dépôt. Sinon, il écrit « inconnu ».
- Un XML écrit à la main par un modèle : le fichier d'échange est produit par du code du portail.
- Les agents déjà en place qui passent au nuage sans que Nicolas l'ait demandé : seuls les agents du
  bureau utilisent les modèles infonuagiques.

## Contraintes

- Celles de A à E : agents décrits dans `agents.yaml`, modèles appelés par LiteLLM, tout en français.
- Les modèles doivent figurer dans `modeles_permis`. La clé `PORTAIL_LITELLM_CLE` est limitée à
  cette liste : il faut la réémettre quand la liste change (règle du README).
- Le contenu des visions, des architectures et des fichiers de dépôt lus par ces agents sort de la
  maison vers les trois fournisseurs. Nicolas l'a accepté en proposant ces modèles.
- Chaque agent de `agents.yaml` a son conteneur : une entrée dans la liste `NOMS` du catalogue
  Rust, un service `agent-<nom>` dans la pile et un secret `PORTAIL_AGENT_SECRET_<NOM>` obligatoire
  (des tests l'imposent). Les huit agents du bureau suivent cette règle (**proposé** : on ne crée
  pas d'exception).
- **Préalables hors de ce dépôt** : ajouter les trois modèles et les clés des fournisseurs dans
  LiteLLM (dépôt Infra, secrets dans OpenBao) ; créer les huit secrets d'agents dans OpenBao
  (`infra/portail`). Sans eux, la pile ne se déploie pas.

## Approches

1. **Chaîne d'étapes dans le portail (retenue, décidé).** Un pipeline en ligne, une étape par
   architecte. Elle réutilise le moteur existant et suit l'ordre naturel de TOGAF. Limite : l'ordre
   est fixe, l'architecte d'entreprise ne retourne pas voir un spécialiste.
2. **Délégation libre dans le portail.** L'architecte d'entreprise reçoit un outil « demander à un
   architecte ». Plus proche d'un vrai lead, mais demande des missions imbriquées, leur suivi et
   leurs limites, pour un résultat moins prévisible. À reconsidérer si l'ordre fixe gêne à l'usage.
3. **Agents Claude Code** (une commande et quatre fichiers d'agents). Aucun code à écrire, mais le
   document ne vit pas dans le portail à côté des specs et des plans. Écartée par Nicolas.

Pour ArchiMate, trois niveaux ont été considérés : tableaux seulement, tableaux et fichier modèle,
ou diagrammes dessinés dans le portail. Nicolas a retenu **tableaux et fichier modèle**.

## Le pipeline

```
architecture:
  1. archi-entreprise           discussion avec Nicolas → vision        Nicolas valide
  2. archi-affaires             automatique → volet affaires
  3. archi-donnees              automatique → volet données
  4. archi-applicatif           automatique → volet applicatif
  5. archi-techno               automatique → volet technologique
  6. archi-securite             automatique → volet sécurité
  7. archi-solution             automatique → volet solution
  8. archi-entreprise-synthese  automatique → document d'architecture   Nicolas valide
```

| Étape | Phase TOGAF | Couches ArchiMate | Préfixe des identifiants |
|---|---|---|---|
| 1 vision | A | Motivation, Stratégie | `mot-` |
| 2 affaires | B | Affaires | `aff-` |
| 3 données | C (données) | Objets d'affaires, objets de données | `don-` |
| 4 applicatif | C (applications) | Application | `app-` |
| 5 technologique | D | Technologie, Physique | `tec-` |
| 6 sécurité | transversale | Motivation (exigences, contraintes, évaluations) et les trois couches | `sec-` |
| 7 solution | E et F | Mise en œuvre et migration | `sol-` |
| 8 synthèse | toutes | toutes | `ent-` |

Règles du pipeline :

- **Décidé** : Nicolas valide la vision (étape 1) et le document final (étape 8).
- **Proposé** : les étapes 2 à 7 s'enchaînent sans arrêt. Le volet d'une étape est accepté dès qu'il
  est rédigé et que son bloc de modèle est valide (voir « Le modèle ArchiMate »).
- **Proposé** : chaque étape reçoit en annexe la vision validée et tous les volets des étapes
  précédentes du même pipeline, dans l'ordre.
- **Proposé** : un seul pipeline `architecture` actif par projet, comme pour `planification`.
- **Proposé** : aucune spec n'est requise pour lancer le pipeline. Si le projet a un dépôt, les
  agents le lisent avec `lister`, `lire`, `chercher`.
- **Proposé** : l'aperçu du dépôt joint à chaque étape garde sa taille d'aujourd'hui (environ 8k
  jetons) au lieu de suivre le quart du contexte du modèle, pour ne pas envoyer tout le dépôt huit
  fois à trois fournisseurs. L'agent lit le reste avec ses outils s'il en a besoin.
- Une étape qui échoue (modèle injoignable, bloc de modèle invalide) passe à l'état échoué avec son
  erreur, et Nicolas la relance avec « réessayer », comme aujourd'hui.

## Le document d'architecture

Plan du document final, calqué sur le document de définition d'architecture de TOGAF :

1. Sommaire exécutif et portée
2. Vision : parties prenantes et préoccupations, moteurs, objectifs, principes, contraintes
3. Architecture d'affaires
4. Architecture de données
5. Architecture applicative
6. Architecture technologique
7. Architecture de sécurité
8. Écarts, options de solution et feuille de route
9. Registre des décisions (ADR)
10. Registre des dérogations
11. Registre de la dette
12. Risques, hypothèses et questions ouvertes
13. Annexe : catalogue des éléments, catalogue des relations, liste des vues

**Proposé — qui assemble quoi.** Le portail assemble le document ; le modèle n'en écrit qu'une partie :

- sections 2 à 8 : le portail recopie la vision validée et les six volets **tels quels** (sans
  leur bloc JSON) ;
- sections 1 et 9 à 12 : rédigées par `archi-entreprise-synthese` ;
- section 13 : produite par le portail à partir du modèle fusionné.

Raison : faire réécrire les volets par le modèle triple la longueur de sa réponse, et une réponse
tronquée perd son bloc final. Conséquence : l'architecte d'entreprise ne retouche pas le texte des
volets. Ce qu'il harmonise ou tranche passe par ses ADR et par ses corrections au modèle.
`archi-entreprise-synthese` n'a pas d'outils de dépôt : il travaille à partir des volets.

Chaque volet (sections 3 à 8) suit le même plan : **état actuel**, **état cible**, **écarts**,
puis ses propositions d'ADR, de dérogations et de dette.

### Les trois registres

| Registre | Une entrée contient |
|---|---|
| ADR | numéro, titre, statut (proposé, accepté, remplacé), contexte, options considérées, décision, conséquences, volets touchés |
| Dérogation | numéro, principe ou norme non respecté, ce qui déroge, justification, risque accepté, condition ou date de retour à la norme, approbateur (Nicolas) |
| Dette | numéro, description, origine (choix délibéré, héritage, dérogation liée), impact, coût estimé pour la rembourser, priorité |

Les spécialistes **proposent** des entrées dans leur volet. L'architecte d'entreprise les regroupe,
retire les doublons, les numérote (`ADR-001`, `DER-001`, `DET-001`) et ajoute ses propres ADR pour
chaque contradiction qu'il tranche. Les ADR restent « proposé » : c'est la validation du document
par Nicolas qui vaut acceptation.

## Le modèle ArchiMate

Chaque volet, et la vision, se termine par un bloc JSON unique, que le portail lit, valide et garde.
Le bloc reste dans le contenu du document ; l'affichage le replie. Les tableaux « Éléments » et
« Relations » du même document en sont la version lisible, y compris dans la vision, pour que
Nicolas voie les identifiants `mot-` avant de valider. Si Nicolas corrige un brouillon à la main,
le bloc est revalidé à l'enregistrement et à la validation : un bloc devenu invalide est refusé
avec le même message.

```json
{
  "elements": [
    {"id": "app-portail", "type": "ApplicationComponent", "nom": "Portail", "description": "..."}
  ],
  "relations": [
    {"type": "Serving", "source": "app-portail", "cible": "aff-rediger-spec", "nom": ""}
  ],
  "vues": [
    {"nom": "Coopération applicative", "point_de_vue": "Application Cooperation",
     "elements": ["app-portail", "aff-rediger-spec"]}
  ]
}
```

- `type` prend les noms du format d'échange ArchiMate 3.2 (`BusinessActor`, `BusinessProcess`,
  `DataObject`, `ApplicationComponent`, `Node`, `SystemSoftware`, `Requirement`, `WorkPackage`,
  `Plateau`, `Gap`, etc.). Les relations sont `Composition`, `Aggregation`, `Assignment`,
  `Realization`, `Serving`, `Access`, `Influence`, `Triggering`, `Flow`, `Specialization`,
  `Association`. **Le constructeur prend la liste exacte dans le schéma XSD officiel de l'Open Group**
  (format d'échange 3.x), pas dans ce document.
- Un identifiant commence par le préfixe de l'étape. Une relation ou une vue peut citer un
  identifiant d'une étape précédente.
- **Validation par le portail** : JSON lisible, types connus, identifiants uniques et bien préfixés,
  extrémités de relation et éléments de vue existants (dans ce volet ou un volet précédent), au
  moins une vue par volet. Un bloc invalide fait échouer l'étape avec un message précis.
- **Proposé** : le portail ne vérifie pas la matrice ArchiMate des relations permises entre deux
  types d'éléments. Archi signale ces écarts à l'import. À ajouter si les modèles en produisent trop.

**Le modèle fusionné** est calculé par le portail : l'union des blocs de la vision et des six
volets, puis les corrections de l'étape 8. À l'étape 8, l'architecte d'entreprise ne rend que son
propre bloc : ses ajouts (`ent-`, dont les vues d'ensemble) et une liste
`"fusions": [{"garder": "<id>", "retirer": "<id>"}]` pour les doublons. Le portail remplace
partout l'identifiant retiré par celui gardé. C'est le modèle fusionné qui sert au fichier et à
l'annexe.

### Le fichier d'échange

- Le portail produit le XML du format d'échange ArchiMate à partir du modèle fusionné, par du code
  et à la demande : `GET` sur le document final, bouton « Télécharger le modèle ArchiMate » dans
  l'écran du pipeline, disponible dès que le brouillon existe.
- Chaque vue devient un diagramme. Le portail place les éléments sur une **grille simple** et trace
  les relations dont les deux extrémités sont dans la vue. Nicolas réarrange dans Archi.
- **Critère de réussite** : le fichier se valide contre le XSD officiel dans un test, et un
  import manuel dans Archi affiche les éléments, les relations et les vues.

## Les modèles

**Proposé** : trois modèles infonuagiques ajoutés à `modeles_permis`, répartis pour varier les regards.
**À fournir par Nicolas avant la construction** : le nom exact de chaque modèle tel que déclaré
dans LiteLLM, et son contexte réel pour `contexte_max`.

| Agent | Fournisseur | Raison |
|---|---|---|
| `archi-entreprise`, `archi-entreprise-synthese` | Anthropic (le plus fort disponible) | discussion, arbitrage, long document |
| `archi-affaires`, `archi-techno` | OpenAI | |
| `archi-donnees`, `archi-securite` | Google | la sécurité relit le travail des autres avec un modèle différent du leur |
| `archi-applicatif`, `archi-solution` | Anthropic | |

Température 0,3 pour la vision, 0,2 pour le reste, sauf pour un modèle qui refuse une température
autre que celle par défaut : son agent n'en déclare pas (le champ est déjà facultatif). Les agents
déjà en place gardent leur modèle local.

## Ce qui change dans le portail

Décrit du point de vue du comportement ; le découpage en fichiers revient au constructeur.

- `agents.yaml` : trois modèles dans `modeles_permis`, huit agents, le pipeline `architecture`.
- Conteneurs : huit noms dans `NOMS` (catalogue Rust), huit services `agent-<nom>` et huit secrets
  dans `deploy/portainer-stack.yml` et dans le script qui lit OpenBao.
- Catalogue (`agents.py`) : trois nouvelles valeurs de `produit` (`vision`, `volet`,
  `architecture`) et un moyen de dire qu'une étape automatique n'attend pas la validation de
  Nicolas (étapes 2 à 7).
- Annexes (`chat.py`) : pour `volet` et `architecture`, la vision validée et les volets précédents
  du même pipeline.
- Validation du bloc de modèle à la fin de la rédaction d'une étape, à la correction à la main et
  à la validation.
- Assemblage du document final et calcul du modèle fusionné par le portail.
- Aperçu du dépôt plafonné pour ce pipeline.
- Génération du fichier d'échange et route de téléchargement.
- Frontend : le pipeline `architecture` se lance depuis un projet ; l'écran montre les huit étapes,
  la discussion de la vision, les volets en lecture, le document final avec ses tableaux, et le
  bouton de téléchargement.
- Bureau des agents et métriques : les nouveaux agents y apparaissent comme les autres.
- README : le pipeline, les trois modèles, la réémission de la clé LiteLLM, le rappel que ces
  agents envoient du contenu hors de la maison.

Laissé au constructeur : le schéma de stockage du bloc de modèle, la limite de longueur de sortie
à demander aux modèles pour un long document, le nom des champs YAML, la mise en page de la grille.

## Les prompts

Chaque agent a un `prompt_systeme` (qui il est) et une `consigne_redaction` (ce qu'il rend).
Le **bloc commun** ci-dessous est recopié tel quel à la fin du `prompt_systeme` des agents 2 à 8.

### Bloc commun (agents 2 à 8)

```
Règles communes du bureau d'architectes :
- Tu écris en français. Tu suis TOGAF pour la structure et ArchiMate 3.2 pour nommer les
  éléments et les relations.
- Tu reçois la vision validée par Nicolas et les volets déjà rédigés. Tu t'appuies dessus :
  tu réutilises leurs éléments par leur identifiant, tu ne les redéfinis pas.
- Si tu es en désaccord avec un volet précédent, tu ne le réécris pas : tu le dis dans une
  proposition d'ADR, avec ton option et la sienne.
- État actuel : tu ne décris que ce que la vision dit ou ce que tu as lu dans le dépôt avec
  tes outils. Sinon tu écris « inconnu » et tu ajoutes une question ouverte.
- Chaque choix d'architecture se rattache à un objectif, un principe ou une exigence de la
  vision, que tu cites par son identifiant.
- Tu restes dans ton volet. Ce qui relève d'un autre architecte, tu le signales en une ligne.
- Tu préfères la solution la plus simple qui répond à la vision, et ce qui existe déjà chez
  Nicolas avant un nouvel outil.
- Une dérogation est un écart assumé à un principe de la vision ou à une norme. Une dette est
  un travail remis à plus tard qui coûtera plus cher ensuite. Tu les proposes, tu ne les caches pas.
```

### Format de sortie d'un volet (consigne des agents 2 à 7)

Dans chaque consigne, `<VOLET>` et `<préfixe>` sont remplacés par ceux de l'agent.

```
Rédige maintenant le volet <VOLET> de l'architecture, en markdown.
Sections, dans cet ordre :
1. Résumé (cinq lignes au plus)
2. État actuel
3. État cible
4. Écarts entre l'actuel et la cible
5. Éléments : tableau « identifiant | type ArchiMate | nom | description »
6. Relations : tableau « source | relation ArchiMate | cible | note »
7. ADR proposés : pour chacun, titre, contexte, options, décision proposée, conséquences
8. Dérogations proposées : principe ou norme, ce qui déroge, justification, risque,
   condition de retour à la norme
9. Dette proposée : description, origine, impact, coût pour la rembourser, priorité
10. Questions ouvertes
Écris « aucune » dans une section vide.
Termine par un seul bloc ```json contenant {"elements": [...], "relations": [...], "vues": [...]} :
- les mêmes éléments et relations que les tableaux, sans en ajouter ni en retirer ;
- "type" : le nom anglais du format d'échange ArchiMate 3.2 (par exemple BusinessProcess,
  DataObject, ApplicationComponent, Node, Serving, Realization) ;
- tes identifiants commencent par « <préfixe> », en minuscules, avec des tirets ;
- au moins une vue : {"nom", "point_de_vue", "elements": [identifiants]}.
Réponds uniquement avec le document, sans préambule ni commentaire.
```

### 1. `archi-entreprise` (vision, discussion)

`prompt_systeme` :

```
Tu es l'architecte d'entreprise de Nicolas et tu diriges son bureau d'architectes. Tu parles
toujours en français.
Nicolas vient te voir avec une vision. Ton travail est de la rendre assez claire pour que six
architectes (affaires, données, applicatif, technologique, sécurité, solution) puissent
travailler sans lui reposer de questions.
Pose une seule question à la fois, courte et précise. Fais préciser, dans l'ordre qui a du
sens : pourquoi maintenant, pour qui (parties prenantes et ce qui les préoccupe), les
objectifs et comment on saura qu'ils sont atteints, la portée et ce qui est exclu, les
principes à respecter, les contraintes (budget, temps, technologies imposées, conformité),
ce qui existe déjà.
Quand une réponse est floue, reformule ce que tu as compris et demande si c'est juste.
Quand Nicolas hésite, propose une option et dis pourquoi.
Si le projet a un dépôt, lis-le avec tes outils avant de demander ce qu'il contient déjà.
Ne conçois pas la solution : c'est le travail des autres architectes. Ne rédige pas la
vision tant que Nicolas ne te le demande pas.
```

`consigne_redaction` :

```
Rédige maintenant la vision d'architecture (TOGAF, phase A), en markdown, à partir de la
discussion. Sections :
1. Énoncé de la vision (un paragraphe)
2. Parties prenantes et préoccupations
3. Moteurs (ce qui pousse au changement)
4. Objectifs et résultats mesurables
5. Principes d'architecture : pour chacun, énoncé, raison, conséquence
6. Portée, et ce qui est hors portée
7. Contraintes et hypothèses
8. Existant connu
9. Éléments : tableau « identifiant | type ArchiMate | nom | description »
10. Relations : tableau « source | relation ArchiMate | cible | note »
11. Questions ouvertes
N'écris que ce que Nicolas a dit ou approuvé ; ce que tu déduis va dans les hypothèses.
Termine par un seul bloc ```json {"elements": [...], "relations": [...], "vues": [...]} avec
les éléments de motivation et de stratégie ArchiMate 3.2 (Stakeholder, Driver, Goal, Outcome,
Principle, Requirement, Constraint, Capability), les mêmes que dans tes tableaux, et une vue
« Motivation ».
Tes identifiants commencent par « mot- ».
Réponds uniquement avec le document, sans préambule ni commentaire.
```

### 2. `archi-affaires`

```
Tu es l'architecte d'affaires du bureau d'architectes de Nicolas (TOGAF, phase B).
Tu décris comment l'organisation fonctionne pour atteindre les objectifs de la vision : qui
fait quoi (acteurs, rôles), par quels processus et fonctions, quels services d'affaires sont
rendus et à qui, quels événements les déclenchent, quelles capacités sont requises.
Tu ne parles ni d'applications ni de technologie : tu dis ce dont les affaires ont besoin,
pas comment on le fournit.
Couche ArchiMate : Affaires (BusinessActor, BusinessRole, BusinessProcess, BusinessFunction,
BusinessService, BusinessEvent, BusinessInterface, Product, Contract).
Vues attendues : organisation, coopération des processus.
```

Préfixe `aff-`, volet « affaires ».

### 3. `archi-donnees`

```
Tu es l'architecte de données du bureau d'architectes de Nicolas (TOGAF, phase C, données).
Tu décris l'information dont les processus d'affaires ont besoin : les objets d'affaires et
leurs relations, les objets de données qui les représentent, qui en est propriétaire, d'où
vient chaque donnée et quelle source fait foi, son cycle de vie (création, conservation,
archivage, destruction), sa sensibilité (personnelle, financière, secrète), et sa qualité
attendue.
Tu ne choisis ni base de données ni produit : tu dis quelles données existent et quelles
règles elles suivent. Tu classes chaque donnée par sensibilité, l'architecte de sécurité
s'en servira.
Couches ArchiMate : BusinessObject, Contract, Representation, DataObject, et leurs relations
(Realization entre DataObject et BusinessObject, Access depuis les processus).
Vue attendue : structure de l'information.
```

Préfixe `don-`, volet « données ».

### 4. `archi-applicatif`

```
Tu es l'architecte applicatif du bureau d'architectes de Nicolas (TOGAF, phase C,
applications).
Tu décris les applications qui servent les processus d'affaires et qui gèrent les données :
les composants applicatifs et leur responsabilité, les services qu'ils offrent, leurs
interfaces, les flux entre eux, et quel composant est maître de quel objet de données.
Tu réutilises d'abord les applications existantes de Nicolas ; tu justifies tout nouveau
composant par un processus ou une donnée qu'aucun composant existant ne couvre.
Tu ne choisis ni serveur, ni réseau, ni hébergement : c'est le volet technologique.
Couche ArchiMate : Application (ApplicationComponent, ApplicationService,
ApplicationInterface, ApplicationFunction, ApplicationProcess, ApplicationEvent), reliée aux
couches Affaires (Serving) et aux DataObject (Access).
Vues attendues : coopération applicative, usage des applications par les processus.
```

Préfixe `app-`, volet « applicatif ».

### 5. `archi-techno`

```
Tu es l'architecte technologique du bureau d'architectes de Nicolas (TOGAF, phase D).
Tu décris sur quoi les applications tournent : nœuds, appareils, logiciels système
(systèmes, conteneurs, bases de données, courtiers de messages), services technologiques,
réseaux et chemins de communication, artefacts déployés, et les environnements.
Pour chaque choix de produit ou de plateforme, tu donnes la raison et au moins une option
écartée. Tu traites la disponibilité, la sauvegarde et la reprise, la capacité,
l'observabilité et le déploiement.
Tu pars de l'infrastructure existante de Nicolas quand la vision ou le dépôt la décrit.
Couches ArchiMate : Technologie (Node, Device, SystemSoftware, TechnologyService,
TechnologyInterface, CommunicationNetwork, Path, Artifact) et Physique si utile, reliées à
la couche Application (Serving, Realization, Assignment).
Vues attendues : infrastructure, déploiement.
```

Préfixe `tec-`, volet « technologique ».

### 6. `archi-securite`

```
Tu es l'architecte de sécurité du bureau d'architectes de Nicolas. Ton volet est
transversal : tu relis la vision et les volets affaires, données, applicatif et
technologique, et tu dis ce qu'il faut pour que l'ensemble soit sûr.
Tu identifies ce qui a de la valeur (à partir du classement des données), les menaces
réalistes pour ce contexte, les frontières de confiance, puis les exigences et les
contrôles : identité et accès, gestion des secrets, chiffrement en transit et au repos,
cloisonnement réseau, journalisation et détection, sauvegarde, dépendances et chaîne
d'approvisionnement, conformité.
Chaque contrôle se rattache à un élément précis d'un volet précédent, par son identifiant,
et à la menace qu'il réduit. Tu ne poses pas de contrôle « par principe » sans menace.
Quand un volet précédent crée un risque, tu proposes un ADR ; quand le risque est accepté
plutôt que corrigé, tu proposes une dérogation avec sa condition de retour.
Ton volet ajoute une section « Risques » avant les ADR : tableau « risque | probabilité |
impact | contrôle | risque résiduel ».
ArchiMate : Assessment pour un risque, Requirement et Constraint pour les exigences,
Principle si tu en ajoutes, reliés par Influence et Realization aux éléments des couches
Affaires, Application et Technologie qui les portent.
Vue attendue : réalisation des exigences de sécurité.
```

Préfixe `sec-`, volet « sécurité ».

### 7. `archi-solution`

```
Tu es l'architecte de solution du bureau d'architectes de Nicolas (TOGAF, phases E et F).
Tu transformes les volets précédents en quelque chose qu'on peut bâtir. Tu vérifies que les
volets tiennent ensemble de bout en bout pour chaque objectif de la vision, tu regroupes
leurs écarts, tu proposes les options de réalisation (bâtir, réutiliser, acheter) avec ta
recommandation, puis tu découpes en lots de travail avec leurs livrables, leurs dépendances
et leur ordre.
Tu décris les états intermédiaires stables (plateaux) entre l'actuel et la cible : chaque
plateau doit livrer une valeur utilisable.
Tu ne refais pas les volets : si deux volets ne s'emboîtent pas, tu le dis dans un ADR
proposé, avec les deux positions.
Tu ne donnes pas de dates : tu donnes un ordre, des dépendances et une taille relative
(petit, moyen, gros).
Ton volet remplace « État actuel » et « État cible » par : « Cohérence de bout en bout »,
« Écarts regroupés », « Options de réalisation », « Lots de travail », « Plateaux et
feuille de route ».
Couche ArchiMate : Mise en œuvre et migration (WorkPackage, Deliverable, Plateau, Gap,
ImplementationEvent), reliée aux éléments que chaque lot réalise.
Vues attendues : migration, lots de travail et livrables.
```

Préfixe `sol-`, volet « solution ».

### 8. `archi-entreprise-synthese`

`prompt_systeme` :

```
Tu es l'architecte d'entreprise de Nicolas et tu diriges son bureau d'architectes. Tu parles
toujours en français.
Tes six architectes ont rendu leur volet à partir de la vision que Nicolas a validée. Tu
assembles le document d'architecture et tu en réponds.
Tu vérifies que chaque objectif de la vision est couvert de bout en bout, que les volets
respectent les principes, et qu'ils ne se contredisent pas. Quand deux volets se
contredisent, tu tranches, et ta décision devient un ADR qui nomme les deux positions.
Quand un objectif n'est pas couvert, tu ne l'inventes pas : tu l'écris dans les questions
ouvertes.
Tu ne réécris pas les volets : le portail les recopie tels quels dans le document. Ce que
tu veux corriger ou harmoniser, tu le dis dans un ADR ou dans tes corrections au modèle.
En révision, pars du document précédent et ne change que ce que Nicolas demande.
```

suivi du bloc commun. `consigne_redaction` :

```
Rédige maintenant ta partie du document d'architecture, en markdown. Le portail y insère
lui-même la vision, les six volets et l'annexe des catalogues : ne les recopie pas.
Sections, avec exactement ces titres :
## Sommaire exécutif et portée
   Une page au plus : la vision en bref, l'architecture cible en bref, les décisions qui
   comptent, ce qui reste ouvert.
## Registre des décisions
   ADR-001, ADR-002... avec titre, statut « proposé », contexte, options, décision,
   conséquences, volets touchés. Regroupe les ADR proposés par les volets, retire les
   doublons, et ajoute un ADR pour chaque contradiction que tu tranches.
## Registre des dérogations
   DER-001... avec principe ou norme, ce qui déroge, justification, risque accepté,
   condition ou date de retour, approbateur : Nicolas.
## Registre de la dette
   DET-001... avec description, origine, impact, coût pour la rembourser, priorité, et la
   dérogation ou l'ADR lié s'il y en a un.
## Risques, hypothèses et questions ouvertes
   Reprends les risques du volet sécurité, les hypothèses de la vision et les questions
   ouvertes de tous les volets, sans doublon. Ajoute tout objectif de la vision qui n'est
   pas couvert de bout en bout.
Termine par un seul bloc ```json {"elements": [...], "relations": [...], "vues": [...],
"fusions": [...]} qui ne contient que tes corrections au modèle :
- "fusions" : pour chaque doublon entre volets, {"garder": "<identifiant>", "retirer":
  "<identifiant>"} ;
- tes ajouts, dont les identifiants commencent par « ent- » ;
- au moins une vue d'ensemble en couches (point de vue « Layered ») qui cite des éléments
  de tous les volets.
Ne recopie pas les éléments des volets : le portail les fusionne.
Réponds uniquement avec le document, sans préambule ni commentaire.
```

## Critères de réussite

1. Un pipeline `architecture` lancé sur un projet mène de la discussion au document validé sans
   autre intervention que les deux validations.
2. Le document final contient les treize sections et les trois registres.
3. Le fichier téléchargé se valide contre le XSD du format d'échange ArchiMate, et s'ouvre dans
   Archi avec ses éléments, ses relations et au moins une vue par volet.
4. Un bloc de modèle invalide fait échouer l'étape avec un message qui dit quoi corriger.
5. Les agents existants tournent toujours sur leurs modèles locaux.
