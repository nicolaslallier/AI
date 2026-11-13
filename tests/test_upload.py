import asyncio

import pytest

from client.rpc import call
from conftest import client, make_pdf, running
from server.app import create_app
from server.digest import digest_obj, sha256_b64url
from server.transfers import TransferStore

CAPS = {"upload"}
PJ = "00 - Inbox/Pièces jointes"


def args(data, name="p.pdf", **kw):
    f = {"id": "f1", "name": name, "mimeType": "application/pdf", "size": len(data), "digest": digest_obj(data)}
    return {"file": f, **kw}


async def demande(http, a, state=None):
    p = {"name": "vault_import_file", "arguments": a}
    if state is not None:
        p["requestState"] = state
    return await call(http, "tools/call", p, CAPS)


async def put(http, r1, body, **kw):
    return await http.put("/mcp" + r1["result"]["uploads"][0]["path"], content=body, **kw)


async def put_flow(http, data, args_override=None):
    a = args(data)
    r1 = await demande(http, a)
    p = await put(http, r1, data)
    r2 = await demande(http, args_override or a, r1["result"]["requestState"])
    return r1, p, r2


def vide(vault):
    return not (vault / PJ).exists() and not any((vault / ".staging").iterdir())


async def test_40mo_bout_en_bout(http, vault):
    pdf = make_pdf(40 * 2**20)
    r1, p, r2 = await put_flow(http, pdf)
    assert r1["result"]["resultType"] == "upload_required" and p.status_code == 204
    up = r1["result"]["uploads"][0]
    assert up["fileId"] == "f1" and up["method"] == "PUT" and up["credentials"] == "include"
    assert up["expiresAt"].endswith("Z")
    assert r2["result"]["structuredContent"]["fichier"] == f"{PJ}/p.pdf"
    assert sha256_b64url((vault / PJ / "p.pdf").read_bytes()) == sha256_b64url(pdf)
    assert "![[p.pdf]]" in (vault / PJ / "p.md").read_text()
    assert not any((vault / ".staging").iterdir())


async def test_etat_reutilise(http):
    pdf = b"%PDF-1"
    r1, _, r2 = await put_flow(http, pdf)
    assert not r2["result"].get("isError")
    r3 = await demande(http, args(pdf), r1["result"]["requestState"])
    assert r3["error"]["code"] == -32602


@pytest.fixture
async def http_ttl_court(vault):
    async with running(create_app(vault, state_ttl=0.5)) as a, client(a) as c:
        yield c


async def test_etat_expire(http_ttl_court):
    pdf = b"%PDF-1"
    r1 = await demande(http_ttl_court, args(pdf))
    assert (await put(http_ttl_court, r1, pdf)).status_code == 204
    await asyncio.sleep(1)
    r2 = await demande(http_ttl_court, args(pdf), r1["result"]["requestState"])
    assert r2["error"]["code"] == -32602


async def test_arguments_modifies(http):
    pdf = b"%PDF-1"
    _, _, r2 = await put_flow(http, pdf, args(pdf, dossier="Autre"))
    assert r2["error"]["code"] == -32602


async def test_taille_differente(http, vault):
    pdf = b"%PDF-12345"
    r1 = await demande(http, args(pdf))
    assert (await put(http, r1, pdf[:-1])).status_code == 413
    assert vide(vault)


async def test_digest_different(http, vault):
    pdf = b"%PDF-12345"
    r1 = await demande(http, args(pdf))
    assert (await put(http, r1, b"%PDF-1234X")).status_code == 400
    r2 = await demande(http, args(pdf), r1["result"]["requestState"])
    assert r2["result"]["isError"]
    assert vide(vault)


async def test_put_sans_content_length(http):
    pdf = b"%PDF-1"
    r1 = await demande(http, args(pdf))

    async def morceaux():
        yield pdf

    assert (await put(http, r1, morceaux())).status_code == 411


async def test_deuxieme_put(http):
    pdf = b"%PDF-1"
    r1 = await demande(http, args(pdf))
    assert (await put(http, r1, pdf)).status_code == 204
    assert (await put(http, r1, pdf)).status_code == 409


