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
    staging = vault.root / ".staging"
    if staging.is_symlink() or (staging.exists() and staging.resolve().parent != vault.root):
        raise RuntimeError(f"{staging} est un lien symbolique ou sort du coffre : démarrage refusé")
    staging.mkdir(exist_ok=True)
    for f in staging.iterdir():  # les jetons sont en mémoire : rien n'y survit à un redémarrage
        if f.is_symlink() or f.is_file():  # un lien est supprimé en tant que lien, jamais suivi
            f.unlink()
    store = TransferStore(staging, transfer_ttl)
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
    import argparse
    import sys

    import uvicorn

    ap = argparse.ArgumentParser(prog="python -m server.app")
    ap.add_argument("--vault", type=Path, default=Path("vault-test"), help="racine du coffre (défaut : vault-test)")
    racine = ap.parse_args().vault
    if not racine.is_dir():
        sys.exit(f"Coffre introuvable : {racine} (copiez-le d'abord, voir le README)")
    uvicorn.run(create_app(racine), host="127.0.0.1", port=8765)
