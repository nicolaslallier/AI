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
   - un chat en flux est essayé et `appel_llm` reçoit des jetons non nuls (sinon LiteLLM ne renvoie
     pas l'usage en flux) ;
   - cAdvisor expose bien `name=~"portail-.*"` ; sinon corriger le filtre des panneaux mémoire et
     CPU du tableau `portail-sante`.

# Lot I (un conteneur par agent) : étapes manuelles

À faire AVANT de fusionner la tâche 11 dans `main` (sinon le déploiement échoue sur les `:?`) :

1. Ranger dans OpenBao, dans le secret `infra/portail` (chemin de la pile `infra/data/portail`), une clé par agent
   `PORTAIL_AGENT_SECRET_<NOM>` : `SPEC`, `ORCHESTRATEUR`, `PLAN`, `TACHES`, `TESTS`, `CODE`,
   `REVUE`, `ARCHITECTE`, `CHALLENGER`, `SECURITE`, `DOC`, `PM`, `TRI` (13 clés). Chacune
   vient de `openssl rand -hex 32` (le script de rendu refuse un secret de moins de 32 caractères).
2. Ajouter le contrôle `agents` à la protection de la branche `main` (réglage GitHub, non
   modifié par le dépôt).
3. Après la fusion, ouvrir la PR Infra : recopier `deploy/nginx/portail.conf` (bloc
   `location ^~ /interne { return 404; }`). Sans elle, `/interne/` passe par `location /`
   derrière oauth2-proxy : pas exposé sans session, mais le 404 voulu manque.
   Vérifier ensuite :
   - `curl -sk -o /dev/null -w '%{http_code}' -X POST https://portail.infra.famillelallier.net/interne/modele` rend `404` ;
   - Loki rend des lignes JSON pour `{container=~"portail-agent-.*"} | json | agent != ""` (Alloy les ramasse déjà, rien à ajouter) ;
   - `docker network inspect portail_portail-agents` ne liste que `portail` et les `agent-*`.
4. Décider, agent par agent, de poser `service:` dans `agents.yaml` (procédure et retour arrière :
   section « Agents en conteneur » du README ; aucun agent ne migre dans ce lot).

5. Avant de poser le premier `service:` :
   - Depuis un conteneur de test attaché à `portail_portail-agents`, `nc -zv 10.250.250.1 22`
     (et chaque autre port ouvert de l'hôte) doit échouer : un réseau `internal: true` peut
     garder l'adresse de passerelle sur le pont de l'hôte, donc exposer ses services. Si c'est
     ouvert : `driver_opts: {com.docker.network.bridge.inhibit_ipv4: "true"}` sur
     `portail-agents`, ou une règle INPUT DROP sur ce pont.
   - Le paquet GHCR `ai-agents` est peut-être privé par défaut : Portainer et Trivy doivent
     pouvoir le tirer (le rendre public, ou leur donner un accès en lecture).

Les services `agent-<nom>` sont tous sur le réseau `portail-agents` (interne) : ils voient le
portail, pas l'Infra, ni la base, ni LiteLLM, ni le lanceur, ni Internet. Ils partagent ce
réseau entre eux ; seul le secret propre à chaque agent les empêche de se parler utilement.

Le sous-réseau `10.250.250.0/24` de `portail-agents` est réservé ; s'il entre en collision, le changer aux deux endroits de `deploy/portainer-stack.yml` (`ipam` et `PORTAIL_RESEAU_AGENTS`) et dans le README principal.

# agent-doc (jeton de service)

Toutes ces étapes sont faites par Nicolas, dans cet ordre :

1. `openssl rand -hex 32` ; ranger la valeur dans OpenBao : `infra/portail` clé
   `PORTAIL_JETON_SERVICE`, et `infra/env` clé `AGENT_DOC_PORTAIL_JETON` (même valeur).
2. Fusionner la PR du Portail (le Portail se redéploie).
3. Recopier `deploy/nginx/portail.conf` dans l'Infra (plan 3 du projet 2, tâche 9).
4. Clé locale : après `make litellm-provision` dans l'Infra (plan 3 du projet 2, tâche 1), ranger
   la clé `portail-agents` dans `infra/portail`, clé `PORTAIL_LITELLM_CLE_AGENTS`, puis
   redéployer le Portail ; vérifier que la page Musique répond toujours. C'est seulement après
   cela que l'Infra retire `apps` d'agent-musique (plan 5).
5. Vérifier :
   - `curl -sk -o /dev/null -w '%{http_code}' -X POST https://portail.infra.famillelallier.net/service/taches-doc` rend `404` ;
   - depuis un conteneur d'`infra-net`, le même `POST` sur `http://portail:8000/service/taches-doc`
     sans jeton rend `401`, et avec le jeton et un dépôt qui a un projet, `201` avec un lien ;
     la tâche apparaît dans la colonne « Prête » puis part en exécution.
