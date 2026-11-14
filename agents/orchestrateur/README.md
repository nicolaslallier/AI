# Orchestrateur

Programme Python qui prend une demande de développement (un texte ou une issue GitHub),
la découpe en tâches et la fait réaliser par quatre sous-agents, jusqu'à un changement
testé, relu et committé sur une branche à part. Il s'appuie sur le
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk), c'est-à-dire la boucle
et les outils de Claude Code, utilisés comme une bibliothèque.

Les agents sont définis dans les fichiers `.md` du dossier parent ; ce programme les lit,
et Claude Code peut s'en servir directement (voir plus bas).

| Agent | Modèle | Outils | Rôle |
|---|---|---|---|
| [`orchestrateur`](../orchestrateur.md) | `claude-opus-5-5` | Agent, lecture, outils d'état | planifie, délègue, suit l'état ; n'écrit jamais de code |
| [`explorateur`](../explorateur.md) | `claude-sonnet-5-5` | Read, Grep, Glob | comprend le code avant qu'on le change |
| [`codeur`](../codeur.md) | `claude-opus-5-5` | lecture, Edit, Write, Bash | réalise une tâche, ses tests, et la committe |
| [`testeur`](../testeur.md) | `claude-haiku-5-5` | lecture, Bash | lance les tests, rend `VERDICT: OK` ou `ECHEC` |
| [`relecteur`](../relecteur.md) | `claude-sonnet-5-5` | lecture, Bash | relit le diff, rend `VERDICT: OK` ou `A_CORRIGER` |

## Déroulé d'une exécution

1. Le programme vérifie que le dépôt cible n'a pas de modifications en cours, puis crée la
   branche `orchestrateur/<id>` depuis la branche courante.
2. L'orchestrateur explore si besoin, enregistre son plan (`plan_definir`), puis pour
   chaque tâche fait travailler le `codeur` et vérifier le `testeur` (3 essais au plus).
3. Le `relecteur` relit la branche entière ; ses remarques repartent au `codeur` (2 tours
   au plus).
4. Le programme affiche le rapport, le plan et le coût. Avec `--pr`, il pousse la branche
   et ouvre une PR en brouillon avec `gh`. Il ne fusionne jamais.

## Suivi d'état

Chaque exécution a son fichier `<dépôt>/.git/orchestrateur/<id>.json` : la demande, la
branche, le plan avec l'état de chaque tâche (`a_faire`, `en_cours`, `faite`, `echec`)
et son nombre d'essais, un journal horodaté, le coût et le rapport. Il est rangé dans
`.git/` pour n'être jamais committé.

L'orchestrateur le tient à jour lui-même, par trois outils MCP servis en mémoire par le
programme : `plan_definir`, `tache_maj` (ces deux-là écrivent dans ce fichier, jamais
dans le dépôt) et `etat_lire` (lecture seule). L'identifiant de session Claude y est
aussi, ce qui permet `--reprendre`.

## Installer

```bash
cd agents/orchestrateur
uv sync
cp .env.example .env   # puis remplir
```

Le SDK embarque Claude Code : rien d'autre à installer. Les variables de `.env` doivent
être dans l'environnement au lancement (`set -a; . ./.env; set +a`, ou `direnv`) :

| Variable | Valeur |
|---|---|
| `ANTHROPIC_BASE_URL` | `https://litellm.infra.famillelallier.net` pour passer par LiteLLM (usage visible dans Grafana) |
| `ANTHROPIC_AUTH_TOKEN` | la clé LiteLLM |
| `NODE_EXTRA_CA_CERTS` | à laisser vide : le programme prend [`certs/infra-ca.crt`](../../certs/) du dépôt |
| `GITHUB_TOKEN` | seulement pour `--issue` ; un jeton en lecture seule suffit |

LiteLLM doit exposer les modèles sous les noms utilisés ici (`claude-opus-5-5`,
`claude-sonnet-5-5`, `claude-haiku-5-5`). Pour changer celui d'un sous-agent, modifier le
champ `model` de son `.md` ; pour l'orchestrateur, `--modele` ou `ORCHESTRATEUR_MODELE`.

## Lancer

```bash
# d'abord à blanc : affiche agents, modèles, permissions et demande, sans rien toucher
uv run orchestrateur --a-blanc --depot ~/Code/AI "Ajouter un outil vault_list à mcp-fichiers"

# pour de vrai
uv run orchestrateur --depot ~/Code/AI "Ajouter un outil vault_list à mcp-fichiers"

# la demande vient d'une issue, et on ouvre une PR en brouillon à la fin
uv run orchestrateur --depot ~/Code/AI --issue nicolaslallier/AI#15 --pr

# lister les exécutions d'un dépôt, reprendre une exécution interrompue (Ctrl-C, budget, tours)
uv run orchestrateur --depot ~/Code/AI --liste
uv run orchestrateur --depot ~/Code/AI --reprendre 20261114-081500-ab12
```

| Option | Défaut | Effet |
|---|---|---|
| `--depot` | dossier courant | dépôt git cible |
| `--issue` | | lire la demande dans une issue (`proprio/depot#12` ou son URL) |
| `--budget-usd` | 10 | plafond de dépense de l'exécution |
| `--max-tours` | 150 | plafond de tours de l'orchestrateur |
| `--autoriser` | | règle d'outil en plus, ex. `"Bash(make test:*)"` (répétable) |
| `--pr` | non | pousser la branche et ouvrir une PR en brouillon à la fin |

### Lancer depuis une tâche planifiée

Pour traiter une issue sans être devant l'écran, par exemple chaque nuit sur les issues
étiquetées pour l'orchestrateur, une ligne cron suffit (une issue par ligne) :

```cron
0 2 * * * cd ~/Code/AI/agents/orchestrateur && set -a && . ./.env && set +a && uv run orchestrateur --depot ~/Code/AI --issue nicolaslallier/AI#15 --pr >> ~/orchestrateur.log 2>&1
```

## Permissions

Personne n'est là pour approuver pendant une exécution : le mode est `dontAsk`, qui
refuse tout outil non autorisé d'avance. Sont autorisés la lecture, l'édition, `git
status/diff/log/show/add/commit`, `uv sync`, `uv run`, `pytest`, `npm test` et `npm run`.
Sont toujours refusés `git push/checkout/switch/reset/rebase/merge`, `gh`, `WebFetch` et
`WebSearch` : seul le programme pousse, et seulement avec `--pr`.

Ce n'est pas un bac à sable : `uv run` et `npm run` exécutent du code du dépôt. Ne lancer
l'orchestrateur que sur ses propres dépôts. Seuls les réglages du dépôt cible
(`.claude/settings.json`, `CLAUDE.md`) sont chargés, pas ceux de `~/.claude`.

## Sans le programme, dans Claude Code

Les cinq `.md` marchent aussi dans Claude Code, sans suivi d'état ni branche créée
d'avance :

```bash
for a in orchestrateur explorateur codeur testeur relecteur; do
  ln -s "$PWD/agents/$a.md" ~/.claude/agents/
done
claude --agent orchestrateur   # depuis le dépôt à modifier, sur une branche à part
```

`--agent` en fait l'agent principal de la session : un sous-agent ne peut pas en appeler
d'autres, l'orchestrateur ne marche donc pas lancé depuis l'outil Agent.

## Tests

```bash
uv run pytest -q
```

Les tests n'appellent aucun modèle : ils couvrent la lecture des `.md`, le fichier d'état
et ses outils MCP, les opérations git, la lecture d'une issue et les options passées au
SDK.
