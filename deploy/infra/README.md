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
   L'absence d'erreur CSP ne prouve pas que l'en-tête est là (un `add_header` dans un
   snippet inclus par un `location` annule ceux du `server`) : vérifier avec
   `curl -sI https://<hôte du portail>/ | grep -i content-security-policy`.
   Refaire aussi le parcours de connexion complet (session expirée, retour par
   Keycloak) : `form-action 'self'` s'applique aux redirections qui suivent un
   formulaire, donc au bouton de `/oauth2/sign_in`. S'il est bloqué, activer
   `skip_provider_button` ou ajouter l'hôte Keycloak à `form-action`.

# PR Infra du lot G (monitoring)

Sans cette PR, `/metrics` répond sur `infra-net` sans être lu : rien ne casse. Elle recopie :

1. `monitoring/prometheus/prometheus.yml` : un job `portail` avec `metrics_path: /metrics` et
   `static_configs: [{targets: ["portail:8000"]}]` (le service `portail` est sur `infra-net`,
   comme pour le vhost).
2. Les quatre `deploy/grafana/portail-*.json` vers `monitoring/grafana/provisioning/dashboards/json/`.
3. `deploy/grafana/alertes-portail.yml` vers `monitoring/grafana/provisioning/alerting/portail.yml`
   (la politique par défaut de l'Infra les envoie au point de contact `ntfy`). Le portail
   injoignable est déjà couvert par la règle `infra-target-down`.
4. `deploy/nginx/portail.conf` vers `nginx/conf.d/` (bloc `location ^~ /metrics`).
5. **Vérifications après déploiement** :
   - la cible `portail` est `UP` dans Prometheus ;
   - `curl -sk -o /dev/null -w '%{http_code}' https://<hôte du portail>/metrics` rend `404` ;
   - les quatre tableaux s'affichent dans le dossier Infra, sans erreur de requête ;
   - les quatre règles sont visibles dans Alerting ;
   - Loki rend des lignes JSON avec `{container=~"portail-portail.*"} | json | agent != ""` ;
   - cAdvisor expose bien `name=~"portail-.*"` ; sinon corriger le filtre des panneaux mémoire et
     CPU du tableau `portail-sante`.
