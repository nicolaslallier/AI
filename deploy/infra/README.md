# À reporter dans le dépôt Infra (PR Infra du lot F)

Ces éléments vivent côté Infra ; ce dossier en garde la source.

1. **Règle Alloy** : recopier `alloy-journaux-prives.alloy` dans `discovery.relabel`
   de `monitoring/alloy/config.alloy`.
2. **Vhost** du portail : voir la tâche 9 du plan du lot F.
3. **Vérification après déploiement** : lancer une exécution, puis vérifier que
   `{container=~"run-.*"}` ne renvoie rien dans Loki (adapter au préfixe réel
   des conteneurs du lanceur).
