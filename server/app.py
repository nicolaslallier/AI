from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.request_state import RequestStateBoundary, RequestStateSecurity
from starlette.applications import Starlette

from server.files_ext import FilesExtension, SealUploadRequired
from server.tools import register_tools
from server.transfers import TransferStore, register_routes
from server.vault import Vault


def create_server(vault_root: Path, *, state_ttl: float = 1800, transfer_ttl: float = 900) -> MCPServer:
    vault = Vault(vault_root)
    store = TransferStore(vault.root / ".staging", transfer_ttl)
    server = MCPServer(
        "mcp-fichiers",
        extensions=[FilesExtension(vault, store)],
        request_state_security=RequestStateSecurity.ephemeral(ttl=state_ttl),
    )
    # Ajouté après la construction : la frontière n'existe qu'ensuite, et la fin de la liste
    # (ordre extérieur → intérieur) place le middleware dans la frontière, qui voit alors son sceau.
    boundary = next(m for m in server.middleware if isinstance(m, RequestStateBoundary))
    server.middleware.append(SealUploadRequired(boundary))
    register_tools(server, vault, store)
    register_routes(server, store)
    return server


def create_app(vault_root: Path, **kw) -> Starlette:
    app = create_server(vault_root, **kw).streamable_http_app()
    app.router.redirect_slashes = False  # jamais de 3xx (ex. PUT /mcp/uploads/x/)
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(Path("vault-test")), host="127.0.0.1", port=8765)
