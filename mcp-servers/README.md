# Serveurs MCP

Un serveur par sous-dossier : `mcp-servers/<nom>/`, avec :

- `README.md` : ce qu'il expose (outils, ressources), comment le lancer, et le bloc
  de configuration à coller dans `.mcp.json` / la config du client
- ses dépendances (`pyproject.toml` + `uv.lock` avec le SDK `mcp`, ou `package.json`)
- `.env.example` si le serveur a besoin de clés ou d'adresses
- ses tests

Un outil qui écrit ou supprime le dit dans sa description et dans ses annotations :
c'est ce que le client montre à la personne qui doit approuver l'appel.
