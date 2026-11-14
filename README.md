# AI

Mes outils IA, au même endroit : serveurs MCP, agents et skills pour Claude Code,
prompts et scripts. Tout est pensé pour tourner sur mes machines et sur la stack
[Infra](https://github.com/nicolaslallier/Infra) (LiteLLM, Ollama), sans dépendre
d'un service tiers quand un modèle local suffit.

## Ce qu'il y a dedans

| Dossier | Contenu | Où ça s'installe |
|---|---|---|
| [`mcp-servers/`](mcp-servers/) | Un serveur MCP par sous-dossier | `.mcp.json` d'un projet, ou `claude mcp add` |
| [`agents/`](agents/) | Agents et sous-agents Claude Code (`<nom>.md`) | `~/.claude/agents/` |
| [`skills/`](skills/) | Skills (`<nom>/SKILL.md` + fichiers) | `~/.claude/skills/` |
| [`prompts/`](prompts/) | Prompts et gabarits réutilisables | à copier où on en a besoin |
| [`scripts/`](scripts/) | Petits scripts autonomes | à lancer depuis le dépôt |

### Index des outils

| Outil | Type | À quoi il sert |
|---|---|---|
| [`mcp-fichiers`](mcp-servers/mcp-fichiers/) | Serveur MCP (HTTP) | Déposer des fichiers dans une copie d'un coffre Obsidian et en ressortir, avec l'extension expérimentale `io.modelcontextprotocol/files` ; client `mcpf` |
| [`orchestrateur`](agents/orchestrateur/) | Agent (programme, Claude Agent SDK) | Découpe une demande de développement (texte ou issue GitHub) et la fait réaliser par les sous-agents [`explorateur`, `codeur`, `testeur`, `relecteur`](agents/) sur une branche à part, avec suivi d'état et reprise |

Chaque outil ajoute sa ligne ici, dans la même PR que l'outil lui-même.

## Démarrage rapide

```bash
git clone https://github.com/nicolaslallier/AI.git ~/OpenCode/AI
cd ~/OpenCode/AI
```

Les agents et les skills s'installent par **lien symbolique**, pour qu'un
`git pull` suffise à les mettre à jour :

```bash
mkdir -p ~/.claude/agents ~/.claude/skills
ln -s "$PWD/agents/<nom>.md" ~/.claude/agents/
ln -s "$PWD/skills/<nom>"    ~/.claude/skills/
```

Un serveur MCP se lance comme son README l'indique ; pour le brancher dans
Claude Code :

```bash
claude mcp add <nom> -- uv run --directory "$PWD/mcp-servers/<nom>" <commande>
```

## Modèles disponibles

Les outils n'écrivent jamais une adresse en dur : elle vient d'une variable
d'environnement, avec ces valeurs pour le réseau de la maison.

| Service | Adresse | Variable conseillée |
|---|---|---|
| LiteLLM (API OpenAI et Anthropic) | `https://litellm.infra.famillelallier.net` | `LITELLM_BASE_URL`, `LITELLM_API_KEY` |
| Ollama (via le proxy de métriques) | `https://ollama.infra.famillelallier.net` | `OLLAMA_URL` |

Passer par ces deux portes plutôt que d'appeler Ollama directement, c'est ce qui
fait apparaître l'usage dans les tableaux de bord Grafana de l'Infra. Le
certificat est celui de la CA locale de l'Infra (`certs/infra-ca.crt`) : un outil
Node a besoin de `NODE_EXTRA_CA_CERTS`, un outil Python de `SSL_CERT_FILE` ou
`REQUESTS_CA_BUNDLE`.

## Ajouter un outil

1. Un dossier à lui, dans le bon répertoire (`mcp-servers/<nom>/`, `skills/<nom>/`,
   `agents/<nom>.md`…).
2. Ses propres dépendances : `pyproject.toml` + `uv.lock` (Python, géré avec
   [`uv`](https://docs.astral.sh/uv/)) ou `package.json` + lockfile (Node). Aucun
   outil n'en importe un autre.
3. Un `README.md` qui dit à quoi il sert, comment l'installer et comment le lancer.
4. Un `.env.example` aux valeurs vides s'il lui faut des clés ou des adresses.
5. Ses tests, s'il a du code.
6. Sa ligne dans l'index ci-dessus.

Chaque répertoire a son propre README avec les conventions de son type d'outil.

## Règles

- **Aucun secret dans le dépôt.** Le dépôt est public. Les clés vont dans un `.env`
  ignoré par git ; seul le `.env.example` est committé.
- **Un outil MCP qui écrit ou supprime le dit**, dans sa description et dans ses
  annotations : c'est ce que le client montre à la personne qui doit approuver
  l'appel.
- **Tout passe par une PR**, comme dans les autres dépôts du projet.

## Historique

Jusqu'en novembre 2026, ce dépôt était un labo MLX qui comparait un modèle de base,
le RAG et le fine-tuning LoRA (jalons M0 à M4). Il est conservé tel quel au commit
[`2775323`](https://github.com/nicolaslallier/AI/tree/2775323), aussi
étiqueté `archive/labo-mlx`.