async def test_jeton_inconnu_et_slash(http):
    assert (await http.put("/mcp/uploads/inconnu", content=b"x")).status_code == 404
    r = await http.put("/mcp/uploads/inconnu/", content=b"x")
    assert r.status_code == 404  # jamais de 3xx


async def test_jeton_expire(vault):
    async with running(create_app(vault, transfer_ttl=0.2)) as a, client(a) as http:
        pdf = b"%PDF-1"
        r1 = await demande(http, args(pdf))
        await asyncio.sleep(0.4)
        assert (await put(http, r1, pdf)).status_code == 410


async def test_coupure_pendant_put(http, vault):
    # Review Focus 1 : httpx envoie le corps court tel quel avec le Content-Length annoncé.
    pdf = make_pdf(100_000)
    r1 = await demande(http, args(pdf))
    r = await put(http, r1, pdf[: len(pdf) // 2], headers={"Content-Length": str(len(pdf))})
    assert r.status_code == 400
    assert vide(vault)
    r2 = await demande(http, args(pdf), r1["result"]["requestState"])
    assert r2["result"]["isError"]
    assert vide(vault)


async def test_coupure_reseau_asgi(app, http, vault):
    # Vraie coupure : le serveur ASGI reçoit `http.disconnect` au milieu du corps.
    pdf = make_pdf(100_000)
    r1 = await demande(http, args(pdf))
    msgs = [
        {"type": "http.request", "body": pdf[:50_000], "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive():
        return msgs.pop(0) if msgs else {"type": "http.disconnect"}

    async def send(_):
        pass

    path = "/mcp" + r1["result"]["uploads"][0]["path"]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "PUT",
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "root_path": "", "headers": [(b"content-length", str(len(pdf)).encode())],
             "server": ("127.0.0.1", 8765), "client": ("127.0.0.1", 1)}
    await app(scope, receive, send)
    assert vide(vault)
    assert (await put(http, r1, pdf)).status_code == 409  # jeton à usage unique


async def test_relance_avant_put(http, vault):
    # Review Focus 2 : erreur claire, état non consommé.
    pdf = b"%PDF-1"
    r1 = await demande(http, args(pdf))
    state = r1["result"]["requestState"]
    r2 = await demande(http, args(pdf), state)
    assert r2["result"]["isError"] and "pas terminé" in r2["result"]["content"][0]["text"]
    assert (await put(http, r1, pdf)).status_code == 204
    r3 = await demande(http, args(pdf), state)
    assert not r3["result"].get("isError")
    assert (vault / PJ / "p.pdf").read_bytes() == pdf


async def test_refus_avant_ticket(http, vault):
    big = args(b"%PDF-1")
    big["file"]["size"] = 157286401
    exe = args(b"MZ", name="a.exe")
    exe["file"]["mimeType"] = "application/octet-stream"
    for a in (big, exe, args(b"%PDF-1", dossier=".obsidian")):
        r = await demande(http, a)
        assert r["result"]["isError"], a
    assert not (vault / ".staging").exists() or not any((vault / ".staging").iterdir())


@pytest.mark.parametrize("caps", [frozenset(), CAPS])
async def test_taille_non_entiere(http, caps):
    a = args(b"%PDF-1")
    a["file"]["size"] = "abc"
    r = await call(http, "tools/call", {"name": "vault_import_file", "arguments": a}, caps)
    assert r.get("result", {}).get("isError") or r["error"]["code"] == -32602


def test_store_sweep(tmp_path):
    s = TransferStore(tmp_path / ".staging", ttl=-1)
    t = s.new_upload(3, "d", "f1")
    t.staged.write_bytes(b"abc")
    s.sweep()
    assert s.upload(t.jeton) is None and not t.staged.exists()
    s2 = TransferStore(tmp_path / ".staging", ttl=60)
    t2 = s2.new_upload(3, "d", "f1")
    assert s2.consume(t2.jeton) and not s2.consume(t2.jeton)
