"""Outils MCP du coffre. Toute exception levée ici devient un résultat `isError: true`."""
import base64
import binascii
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from server.digest import digest_obj
from server.files_ext import MAX_INLINE, X_MCP_FILE, FileInput, accepts
from server.vault import Vault

EXTRAIT = 160


def _verifier(name: str, mime: str, size: int) -> None:
    if not accepts(name, mime, X_MCP_FILE["accept"]):
        raise ToolError(f"Type de fichier refusé : {mime} ({name or 'sans nom'})")
    if size > MAX_INLINE:
        raise ToolError(f"Fichier trop gros pour l'envoi en ligne (> {MAX_INLINE} octets) : utilisez l'envoi hors bande")


async def import_bytes(
    vault: Vault, data: bytes | Path, name: str, mime: str, dossier: str, note_liee: str | None
) -> dict[str, str]:
    """Écrit dans `<dossier>/Pièces jointes/` sans écraser, lie à une note. Utilisé par les Tasks 6, 8 et 9."""
    dossier_pj = f"{dossier}/Pièces jointes"
    dest = await vault.write_unique(dossier_pj, name, data)
    note = vault.attach(note_liee, dossier_pj, dest)
    return {"fichier": dest.relative_to(vault.root).as_posix(), "note": note.relative_to(vault.root).as_posix()}


def register_tools(server: MCPServer, vault: Vault, store) -> None:
    @server.tool()
    def vault_search(query: str, limit: int = 10) -> list[dict[str, str]]:
        """Cherche (sans tenir compte de la casse) dans les notes .md du coffre."""
        q, out = query.lower(), []
        for p in sorted(vault.root.rglob("*.md")):
            rel = p.relative_to(vault.root)
            if any(c.startswith(".") for c in rel.parts) or not p.is_file():
                continue
            try:
                vault.safe(rel.as_posix())  # lien sortant du coffre ou vers un dossier caché
            except ValueError:
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
        if not chemin.endswith(".md"):
            raise ToolError(f"Seules les notes .md se lisent : {chemin}")
        p = vault.safe(chemin)  # VaultPathError -> isError
        if not p.is_file():
            raise FileNotFoundError(f"Note introuvable : {chemin}")
        return p.read_text(encoding="utf-8")

    @server.tool()
    async def vault_import_file(
        file: Annotated[FileInput, Field(json_schema_extra={"x-mcp-file": X_MCP_FILE})],
        dossier: str = "00 - Inbox",
        note_liée: str | None = None,
    ) -> dict[str, str]:
        """Importe un fichier dans `<dossier>/Pièces jointes/` et le lie à une note."""
        if file.data is None and file.size > 0:
            raise ToolError("Envoi hors bande pas encore pris en charge")  # Task 6
        _verifier(file.name or "", file.mimeType, file.size)
        try:
            data = base64.b64decode(file.data or "", validate=True)
        except binascii.Error as e:
            raise ToolError("Données base64 invalides") from e
        if len(data) != file.size or digest_obj(data) != file.digest.model_dump():
            raise ToolError("Taille ou digest ne correspondent pas aux données")
        return await import_bytes(vault, data, file.name or "", file.mimeType, dossier, note_liée)

    @server.tool()
    async def vault_import_base64(
        name: str, mimeType: str, data_base64: str, dossier: str = "00 - Inbox", note_liée: str | None = None
    ) -> dict[str, str]:
        """Comme vault_import_file, pour les clients sans l'extension files (limite 1 Mio)."""
        if len(data_base64) > MAX_INLINE * 4 // 3 + 8:  # avant de décoder
            raise ToolError(f"Fichier trop gros (> {MAX_INLINE} octets) : utilisez l'envoi hors bande")
        try:
            data = base64.b64decode(data_base64, validate=True)
        except binascii.Error as e:
            raise ToolError("Données base64 invalides") from e
        _verifier(name, mimeType, len(data))
        return await import_bytes(vault, data, name, mimeType, dossier, note_liée)
