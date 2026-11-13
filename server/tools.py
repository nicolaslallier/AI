"""Outils MCP du coffre. Toute exception levée ici devient un résultat `isError: true`."""
import base64
import asyncio
import binascii
import os
import mimetypes
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import BlobResourceContents, EmbeddedResource
from pydantic import Field

from server.digest import digest_obj
from server.files_ext import MAX_INLINE, X_MCP_FILE, FileInput, accepts
from server.insurance import GABARIT, note_police, parse_police, texte_pdf
from server.vault import Vault, sanitize_name

EXTRAIT = 160


def mime_of(p: Path) -> str:
    return mimetypes.guess_type(p.name)[0] or ("text/markdown" if p.suffix == ".md" else "application/octet-stream")


def export_path(vault: Vault, chemin: str) -> Path:
    """Même confinement que vault_read_note (VaultPathError -> isError), sans la restriction .md."""
    p = vault.safe(chemin)
    if not p.is_file():
        raise ToolError(f"Fichier introuvable : {chemin}")
    return p


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
    vault.safe(dossier_pj)  # tout valider avant d'écrire : pas de fichier orphelin
    vault.note_target(note_liee)  # la note par défaut est sûre : dossier validé, nom assaini sans "."
    police = None
    if mime == "application/pdf" and not note_liee:  # une note_liée explicite garde le comportement générique
        try:
            modele = vault.safe(GABARIT).read_text(encoding="utf-8")  # avant d'écrire le PDF
        except (OSError, ValueError):
            modele = None  # sans modèle lisible : note générique
        if modele:
            police = parse_police(await asyncio.to_thread(texte_pdf, data))
    note_nom = os.path.splitext(sanitize_name(name))[0] + ".md"
    if police:
        vault.safe(f"{dossier}/{note_nom}")  # valider avant d'écrire : pas de fichier orphelin
    dest = await vault.write_unique(dossier_pj, name, data)
    if police:
        txt = note_police(police, modele, dest.name)
        note = await vault.write_unique(dossier, note_nom, txt.encode("utf-8"))
    else:
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
        # data absent et size > 0 : traité par FilesExtension.intercept_tool_call (upload_required)
        _verifier(file.name or "", file.mimeType, file.size)
        if len(file.data or "") > MAX_INLINE * 4 // 3 + 8:  # avant de décoder
            raise ToolError(f"Fichier trop gros (> {MAX_INLINE} octets) : utilisez l'envoi hors bande")
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

    @server.tool()
    def vault_export(chemin: str) -> list[EmbeddedResource]:
        """Exporte un fichier du coffre. Avec la capacité `download` (extension files), la réponse
        porte un lien de téléchargement ; sinon le fichier revient en ligne (limite 1 Mio)."""
        p = export_path(vault, chemin)
        if p.stat().st_size > MAX_INLINE:
            raise ToolError(f"Fichier trop gros pour l'export en ligne (> {MAX_INLINE} octets) : le client doit déclarer `download`")
        blob = base64.b64encode(p.read_bytes()).decode("ascii")
        return [EmbeddedResource(type="resource", resource=BlobResourceContents(
            uri=p.as_uri(), mimeType=mime_of(p), blob=blob))]
