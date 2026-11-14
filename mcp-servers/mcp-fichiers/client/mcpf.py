"""CLI `mcpf` : `put` envoie un fichier au serveur, `get` en rapatrie un (extension files)."""
import argparse
import asyncio
import mimetypes
import secrets
import sys
from pathlib import Path

import httpx

from client.rpc import EXT_ID, call
from server.digest import Sha256Stream

CHUNK = 1 << 20


class McpfError(Exception):
    pass


class IntegrityError(McpfError):
    pass


async def _tool(http, name: str, arguments: dict, caps: set[str], state: str | None = None) -> dict:
    params = {"name": name, "arguments": arguments, **({"requestState": state} if state else {})}
    msg = await call(http, "tools/call", params, caps)
    if "error" in msg:
        raise McpfError(f"Erreur du protocole {msg['error'].get('code')} : {msg['error'].get('message')}")
    res = msg["result"]
    if res.get("isError"):
        raise McpfError("Erreur de l'outil : " + " ".join(c.get("text", "") for c in res.get("content", [])))
    return res


def _digest(path: Path) -> dict:
    h = Sha256Stream()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.digest_obj()


async def _lire(path: Path):
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            yield chunk


async def put(http, fichier: Path, dossier: str = "00 - Inbox", note: str | None = None) -> dict:
    size = fichier.stat().st_size
    entree = {"id": secrets.token_hex(8), "name": fichier.name, "size": size, "digest": _digest(fichier),
              "mimeType": mimetypes.guess_type(fichier.name)[0] or "application/octet-stream"}
    arguments = {"file": entree, "dossier": dossier, **({"note_liée": note} if note else {})}
    r = await _tool(http, "vault_import_file", arguments, {"upload"})
    if r.get("resultType") != "upload_required":
        return r
    cible = "/mcp" + r["uploads"][0]["path"]
    # ponytail: le jeton est à usage unique, pas de reprise automatique après un échec du PUT
    p = await http.put(cible, content=_lire(fichier), headers={"Content-Length": str(size)}, follow_redirects=False)
    if p.status_code != 204:
        raise McpfError(f"PUT refusé (HTTP {p.status_code}) : {p.text[:200]}. Relancez la commande.")
    return await _tool(http, "vault_import_file", arguments, {"upload"}, r["requestState"])  # mêmes arguments


async def get(http, chemin: str, sortie: Path) -> Path:
    r = await _tool(http, "vault_export", {"chemin": chemin}, {"download"})
    d = r["_meta"][EXT_ID]["downloads"][0]
    part = sortie.with_name(sortie.name + ".part")
    h, n = Sha256Stream(), 0
    try:
        async with http.stream("GET", "/mcp" + d["path"], follow_redirects=False) as g:
            if g.status_code != 200:
                raise McpfError(f"Téléchargement refusé (HTTP {g.status_code})")
            with part.open("wb") as f:
                async for chunk in g.aiter_bytes(CHUNK):
                    f.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
        if n != d["size"] or h.b64url() != d["digest"]["value"]:
            raise IntegrityError(f"Fichier corrompu : {n} octets reçus sur {d['size']}, digest différent")
        part.replace(sortie)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return sortie


async def _run(args) -> None:
    async with httpx.AsyncClient(base_url=args.url, timeout=None) as http:
        if args.cmd == "put":
            r = await put(http, args.fichier, args.dossier, args.note)
            print("Importé :", r.get("structuredContent", r))
        else:
            print("Téléchargé :", await get(http, args.chemin, args.sortie or Path(Path(args.chemin).name)))


def main() -> None:
    ap = argparse.ArgumentParser(prog="mcpf", description="Client de l'extension files du serveur MCP Fichiers")
    ap.add_argument("--url", default="http://127.0.0.1:8765", help="adresse du serveur")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("put", help="envoyer un fichier dans le coffre")
    p.add_argument("fichier", type=Path)
    p.add_argument("--dossier", default="00 - Inbox", help="dossier du coffre (défaut : 00 - Inbox)")
    p.add_argument("--note", help="note à laquelle lier le fichier")
    g = sub.add_parser("get", help="télécharger un fichier du coffre")
    g.add_argument("chemin", help="chemin dans le coffre")
    g.add_argument("-o", "--sortie", type=Path, help="fichier de sortie (défaut : nom du fichier)")
    try:
        asyncio.run(_run(ap.parse_args()))
    except (McpfError, httpx.HTTPError, OSError) as e:
        sys.exit(f"mcpf : {e}")
