"""Outils MCP du coffre. Toute exception levée ici devient un résultat `isError: true`."""
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.files_ext import X_MCP_FILE, FileInput

from server.vault import Vault

EXTRAIT = 160


def register_tools(server: MCPServer, vault: Vault, store) -> None:
    @server.tool()
    def vault_search(query: str, limit: int = 10) -> list[dict[str, str]]:
        """Cherche (sans tenir compte de la casse) dans les notes .md du coffre."""
        q, out = query.lower(), []
        for p in sorted(vault.root.rglob("*.md")):
            rel = p.relative_to(vault.root)
            if any(c.startswith(".") for c in rel.parts) or not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            i = text.lower().find(q)
            if i < 0:
                continue
            start = max(0, i - (EXTRAIT - len(q)) // 2)
            out.append({"chemin": rel.as_posix(), "extrait": text[start : start + EXTRAIT]})
            if len(out) >= limit:
                break
        return out

    @server.tool()
    def vault_read_note(chemin: str) -> str:
        """Lit une note du coffre."""
        p = vault.resolve(chemin)  # VaultPathError -> isError
        if not p.is_file():
            raise FileNotFoundError(f"Note introuvable : {chemin}")
        return p.read_text(encoding="utf-8")

    @server.tool()
    def vault_import_file(
        file: Annotated[FileInput, Field(json_schema_extra={"x-mcp-file": X_MCP_FILE})],
        dossier: str = "00 - Inbox",
        note_liée: str | None = None,
    ) -> dict[str, str]:
        """Importe un fichier dans `<dossier>/Pièces jointes/` et le lie à une note."""
        raise NotImplementedError("vault_import_file : Task 5")

    @server.tool()
    def vault_import_base64(
        name: str, mimeType: str, data_base64: str, dossier: str = "00 - Inbox", note_liée: str | None = None
    ) -> dict[str, str]:
        """Comme vault_import_file, pour les clients sans l'extension files (limite 1 Mio)."""
        raise NotImplementedError("vault_import_base64 : Task 5")
