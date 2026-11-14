# Portail d'orchestration IA — C2 : reprise sur commentaires, ntfy et flux d'événements : design

Date : 2026-11-14 · Statut : à approuver par Nicolas
S'appuie sur : la spec C (`2026-11-14-portail-c-boucle-dev-design.md`) et la spec C1
(`2026-11-14-portail-c1-boucle-dev-design.md`), dont le code est sur `claude/portail-c1` (PR #22, pas encore fusionnée).

Ce document termine C : il reprend ce que la spec C1 a « reporté à C2 », et ne fixe que ce que la spec C laissait ouvert.
Tout ce qui n'est pas mentionné ici reste comme dans la spec C et la spec C1.

## Intention

Fermer la boucle. Aujourd'hui, une PR ouverte par le portail ne bouge plus : Nicolas corrige lui-même ou ferme. Avec C2,
Nicolas relit la PR sur GitHub comme il le ferait pour un collègue, et les agents reprennent le travail sur la même branche,
avec les mêmes protections, puis répondent sous ses commentaires. Il est prévenu sur son téléphone (ntfy) quand il y a
quelque chose à regarder, et l'interface se met à jour seule.

## Objectifs

1. Une revue de Nicolas sur une PR du portail déclenche **une** reprise qui traite tous ses commentaires.
2. Les commentaires sur des tests vont à l'agent de tests, ceux sur le code à l'agent de code ; la séparation tests/code et la
   troisième protection tiennent comme en C1.
3. Le portail répond sous chaque commentaire traité, et explique sur la PR une reprise qui échoue.
4. ntfy : PR ouverte, tâche *Bloquée*, reprise terminée (réussie ou non).
5. Le kanban et la liste des pipelines passent du sondage au flux d'événements (SSE).

## Non-objectifs

- Discuter avec les agents dans les fils de commentaires (une reprise répond, elle ne mène pas de conversation).
- Réagir aux commentaires d'autres personnes que Nicolas, ou des bots (CI, Dependabot…).
- Plusieurs reprises en parallèle, ou plusieurs dépôts suivis plus vite (on garde `paralleles_max` = 1).
- Webhooks GitHub (le portail n'est pas joignable depuis Internet : on reste au sondage côté GitHub).

## Anti-objectifs

- Une reprise qui pousse quelque chose que la troisième protection refuse, ou qui réécrit l'historique (jamais de force-push ni de rebase).
- Cinq commentaires d'affilée qui lancent cinq reprises.
- Un commentaire traité deux fois après un redémarrage, ou jamais traité.
- Une panne de ntfy ou du flux d'événements qui fait échouer un pipeline.

## Ce qui est décidé

### Quand une reprise part (décidé par Nicolas)

- **Une revue soumise** par Nicolas (« Request changes » ou « Comment ») déclenche une reprise **avec tout le lot** :
  le texte de la revue et ses commentaires de ligne.
- **Les commentaires isolés** (commentaires de conversation sur la PR, hors revue) partent quand **10 minutes** se sont écoulées
  sans nouveau commentaire de Nicolas sur cette PR. Plusieurs commentaires isolés rapprochés font donc une seule reprise.
- Une revue « Approve » ne déclenche rien. Une revue sans texte **ni** commentaire de ligne non plus ; une revue au texte vide
  mais avec des commentaires de ligne compte (sur GitHub, un « single comment » de ligne est une revue `COMMENTED`).
- Une revue **emporte** les commentaires isolés encore dans leur délai : tout ce que Nicolas a écrit de nouveau jusque-là part
  dans la même reprise. *(Choix de Claude.)*
- Ce que Nicolas écrit **pendant** qu'une reprise tourne attend le retour *En revue*, puis suit les mêmes règles (une revue part
  tout de suite ; des commentaires isolés partent 10 minutes après le dernier, délai qui peut être déjà écoulé). *(Choix de Claude.)*
- Seuls comptent les auteurs dont le login est `PORTAIL_GITHUB_PROPRIETAIRE` (nouveau réglage, pas un secret). Sans ce
  réglage, aucune reprise ne part (le suivi fusion/fermeture de C1 continue).

### Ce que le portail retient *(choix de Claude)*

- **Le suivi des PR crée la reprise ; l'ordonnanceur la lance.** Quand le suivi voit un lot prêt, il crée dans une seule
  transaction l'exécution de reprise **en attente** (pipeline `dev`, mode `reprise`, avec les commentaires pris en charge : id
  GitHub, type, auteur, chemin et ligne s'il y en a, texte). La tâche reste *En revue* et garde son verrou jusqu'à ce que
  l'ordonnanceur lance la reprise ; elle passe alors *En cours* et le verrou passe à la reprise. L'ordonnanceur ne lit que la base.
- Un commentaire déjà pris en charge par une exécution de la tâche n'est plus jamais repris. Après un redémarrage, une reprise
  lancée est reprise comme en C1 (une fois) ; une reprise en attente attend simplement son tour. Rien n'est redemandé à GitHub.
- La reprise recopie de l'exécution d'origine la branche, `pr_numero` et `pr_url` (pas de suffixe `-n`, pas de nouvelle PR,
  aucune PR fermée). Le suivi lit toujours la **dernière** exécution de la tâche, comme en C1.
- Au tout premier passage sur une PR (exécution de C1, ou portail mis à jour avec des PR déjà ouvertes), seuls les commentaires
  **postérieurs à l'ouverture de la PR par le portail** comptent.
- Les commentaires que le portail écrit lui-même (réponses, explications) sont signés par l'App : le filtre par login les écarte.

### La reprise *(choix de Claude, d'après la spec C)*

Une reprise est une **nouvelle exécution `dev`** (nouveau pipeline, mode `reprise`) sur la **même branche** et la **même PR**.
Elle prend le verrou de la tâche, qui passe *En revue* → *En cours*.

1. **Préparation** : clone neuf, branche récupérée telle quelle sur GitHub (avec les commits que Nicolas aurait poussés),
   puis fusion de `origin/<branche_ref>`. Conflit → la tâche revient *En revue*, commentaire sur la PR demandant à
   Nicolas de résoudre, ntfy. Installation comme en C1.
2. **Tri** : l'agent de revue, avec une consigne de tri, classe chaque commentaire en `tests`, `code` ou `reponse`
   (question ou remarque sans changement à faire), avec une consigne courte par commentaire. Sortie JSON validée par schéma.
   Un commentaire de ligne sur un chemin de tests est toujours `tests`, quoi que dise le tri. Un commentaire sur une section de
   tests d'un manifeste (`[tool.pytest]`, `scripts` de `package.json`…) ne peut être fait par aucun agent (C1 : l'étape tests ne
   commite pas les manifestes, la troisième protection refuse l'agent de code) : il est classé `reponse`, et la réponse dit que
   c'est à Nicolas de le faire. JSON du tri illisible ou invalide → **échec de la reprise** (voir plus bas), jamais un tri par défaut.
3. **Tests** (s'il y a des commentaires `tests`) : l'agent de tests, avec ses commentaires. Pas de vérification « rouge » (comme
   après un renvoi de la revue en C1).
4. **Code** (s'il y a des commentaires `code`, ou si l'étape tests a changé quelque chose) : l'agent de code, avec ses
   commentaires et les tests. Mêmes règles qu'en C1 (rôle, lecture seule, globs restaurés).
5. **Vérification** sur espace propre, puis **revue** (au plus 2 renvois), exactement comme en C1.
6. **Push** (troisième protection juste avant, sur les commits de la reprise seulement), puis une **réponse** sous chaque
   commentaire pris en charge : pour un commentaire de ligne, dans son fil ; pour une revue ou un commentaire de conversation,
   un commentaire sur la PR qui les cite. La réponse dit ce qui a été fait (commit court) ou, pour `reponse`, répond.
7. La tâche revient *En revue*, le verrou reste posé sur la nouvelle exécution, ntfy « reprise terminée ».

Si aucun commentaire n'appelle de changement (tous `reponse`), la reprise saute 3 à 6 sauf les réponses, et ne pousse rien
(pas même la fusion de l'étape 1).

**Points de départ** *(choix de Claude)* : la fusion de `origin/<branche_ref>` est un commit du portail (auteur `portail`), poussé
seulement avec des changements d'agents. Le diff montré à la revue part du HEAD **après** cette fusion (seul le travail des agents
apparaît). La troisième protection vérifie les commits d'agents de rôle `code` entre le HEAD récupéré sur GitHub et le nouveau HEAD
(le commit de fusion et ceux de Nicolas ne sont pas vérifiés, comme en C).

### Échec d'une reprise (spec C)

Tout ce qui bloquerait une première exécution (délai, `tours_max`, revue épuisée, protection, commande invalide…) ramène la
tâche **En revue** au lieu de *Bloquée*. Rien n'est poussé si la troisième protection refuse ; sinon les commits valides déjà
faits ne sont **pas** poussés non plus *(choix de Claude : une reprise est tout ou rien)*. Le portail explique l'échec en
commentaire sur la PR (raison courte, sans sortie brute de commande) et notifie. Les commentaires restent pris en charge :
Nicolas recommente pour relancer.

### Ordonnanceur *(choix de Claude)*

Une reprise compte dans `paralleles_max` = 1. Quand une place se libère, **les reprises passent avant** les tâches *Prêtes*
(finir ce qui est en revue avant d'ouvrir autre chose), dans l'ordre d'arrivée des commentaires.

### Annuler

« Annuler » sur une reprise en cours arrête la commande, termine le pipeline (« annulé ») et ramène la tâche **En revue** (pas
*À faire* : la PR existe). L'espace est supprimé, rien n'est poussé.

### ntfy

- Réglages : `PORTAIL_NTFY_URL` (défaut `http://ntfy`), `PORTAIL_NTFY_SUJET` (défaut `portail`) et le secret
  `PORTAIL_NTFY_JETON`, ajouté à `MAP` dans `scripts/vault-render-env.sh` et rangé dans OpenBao `infra/portail`.
  Nicolas l'obtient avec `make ntfy-provision app=portail` dans l'Infra (rien à changer dans l'Infra).
- Trois messages : PR ouverte (lien de la PR), tâche *Bloquée* (raison courte, lien vers la tâche), reprise terminée
  (réussie : lien de la PR ; échouée : raison courte). Titre = titre de la tâche.
- Envoi au mieux : délai court, une erreur est journalisée et n'arrête rien. Sans jeton, rien n'est envoyé.
- Liens absolus : nouveau réglage `PORTAIL_URL_PUBLIQUE` (dans la pile : `https://portail.infra.famillelallier.net`). Il sert aux
  notifications et remplace les liens relatifs du corps des PR de C1, qui ne marchent pas sur GitHub. Sans réglage, pas de lien.
  *(Choix de Claude.)*

### Flux d'événements (SSE) *(choix de Claude)*

- Un seul flux, `GET /api/evenements` (même authentification que le reste de l'API), qui n'envoie que des **signaux** :
  `kanban` avec l'id du projet, ou `pipelines`. Jamais de données : le client recharge ce qu'il affiche avec les routes existantes.
- Les signaux sont publiés dans le processus (le portail tourne en un seul processus, l'ordonnanceur l'impose déjà) à chaque
  changement de tâche ou de pipeline : routes, orchestrateur, ordonnanceur, suivi des PR.
- Le kanban et la liste des pipelines s'abonnent ; le sondage reste en filet, toutes les 60 s. Un ping de maintien est envoyé
  toutes les 25 s (NGINX coupe les connexions muettes).
- Le détail d'un pipeline garde le SSE existant de A/B pour ses étapes.

### Interface

- Une reprise apparaît comme un pipeline `dev` de plus sur la tâche, avec ses commentaires pris en charge (auteur, extrait,
  lien GitHub) et le résultat du tri. Le texte des commentaires est affiché tel quel, jamais en HTML.
- Le kanban montre « reprise en cours » sur la carte d'une tâche *En cours* en mode reprise.

## Contraintes

Celles de C et C1, en particulier : jamais de push sur `main`, jamais de fusion par Claude, jamais de secret dans le dépôt,
le déploiement ne tourne jamais sur `pull_request`, tout nouveau secret dans `MAP`. Le portail n'exécute jamais ce que les agents
écrivent. Le texte des commentaires est une donnée pour les agents (consigne de Nicolas, mais citée, pas fusionnée dans le prompt système).

## Approches envisagées

- **Une reprise par commentaire** : simple, mais une revue de cinq commentaires fait cinq reprises. Écartée.
- **Revue soumise, commentaires isolés regroupés après 10 min** : retenue par Nicolas — c'est sa façon naturelle de relire.
- **Seulement « Request changes »** : explicite, mais un simple commentaire ne fait rien. Écartée.
- Pour le temps réel : **signaux SSE + rechargement** (retenu, petit, sans état dupliqué) plutôt qu'envoyer les données dans le
  flux (deux chemins à garder cohérents) ou WebSocket (rien à envoyer du client).

## Déploiement

- Nouveaux réglages dans la pile : `PORTAIL_GITHUB_PROPRIETAIRE`, `PORTAIL_NTFY_URL`, `PORTAIL_NTFY_SUJET`,
  `PORTAIL_URL_PUBLIQUE`, et le secret
  `PORTAIL_NTFY_JETON` (dans `MAP` ; **prérequis bloquant** comme les trois secrets de C1).
- Une migration Alembic (mode de l'exécution, commentaires pris en charge).
- La PR C2 vise `claude/portail-c1` tant que la PR #22 n'est pas fusionnée, puis `main`.

## Laissé au constructeur

La consigne et le schéma JSON du tri, le format exact des réponses et des notifications, la forme des tables, les noms
des signaux SSE, les tests. Pour les tests, en plus de ceux de C1 :
- le regroupement (revue → une reprise ; trois commentaires isolés rapprochés → une reprise après 10 min ; Approve → rien) ;
- le filtre par auteur (bot, autre personne, le portail lui-même) ;
- rien de traité deux fois après un redémarrage ;
- un commentaire de ligne sur un test classé `code` par le tri va quand même à l'agent de tests ;
- l'échec d'une reprise ramène *En revue* sans push, avec un commentaire ;
- ntfy en panne n'arrête rien ; le flux SSE reçoit un signal quand une tâche change de colonne.

## Risque connu

Comme pour C1 : l'appel d'outils de qwen à travers LiteLLM n'est pas encore vérifié en vrai. C2 ajoute une sortie JSON (le tri).
