# Portail d'orchestration IA — D : agents transversaux : design

Date : 2026-11-14 · Statut : brouillon, à approuver par Nicolas
S'appuie sur : A, B et C (`2026-11-14-portail-{socle,b-plan-taches,c-boucle-dev}-design.md`), **supposés construits et fusionnés.**

## Intention

Ajouter les agents qui veillent sur la qualité et tiennent Nicolas au courant : un **PM** à qui il
demande où en sont ses projets, un **architecte**, un **challenger** qui ne croit personne sur parole,
un agent de **sécurité** et un agent de **documentation**. Une fois C construit, le moteur existe déjà :
D ajoute surtout des rôles dans le YAML et des étapes dans des types de pipeline, et presque pas de mécanique nouvelle.

## Objectifs

1. **PM** : un chat où Nicolas demande l'état de ses projets (« où en est EA ? », « qu'est-ce qui est
   bloqué ? », « qu'est-ce qui a avancé cette nuit ? », « qu'est-ce qui attend que je fasse quelque chose ? »). Un **résumé du matin** est envoyé par ntfy.
2. **Architecte** : il relit le brouillon du plan en le comparant à l'architecture du dépôt.
3. **Challenger** : il conteste les designs (spec, plan), la façon dont les IA codent, les hallucinations des
   agents, et le respect des règles (celles du dépôt et celles du portail).
4. **Sécurité** : il cherche les failles dans le diff de chaque tâche.
5. **Documentation** : il met à jour la documentation du dépôt dans la PR de la tâche.

## Non-objectifs

- Le PM n'agit pas : il ne lance aucun pipeline et ne modifie ni tâche ni document. On pourra l'élargir plus tard.
- Pas d'agent planificateur : l'ordonnanceur de C reste une règle fixe.
- Pas d'audit de sécurité de tout le dépôt ni de scan planifié : seulement le diff de chaque tâche.
- Pas de traduction ni de site de documentation : seulement les fichiers de doc du dépôt.

## Anti-objectifs

- Un challenger qui bloque tout pour des questions de goût : seuls les faits vérifiables et les règles enfreintes bloquent.
- Un challenger qui tourne sur le même modèle que l'agent qu'il conteste.
- Un agent qui ajoute des étapes sans limite : chaque renvoi compte dans la limite de renvois de C.
- Un PM qui invente un état : il ne répond qu'à partir de ce que ses outils lui renvoient.

## Contraintes

Celles de A, B et C. **Premier dépôt visé : EA.** Ses règles (`CLAUDE.md` / `AGENTS.md`) sont la première
source de règles que le challenger fait respecter.

## Approches envisagées

Une seule est sensée, et Nicolas l'a confirmée : **chaque agent est un rôle dans le YAML, placé comme étape dans un
type de pipeline**, avec la boucle d'outils, le lanceur et les règles de chemin de B et C. Des services séparés ou un framework
n'apporteraient rien ici, puisque le moteur existe déjà.

## Ce qui est décidé

### Renvois : une seule mécanique

En C, la revue répond `ok`, `renvoyer_tests` ou `renvoyer_code`. D **généralise** ce verdict à toute **étape de contrôle** :
- `ok` ;
- `renvoyer_tests` ou `renvoyer_code`, avec des remarques qui **bloquent** ;
- des `notes` qui ne bloquent pas : elles vont dans la PR, ou à côté du document.

Tous les renvois d'un pipeline `dev` partagent un seul compteur (`renvois_max`, 2 par défaut, comme en C).
Après un renvoi, le pipeline reprend à l'étape renvoyée, puis repasse par **tous** les contrôles qui suivent.
**Une fois la limite atteinte, les contrôles restants tournent quand même**, mais en mode `notes` seulement. La sécurité voit
donc toujours le diff final. Puis la PR s'ouvre avec les remarques non résolues bien en vue. *(Choix de Claude, à la suite de la relecture.)*

**Vérification « rouge » après un renvoi aux tests** (par exemple, la sécurité demande un test qui démontre la faille) : seuls les
fichiers de tests **ajoutés ou modifiés par ce renvoi** doivent échouer, et on ne relance qu'eux. Les tests précédents, qui passent déjà, restent verts.
*(Choix de Claude.)*

