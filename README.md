# MCP Fichiers

Serveur MCP (Python) qui implémente l'extension expérimentale `io.modelcontextprotocol/files`
sur une copie d'un coffre Obsidian.

## Brouillon de l'extension (commit `8a859b8`, `specification/draft/file-uploads.md`)

- Digest : sha-256 en base64url, **sans remplissage `=`** (« base64url, no padding »).
- `FileInput` : champs requis `id` (1 à 128 caractères), `mimeType`, `size` (entier >= 0).
  Optionnels : `name`, `digest {algorithm: "sha-256", value}`, `data` (base64 RFC 4648 ; absent et `size > 0` = envoi hors bande).
- `x-mcp-file` (`FileInputDescriptor`) : `accept?`, `maxSize?`.

## Développement

```
uv sync
uv run pytest -q
cp -R ~/Obsidian/Maison vault-test   # copie de travail, ignorée par git
uv run python -m server.app          # http://127.0.0.1:8765/mcp
```
