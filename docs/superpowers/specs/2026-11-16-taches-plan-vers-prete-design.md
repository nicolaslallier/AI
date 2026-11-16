# Le plan validé fait avancer le kanban

## Pourquoi

Pipeline 13 (projet AI) : plan validé, étape `taches` terminée… et rien dans le kanban.
L'agent a proposé 10 modifications de T3, tâche protégée ; toutes écartées en silence à
l'enregistrement. L'étape finit « terminée » sans tâche. Nicolas veut qu'un plan validé mène
droit au travail : des tâches créées, et prises aussitôt par la boucle de dev.

## Objectifs

- A. Une proposition qui vise une tâche non modifiable (absente, protégée, verrouillée, hors
  `a_faire`/`prete`) rend la réponse invalide : le modèle reçoit la raison et réessaie une fois
  (la relance existante de `_proposer`). Second échec : l'étape échoue, message visible.
- A'. Le prompt de l'agent `taches` dit qu'on ne modifie ni ne retire une tâche protégée,
  verrouillée ou hors À faire/Prête, et qu'une étape du plan devient une tâche nouvelle.
- B. Pour un agent `sans_validation`, les tâches créées par l'étape passent en **Prête**
  (`deplacer_tache`, auteur `agent:taches`), dans l'ordre de création. L'ordonnanceur les prend
  ensuite, une à la fois, dépendances respectées.

## Non-objectifs

- Déplacer les tâches existantes que l'étape modifie : elles restent où elles sont.
- Remplir `config_execution` du projet AI : réglage de Nicolas, dans la page du projet.
- Changer l'ordonnanceur ou le sens de la colonne À faire.

## Approches

- **Retenue — relance + déplacement.** A s'appuie sur la boucle de relance déjà en place ;
  B réutilise `deplacer_tache`, donc l'historique du kanban montre « déplacée vers Prête par
  agent:taches ».
- Créer directement en Prête (paramètre `colonne` sur `creer_tache`) : moins d'écritures, mais
  plus de trace du passage automatique. Écartée.
- Faire prendre À faire par l'ordonnanceur : change le sens de la colonne pour les tâches
  manuelles. Écartée.

## Le comment

- `lire_propositions(texte, cles_existantes)` reçoit plutôt `{id: raison | None}` des tâches du
  projet (raison calculée par `_raison`) ; une modification ou un retrait dont la tâche est
  absente ou a une raison lève `ValueError("T<id> : <raison> ; propose une tâche nouvelle")`.
  `enregistrer_propositions` garde sa vérification sous verrou (course entre lecture et écriture).
- `_enregistrer` : après `tout_accepter`, pour chaque `Proposition` de l'étape avec
  `tache_creee_id`, par id, `deplacer_tache(s, tache, "prete", None, f"agent:{agent.nom}")`.
- Tests : une réponse « modification de T protégée » relance puis échoue ; une réponse valide
  après relance passe ; les tâches créées par une étape `sans_validation` finissent en `prete`.

## Laissé au builder

Formulation exacte du message d'erreur et de la ligne de prompt.