**Reprise sur les commentaires de la PR (C)** : toute la chaîne de contrôles retourne (revue, challenger, sécurité, documentation),
et le compteur de renvois **repart à zéro pour chaque reprise**. L'agent de tri peut classer un commentaire en *tests*, *code*
ou *doc*. *(Choix de Claude.)*

### Nouvel ordre du pipeline `dev`

`tests → rouge → code → suite complète → revue → challenger → sécurité → documentation → PR`.

### Documents : les avis à côté du brouillon

Pour les étapes à document (spec et plan) : quand **l'agent** rédige ou réécrit un brouillon, les agents d'avis
configurés pour ce type de document tournent automatiquement. Les enregistrements de Nicolas ne les déclenchent pas. Un bouton
« Demander un avis » les relance à la main. Un avis **n'est pas une étape** : il est rangé dans une table `avis`
(document, version lue, agent, contenu, état). Il ne compte pas dans l'état du pipeline, et Nicolas peut valider
sans attendre les avis en cours, qui sont alors abandonnés. À la réécriture suivante, l'agent reçoit les avis encore
*ouverts*. *(Choix de Claude, à la suite de la relecture.)*

**Partage des modèles** : au plus un appel en cours par modèle à la fois. Les appels interactifs (chats, avis) passent **avant**
les étapes de fond de `dev`. *(Choix de Claude : les modèles locaux sont lents et partagés.)*

Le reste du fonctionnement des avis : Leurs avis s'affichent **à côté du brouillon**, chacun avec
un état *ouvert*, *pris en compte* ou *écarté*, que Nicolas règle. **Ils ne bloquent pas la validation** : c'est Nicolas qui décide.
L'avis voit la version du brouillon qu'il a lue. Si le brouillon change, les avis précédents sont marqués « sur une version
antérieure ».

- Spec : le **challenger**.
- Plan : l'**architecte** et le **challenger**.

### PM

- C'est un chat, avec le même mécanisme que A (messages, streaming, jauge), mais **sans document à rédiger**. Il est accessible
  partout dans le portail, et une conversation PM n'est rattachée à aucun projet.
- Ses **outils**, en lecture seule sur les données du portail : `projets()`, `pipelines(filtre)`,
  `taches(projet, colonne?)`, `pipeline(id)` (avec ses étapes et leurs erreurs), `en_attente_de_nicolas()`, `activite(depuis)`.
  Ils renvoient des faits datés. Le prompt lui interdit d'affirmer ce qu'un outil n'a pas renvoyé.
- **Résumé du matin** : une heure réglable (par défaut 7 h, heure de Toronto). Le PM tourne avec une consigne fixe (« ce qui
  s'est passé depuis hier, ce qui est bloqué, ce qui attend Nicolas »), et le résultat est envoyé par ntfy et gardé dans
  l'historique du PM. Pas d'envoi s'il n'y a eu aucune activité.

### Architecte

- Il lit le dépôt (les outils en lecture seule de B) et le brouillon du plan. Il signale ce qui contredit l'architecture
  en place, les modules qu'il vaudrait mieux réutiliser plutôt que recréer, et les découpages qui ne cadrent pas avec le code.
- Il ne donne que des avis (voir « Documents »), il n'intervient pas dans `dev`. *(Choix de Claude : les
  questions d'architecture se règlent au plan. Dans une PR, c'est trop tard et ça coûte cher en renvois.)*

### Challenger

Il ne croit personne sur parole. Il a deux sources : des **faits vérifiés par du code**, puis son jugement.

**Faits vérifiés par le portail, avant le challenger, sans modèle.** Ces vérifications **bloquent d'elles-mêmes**, sans dépendre du
jugement du modèle : un échec renvoie le travail au rôle qui a produit le message ou le commit fautif (`tests` ou `code`) et compte
dans le compteur de renvois. Elles sont aussi données au challenger. *(Choix de Claude, à la suite de la relecture.)*
- **Références** : les fichiers, symboles et imports qu'un agent cite dans ses messages ou ajoute dans son diff existent-ils ?
  Cette vérification passe par les outils `chercher` et `lire`, et par l'installation des dépendances, qui échoue sur un paquet inventé.
- **Affirmations** : chaque « les tests passent », « lint OK », etc. d'un agent est comparé au **journal réel des `lancer`**
  de l'étape (quelle commande, quel code de retour, à quel moment). Une affirmation sans commande qui la prouve est signalée.
