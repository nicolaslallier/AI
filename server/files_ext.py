import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.request_state import RequestStateBoundary
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolRequestParams
from pydantic import BaseModel, Field, ValidationError

if TYPE_CHECKING:
    from server.transfers import TransferStore
    from server.vault import Vault

EXT_ID = "io.modelcontextprotocol/files"
MAX_INLINE = 1048576
X_MCP_FILE = {"accept": ["application/pdf", "image/*", ".md"], "maxSize": 157286400}


class Digest(BaseModel):
    algorithm: Literal["sha-256"]
    value: str  # base64url sans remplissage (server.digest.digest_obj)


class FileInput(BaseModel):
    """`FileInput` du brouillon (commit 8a859b8) ; `digest` requis en plus (spec §6.2)."""

    id: str = Field(min_length=1, max_length=128)
    mimeType: str
    size: int = Field(ge=0)
    digest: Digest
    name: str | None = None
    data: str | None = None  # base64 ; absent et size > 0 = envoi hors bande


def accepts(name: str, mime: str, accept: list[str]) -> bool:
    """Type exact, joker `type/*`, ou extension `.ext` sur le nom (sans tenir compte de la casse)."""
    mime, name = mime.lower(), name.lower()
    for a in map(str.lower, accept):
        if a.startswith("."):
            if name.endswith(a):
                return True
        elif a.endswith("/*"):
            if mime.startswith(a[:-1]):
                return True
        elif mime == a:
            return True
    return False


def client_file_caps(ctx: ServerRequestContext[Any, Any]) -> set[str]:
    caps = ctx.session.client_capabilities
    ext = (caps.extensions or {}).get(EXT_ID) if caps else None
    return {"upload", "download"} & set(ext or ())


class FilesExtension(Extension):
    identifier = EXT_ID

    def __init__(self, vault: "Vault | None" = None, store: "TransferStore | None" = None):
        self.vault, self.store = vault, store

    def settings(self) -> dict[str, Any]:
        return {"upload": {}, "download": {}, "maxInlineBytes": MAX_INLINE}

    async def intercept_tool_call(
        self, params: CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        if params.name != "vault_import_file":
            return await call_next(ctx)
        args = params.arguments or {}
        try:
            f = FileInput.model_validate(args.get("file"))
        except ValidationError:
            return await call_next(ctx)  # l'outil refuse proprement (isError), jamais de TypeError ici
        dossier, note = args.get("dossier", "00 - Inbox"), args.get("note_liée")
        if f.data is not None or f.size == 0 or not isinstance(dossier, str) or not isinstance(note, str | None):
            return await call_next(ctx)
        if "upload" not in client_file_caps(ctx):
            raise MCPError(
                code=-32021,
                message="Le client doit déclarer la capacité `upload` (extension files) ou utiliser vault_import_base64",
            )
        state = (ctx.params or {}).get("requestState")  # déjà vérifié et désemballé par la frontière du SDK
        if state is None:
            return self._demander_upload(f, dossier, note)
        return await self._terminer_upload(state, f, dossier, note)

    def _demander_upload(self, f: FileInput, dossier: str, note: str | None) -> dict[str, Any]:
        name = f.name or ""
        if not accepts(name, f.mimeType, X_MCP_FILE["accept"]):
            return _erreur(f"Type de fichier refusé : {f.mimeType} ({name or 'sans nom'})")
        if f.size > X_MCP_FILE["maxSize"]:
            return _erreur(f"Fichier trop gros (> {X_MCP_FILE['maxSize']} octets)")
        try:  # refuser avant le transfert ce qui échouerait à la relance
            self.vault.safe(f"{dossier}/Pièces jointes")
            self.vault.note_target(note)
        except ValueError as e:
            return _erreur(str(e))
        t = self.store.new_upload(f.size, f.digest.value, f.id)
        expires = datetime.fromtimestamp(t.expires_at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "resultType": "upload_required",
            "uploads": [{"fileId": f.id, "path": f"/uploads/{t.jeton}", "method": "PUT",
                         "credentials": "include", "expiresAt": expires}],
            "requestState": json.dumps({"jeton": t.jeton}),
        }

    async def _terminer_upload(self, state: str, f: FileInput, dossier: str, note: str | None) -> dict[str, Any]:
        from server.tools import import_bytes  # import circulaire : tools importe ce module

        try:
            jeton = json.loads(state)["jeton"]
        except (ValueError, TypeError, KeyError):
            raise MCPError(code=-32602, message="requestState invalide") from None
        self.store.sweep()
        t = self.store.upload(jeton)
        if t is None:
            raise MCPError(code=-32602, message="Téléversement inconnu ou expiré")
        if not t.done:
            return _erreur("Téléversement pas terminé : faites le PUT, puis relancez avec le même requestState")
        if not self.store.consume(jeton):
            raise MCPError(code=-32602, message="requestState déjà utilisé")
        try:  # consommé avant d'écrire : l'import n'est pas idempotent
            res = await import_bytes(self.vault, t.staged, f.name or "", f.mimeType, dossier, note)
        except (ToolError, ValueError, OSError) as e:
            return _erreur(str(e))
        return {"resultType": "complete", "isError": False, "structuredContent": res,
                "content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}


def _erreur(msg: str) -> dict[str, Any]:
    return {"resultType": "complete", "isError": True, "content": [{"type": "text", "text": msg}]}


class SealUploadRequired:
    """Middleware à placer *dans* la `RequestStateBoundary` du SDK.

    La frontière ne scelle que les résultats `input_required` ; ce middleware scelle aussi
    `upload_required` avec `boundary._seal` (méthode privée, d'où `mcp==2.3.0` épinglé).
    La relance n'a besoin de rien : la frontière vérifie tout `requestState` entrant.
    Il cache aussi les outils `x-mcp-file` aux clients qui n'ont pas déclaré `upload`.
    """

    def __init__(self, boundary: RequestStateBoundary):
        self._boundary = boundary

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        result = await call_next(ctx)
        if not isinstance(result, dict):  # le runner sérialise avant les middlewares
            return result
        if ctx.method == "tools/call" and result.get("resultType") == "upload_required":
            state = result.get("requestState")
            if isinstance(state, str):
                return {**result, "requestState": self._boundary._seal(ctx, state)}
        elif ctx.method == "tools/list" and "upload" not in client_file_caps(ctx):
            tools = [t for t in result.get("tools", []) if not _is_file_tool(t)]
            return {**result, "tools": tools}
        return result


def _is_file_tool(tool: dict[str, Any]) -> bool:
    props = (tool.get("inputSchema") or {}).get("properties") or {}
    return any(isinstance(p, dict) and "x-mcp-file" in p for p in props.values())
