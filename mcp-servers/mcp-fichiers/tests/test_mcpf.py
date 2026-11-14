import pytest

from client.mcpf import IntegrityError, McpfError, get, put
from conftest import make_pdf
from server.digest import Sha256Stream

PJ = "00 - Inbox/Pièces jointes"


async def test_put_puis_get_identiques(http, vault, tmp_path):
    src = tmp_path / "p.pdf"
    src.write_bytes(make_pdf(5 * 2**20))
    r = await put(http, src)
    assert r["structuredContent"]["fichier"] == f"{PJ}/p.pdf"
    out = await get(http, f"{PJ}/p.pdf", tmp_path / "out.pdf")
    assert out.read_bytes() == src.read_bytes()
    assert not (tmp_path / "out.pdf.part").exists()


async def test_get_digest_faux_supprime(http, vault, tmp_path, monkeypatch):
    (vault / "00 - Inbox/x.pdf").write_bytes(make_pdf(1000))
    monkeypatch.setattr(Sha256Stream, "digest_obj", lambda self: {"algorithm": "sha-256", "value": "AAAA"})
    with pytest.raises(IntegrityError):
        await get(http, "00 - Inbox/x.pdf", tmp_path / "o.pdf")
    assert not (tmp_path / "o.pdf").exists() and not (tmp_path / "o.pdf.part").exists()


async def test_get_refus_et_put_vide(http, vault, tmp_path):
    with pytest.raises(McpfError):
        await get(http, "00 - Inbox/absent.pdf", tmp_path / "o")
    vide = tmp_path / "v.md"
    vide.write_bytes(b"")
    await put(http, vide)
    assert (vault / PJ / "v.md").read_bytes() == b""


async def test_put_refus_serveur(http, tmp_path):
    src = tmp_path / "x.exe"
    src.write_bytes(b"MZ")
    with pytest.raises(McpfError):
        await put(http, src, dossier=".cache")
