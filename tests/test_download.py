import asyncio

import pytest

from client.rpc import EXT_ID, call
from conftest import client, make_pdf, running
from server.app import create_app
from server.digest import sha256_b64url

DL = {"download"}


async def export(http, chemin, caps=DL):
    return await call(http, "tools/call", {"name": "vault_export", "arguments": {"chemin": chemin}}, caps)


async def ticket(http, vault, data=b"0123456789" * 100, name="x.pdf"):
    (vault / "00 - Inbox" / name).write_bytes(data)
    r = await export(http, f"00 - Inbox/{name}")
    return "/mcp" + r["result"]["_meta"][EXT_ID]["downloads"][0]["path"]


async def test_aller_retour_40mo(http, vault):
    pdf = make_pdf(40 * 2**20)
    (vault / "00 - Inbox/x.pdf").write_bytes(pdf)
    r = await export(http, "00 - Inbox/x.pdf")
    assert not r["result"].get("isError")
    d = r["result"]["_meta"][EXT_ID]["downloads"][0]
    assert d["digest"] == {"algorithm": "sha-256", "value": sha256_b64url(pdf)}
    assert d["name"] == "x.pdf" and d["mimeType"] == "application/pdf" and d["size"] == len(pdf)
    assert d["expiresAt"].endswith("Z") and d["path"].startswith("/downloads/")
    assert r["result"]["content"][0]["text"] == f"x.pdf, {len(pdf)} octets, application/pdf"
    g = await http.get("/mcp" + d["path"])
    assert g.status_code == 200 and sha256_b64url(g.content) == d["digest"]["value"]
    assert (await http.get("/mcp" + d["path"])).status_code == 200  # plusieurs GET permis


async def test_range_206(http, vault):
    data = bytes(range(256)) * 10
    url = await ticket(http, vault, data)
    g = await http.get(url, headers={"Range": "bytes=0-99"})
    assert g.status_code == 206 and g.content == data[:100]
    assert g.headers["content-range"] == f"bytes 0-99/{len(data)}"
    g = await http.get(url, headers={"Range": "bytes=2500-"})
    assert g.status_code == 206 and g.content == data[2500:]
    g = await http.get(url, headers={"Range": "bytes=-10"})
    assert g.status_code == 206 and g.content == data[-10:]
    assert g.headers["content-range"] == f"bytes {len(data) - 10}-{len(data) - 1}/{len(data)}"
    g = await http.get(url, headers={"Range": f"bytes=10-{len(data) + 500}"})  # fin tronquée
    assert g.status_code == 206 and g.content == data[10:]


async def test_pas_de_downloads_sans_capacite(http, vault):
    (vault / "00 - Inbox/n.md").write_text("salut")
    r = await export(http, "00 - Inbox/n.md", caps=set())
    assert not r["result"].get("isError")
    assert EXT_ID not in (r["result"].get("_meta") or {})
    res = r["result"]["content"][0]
    assert res["type"] == "resource" and res["resource"]["blob"] == "c2FsdXQ="


async def test_sans_capacite_trop_gros(http, vault):
    (vault / "00 - Inbox/g.pdf").write_bytes(make_pdf(2**20 + 1))
    r = await export(http, "00 - Inbox/g.pdf", caps=set())
    assert r["result"]["isError"]


@pytest.mark.parametrize("rng", ["bytes=500-100", "bytes=99999999-", "octets=1-2", "bytes=1-2,4-5",
                                 "bytes=-", "bytes=-0", "bytes=a-b", "bytes=", "bytes=1000-", "bytes=-1-2"])
async def test_range_invalide_416(http, vault, rng):  # Review Focus 5
    url = await ticket(http, vault, b"x" * 1000)
    g = await http.get(url, headers={"Range": rng})
    assert g.status_code == 416 and g.headers["content-range"] == "bytes */1000"


async def test_telechargement_inconnu_expire(vault):
    async with running(create_app(vault, transfer_ttl=0.2)) as a, client(a) as http:
        assert (await http.get("/mcp/downloads/inconnu")).status_code == 404
        assert (await http.get("/mcp/downloads/inconnu/")).status_code == 404
        url = await ticket(http, vault)
        await asyncio.sleep(0.4)
        assert (await http.get(url)).status_code == 410


@pytest.mark.parametrize("chemin", ["../x.pdf", ".obsidian/a.md", "00 - Inbox/absent.pdf", "00 - Inbox", ""])
async def test_export_refus(http, vault, chemin):
    r = await export(http, chemin)
    assert r["result"]["isError"]


async def test_export_lien_hors_coffre(http, vault, tmp_path_factory):
    dehors = tmp_path_factory.mktemp("dehors") / "secret.pdf"
    dehors.write_bytes(b"secret")
    (vault / "00 - Inbox/l.pdf").symlink_to(dehors)
    assert (await export(http, "00 - Inbox/l.pdf"))["result"]["isError"]