- **Règles mécaniques** : on vérifie le diff contre les règles du portail (chemins de tests, `config_tests`) et contre
  la commande `lint` du projet si elle existe. `lint` est d'abord lancée **sur la base de la branche**, au début de la tâche. Si elle échoue déjà
  sur la base, le lint ne fait que des `notes` pour cette tâche. On ne bloque jamais une tâche pour une dette qui existait avant elle.

**Jugement du challenger**, à partir de ces faits, du diff, de la tâche, des règles du dépôt (`CLAUDE.md`, `AGENTS.md`,
et un fichier de règles optionnel déclaré dans la config du projet) et du journal des agents :
- **une règle du dépôt enfreinte**, **une affirmation fausse** ou **une hallucination** : il renvoie le travail (`renvoyer_code` ou
  `renvoyer_tests`), avec la règle ou le fait en cause cité ;
- **la façon de coder** (un test contourné par un cas particulier, du code mort, une complexité inutile, une duplication de l'existant) : il renvoie si
  c'est un contournement des tests, sinon il laisse une `note` ;
- **le design** : une `note`.

**Il tourne sur un autre modèle que celui qu'il conteste.** « L'agent contesté », c'est l'**auteur principal** de l'étape : l'agent
de **code** dans `dev`, l'agent qui **rédige** pour la spec et le plan. (L'agent de tests peut avoir le même modèle que le challenger.
Avec deux modèles seulement aujourd'hui, on ne peut pas différer de tous.) Le YAML déclare pour lui un `modele` *et*
un `modele_si_meme`, utilisé quand l'auteur principal a le même modèle. Au démarrage, on vérifie que `modele` et
`modele_si_meme` sont différents, sinon le démarrage échoue. *(Précisé par Claude, à la suite de la relecture.)*

### Sécurité

- Il lit le diff et le code autour (lecture seule), et peut lancer une commande `securite` si le projet en déclare une
  (par exemple `pip-audit`, `npm audit` ou un analyseur statique). Elle passe par le lanceur, sans réseau autre que son squid.
- Une faille exploitable (injection, contrôle d'accès manquant, secret dans le code, désérialisation non sûre…) entraîne `renvoyer_code`
  ou `renvoyer_tests` (« ajoute un test qui démontre la faille »). Un point mineur ou une bonne pratique devient une `note`.

### Documentation

- Le rôle `doc` ne peut écrire que dans les **chemins de doc** déclarés dans la config du projet (par défaut `README.md`,
  `docs/**`, `CHANGELOG.md` s'il existe). Les règles de chemin sont appliquées par le lanceur, comme pour les autres rôles. Son
  commit a pour auteur `agent-doc`.
- Il ne fait rien si la tâche ne change aucun comportement documenté. Il ne renvoie jamais le travail.
- La troisième protection de C est étendue : les commits `agent-doc` ne touchent que les chemins de doc.

### Réglages par projet

La config d'exécution de C gagne : `chemins_doc`, `regles` (un chemin vers un fichier de règles en plus), et une commande
`securite` optionnelle. Les agents de contrôle se désactivent **par type de pipeline** dans le YAML, pas par projet, pour garder la config simple.

## Laissé au constructeur

- Les prompts des cinq agents, et le schéma JSON commun des verdicts de contrôle.
- Comment on extrait les références et les affirmations des messages et du diff (des heuristiques sont acceptables : mieux vaut signaler un faux positif à Nicolas
  qu'un faux négatif).
- Comment le résumé du matin est planifié (une boucle dans le processus comme l'ordonnanceur, ou autre).
- L'interface des avis à côté des documents, et l'endroit où le chat du PM s'ouvre.
- Les tests. Au minimum :
  - le compteur de renvois partagé, et la reprise à la bonne étape suivie de tous les contrôles ;
  - les vérifications factuelles (référence inexistante, affirmation sans `lancer` qui la prouve) ;
  - l'obligation d'un modèle différent pour le challenger ;
  - le confinement du rôle `doc` ;
  - le PM en lecture seule, sans aucun outil qui modifie quoi que ce soit ;
  - le résumé du matin, qui n'est pas envoyé sans activité.
