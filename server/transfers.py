"""Jetons de transfert hors bande (en mémoire) et route `PUT /mcp/uploads/{jeton}`."""
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response, StreamingResponse

from server.digest import Sha256Stream


@dataclass
class UploadTicket:
    jeton: str
    file_id: str
    size: int
    digest: str  # base64url, comme Digest.value
    expires_at: float
    staged: Path
    done: bool = False
    written: bool = False


@dataclass
class DownloadTicket:
    jeton: str
    path: Path
    size: int
    expires_at: float


class TransferStore:
    def __init__(self, staging: Path, ttl: float):
        self.staging, self.ttl = Path(staging), ttl
        self._uploads: dict[str, UploadTicket] = {}
        self._downloads: dict[str, DownloadTicket] = {}
        self._consumed: set[str] = set()

    def new_upload(self, size: int, digest: str, file_id: str) -> UploadTicket:
        self.sweep()
        self.staging.mkdir(exist_ok=True)
        jeton = secrets.token_urlsafe(32)
        t = UploadTicket(jeton, file_id, size, digest, time.time() + self.ttl, self.staging / jeton)
        self._uploads[jeton] = t
        return t

    def new_download(self, path: Path) -> DownloadTicket:
        self.sweep()
        jeton = secrets.token_urlsafe(32)
        t = DownloadTicket(jeton, Path(path), Path(path).stat().st_size, time.time() + self.ttl)
        self._downloads[jeton] = t
        return t

    def upload(self, jeton: str) -> UploadTicket | None:
        return self._uploads.get(jeton)

    def download(self, jeton: str) -> DownloadTicket | None:
        return self._downloads.get(jeton)

    def consume(self, jeton: str) -> bool:
        """Synchrone (pas d'await) : deux relances concurrentes ne peuvent pas passer toutes les deux."""
        if jeton in self._consumed:
            return False
        self._consumed.add(jeton)
        return True

    def sweep(self) -> None:
        now = time.time()
        for j, t in list(self._uploads.items()):
            if t.expires_at <= now:
                del self._uploads[j]
                self._consumed.discard(j)
                t.staged.unlink(missing_ok=True)
        for j, d in list(self._downloads.items()):
            if d.expires_at <= now:
                del self._downloads[j]


def register_routes(server: MCPServer, store: TransferStore) -> None:
    @server.custom_route("/mcp/uploads/{jeton}", methods=["PUT"])
    async def put_upload(request: Request) -> Response:
        t = store.upload(request.path_params["jeton"])
        store.sweep()  # après la recherche, pour distinguer expiré (410) d'inconnu (404)
        if t is None:
            return Response(status_code=404)
        if t.expires_at <= time.time():
            return Response(status_code=410)
        if t.written:
            return Response(status_code=409)
        cl = request.headers.get("content-length")
        if cl is None:
            return Response(status_code=411)
        if not (cl.isascii() and cl.isdigit()) or int(cl) != t.size:
            return Response(status_code=413)
        t.written = True  # usage unique, même si le corps est rejeté : le client recommence l'appel
        h, n, ok = Sha256Stream(), 0, False
        try:
            with open(t.staged, "xb") as f:
                async for chunk in request.stream():
                    n += len(chunk)
                    if n > t.size:  # jamais plus de size + 1 octets lus, jamais plus de size écrits
                        break
                    h.update(chunk)
                    f.write(chunk)
            ok = n == t.size and h.b64url() == t.digest
        except ClientDisconnect:
            pass
        finally:
            if not ok:
                t.staged.unlink(missing_ok=True)
        if not ok:
            return Response(status_code=400)
        if store.upload(t.jeton) is not t:  # balayé pendant le PUT (expiré) : rien ne reste
            t.staged.unlink(missing_ok=True)
            return Response(status_code=410)
        t.done = True
        return Response(status_code=204)

    @server.custom_route("/mcp/downloads/{jeton}", methods=["GET"])
    async def get_download(request: Request) -> Response:
        d = store.download(request.path_params["jeton"])
        store.sweep()
        if d is None:
            return Response(status_code=404)
        if d.expires_at <= time.time():
            return Response(status_code=410)
        rng = request.headers.get("range")
        if rng is None:
            return StreamingResponse(_lire(d.path, 0, d.size - 1), headers={
                "content-length": str(d.size), "accept-ranges": "bytes", "content-type": "application/octet-stream"})
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip()) if rng.isascii() else None
        start = end = None
        if m and (m[1] or m[2]):
            if m[1]:
                start, end = int(m[1]), min(int(m[2]) if m[2] else d.size - 1, d.size - 1)
            elif int(m[2]) > 0:  # suffixe : les n derniers octets
                start, end = max(0, d.size - int(m[2])), d.size - 1
        if start is None or start >= d.size or start > end:
            return Response(status_code=416, headers={"content-range": f"bytes */{d.size}"})
        return StreamingResponse(_lire(d.path, start, end), status_code=206, headers={
            "content-range": f"bytes {start}-{end}/{d.size}", "content-length": str(end - start + 1),
            "accept-ranges": "bytes", "content-type": "application/octet-stream"})


async def _lire(path: Path, start: int, end: int):
    """Lit [start, end] par blocs de 1 Mio (le fichier peut avoir changé : on s'arrête à la fin réelle)."""
    left = end - start + 1
    with open(path, "rb") as f:
        f.seek(start)
        while left > 0 and (chunk := f.read(min(1 << 20, left))):
            left -= len(chunk)
            yield chunk
