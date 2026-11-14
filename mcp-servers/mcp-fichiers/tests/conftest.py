import asyncio
import base64
import contextlib

import httpx
import pytest
from httpx import ASGITransport

from server.app import create_app


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "00 - Inbox").mkdir()
    return tmp_path


@contextlib.asynccontextmanager
async def running(app):
    # ASGITransport ne lance pas le lifespan Starlette : on le tient dans une tâche dédiée
    # (anyio exige d'entrer et sortir du cancel scope dans la même tâche).
    ready, stop = asyncio.Event(), asyncio.Event()

    async def run():
        async with app.router.lifespan_context(app):
            ready.set()
            await stop.wait()

    task = asyncio.create_task(run())
    await ready.wait()
    try:
        yield app
    finally:
        stop.set()
        await task


def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app), base_url="http://127.0.0.1:8765")


@pytest.fixture
async def app(vault):
    async with running(create_app(vault)) as a:
        yield a


@pytest.fixture
async def http(app):
    async with client(app) as c:
        yield c


def make_pdf(n_bytes: int = 0, texte: str | None = None) -> bytes:
    """PDF minimal, rembourré (commentaire `%` avant `xref`) jusqu'à `n_bytes`.
    Sans `texte` : sans page. Avec `texte` : une page Helvetica, une ligne `Tj` par ligne, lisible par pypdf."""
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>"] if texte is not None else [b"<</Type/Catalog>>"]
    if texte is not None:
        flux = b"BT /F1 12 Tf 14 TL 50 750 Td\n" + b"".join(
            b"(" + l.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b") Tj T*\n"
            for l in texte.split("\n")) + b"ET"
        objs += [b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
                 b"<</Length %d>>stream\n%s\nendstream" % (len(flux), flux),
                 b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>"]
    out, offs = b"%PDF-1.4\n", []
    for n, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj%s\nendobj\n" % (n, o)
    tail = b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    tail += b"".join(b"%010d 00000 n \n" % o for o in offs)
    tail += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n" % (len(objs) + 1)
    def fin(o: bytes) -> bytes:
        return o + tail + b"%d\n%%%%EOF\n" % len(o)

    if n_bytes:
        pad = max(0, n_bytes - len(fin(out)) - 2)
        pad += n_bytes - len(fin(out + b"%" + b"x" * pad + b"\n")) if pad else 0
        if pad:
            out += b"%" + b"x" * pad + b"\n"
    return fin(out)

def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def gabarit(vault) -> None:
    """Copie le modèle de note de ressource (fidèle à celui du coffre) dans vault/06 - Modèles/."""
    d = vault / "06 - Modèles"
    d.mkdir(exist_ok=True)
    (d / "Modèle - Note de ressource.md").write_text(
        "---\ntype: ressource\nsource:\ntags: [ressource]\n---\n\n# Titre\n\n## Résumé\n\n## Points clés\n\n## Liens\n",
        encoding="utf-8")
