from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension
from mcp.server.request_state import RequestStateBoundary
from mcp_types import CallToolRequestParams
from pydantic import BaseModel, Field

EXT_ID = "io.modelcontextprotocol/files"
MAX_INLINE = 1048576
X_MCP_FILE = {"accept": ["application/pdf", "image/*", ".md"], "maxSize": 157286400}


class FileInput(BaseModel):
    """`FileInput` du brouillon (commit 8a859b8) ; `digest` requis en plus (spec §6.2)."""

    id: str = Field(min_length=1, max_length=128)
    mimeType: str
    size: int = Field(ge=0)
    digest: str  # sha-256 base64url sans remplissage (server.digest.sha256_b64url)
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

    def settings(self) -> dict[str, Any]:
        return {"upload": {}, "download": {}, "maxInlineBytes": MAX_INLINE}

    async def intercept_tool_call(
        self, params: CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        # Point d'accroche des Tasks 5 (-32021) et 6 (upload_required).
        return await call_next(ctx)


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
