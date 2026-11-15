# À reporter dans le dépôt Infra (PR Infra du lot F)

Ces éléments vivent côté Infra ; ce dossier en garde la source.

1. **Règle Alloy** : `alloy-journaux-prives.alloy` est un fragment, à recopier dans
   le bloc `discovery.relabel` existant de `monitoring/alloy/config.alloy`, puis
   recharger Alloy. La règle écarte tout conteneur qui porte le libellé
   `portail.journaux=prives` : les exécutions comme leurs services (base, MinIO).
   Un service déjà en cours ne porte le libellé qu'une fois recréé.
2. **Vhost** du portail : recopier `deploy/nginx/portail.conf` dans le dépôt Infra
   (en-têtes de sécurité au niveau `server`, `location` des flux en direct sans tampon).
3. **Vérification après déploiement** : les conteneurs d'exécution n'ont pas de
   nom stable, on cherche donc leur sortie et non leur nom. Lancer une exécution
   dont une commande affiche un marqueur unique (par exemple
   `echo fuite-loki-2f9c`), puis vérifier dans Loki que
   `{container=~".+"} |= "fuite-loki-2f9c"` ne renvoie rien. Pour prouver que la
   requête aurait vu une fuite, la refaire avec un marqueur affiché par un
   conteneur sans le libellé : elle doit alors le trouver.
4. **Lanceur durci** : il tourne avec `cap_drop: ALL` et `read_only`. Au premier
   déploiement, vérifier que son `/health` répond et qu'une exécution démarre
   (accès au socket Docker) ; sinon, retirer `cap_drop` du lanceur seul.
5. **Vérification du vhost** (`nginx -t` échoue ici : `include` et certificat absents) :
   après la PR Infra, la page Chat s'affiche sans erreur CSP dans la console, et
   une réponse de l'orchestrateur arrive au fil de l'eau (pas d'un bloc à la fin).
