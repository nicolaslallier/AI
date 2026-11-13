# AI : mes outils IA

Dépôt de mes outils IA : serveurs MCP, définitions d'agents, skills, prompts et scripts.

> L'ancien labo MLX (fine-tuning LoRA et RAG, jalons M0 à M4) est archivé sous le tag
> [`archive/labo-mlx`](https://github.com/nicolaslallier/AI/tree/archive/labo-mlx).
> `git checkout archive/labo-mlx` le ramène tel qu'il était.

## Structure

| Dossier | Contenu |
|---|---|
| [`mcp-servers/`](mcp-servers/) | Un serveur MCP par sous-dossier, autonome (ses dépendances, son README) |
| [`agents/`](agents/) | Définitions d'agents et de sous-agents Claude Code (`.md` avec frontmatter) |
| [`skills/`](skills/) | Skills réutilisables (`<nom>/SKILL.md` + fichiers) |
| [`prompts/`](prompts/) | Prompts et gabarits réutilisables |
| [`scripts/`](scripts/) | Petits scripts autonomes (CLI, utilitaires Ollama, LiteLLM, etc.) |

## Index des outils

| Outil | Type | Description |
|---|---|---|
| _(vide pour l'instant)_ | | |

Chaque nouvel outil ajoute sa ligne ici, dans la même PR que l'outil.

## Conventions

- **Un outil = un dossier autonome.** Il porte ses propres dépendances
  (`pyproject.toml` + `uv.lock`, ou `package.json` + lockfile) et un `README.md` qui
  dit à quoi il sert, comment l'installer et comment le lancer. Aucun outil n'en
  importe un autre.
- **Aucun secret dans le dépôt.** Les clés vont dans un `.env` ignoré par git ; on
  committe un `.env.example` aux valeurs vides.
- **Modèles locaux par défaut.** Les outils qui appellent un LLM passent par la
  passerelle LiteLLM de l'Infra (`https://litellm.infra.famillelallier.net`) ou par
  Ollama, l'adresse étant une variable d'environnement, jamais une constante.
