import base64

import pytest

from client.rpc import call
from server.digest import digest_obj
from conftest import make_pdf


def fi(data, name="p.pdf", mime="application/pdf", **kw):
    return {"id": "f1", "name": name, "mimeType": mime, "size": len(data),
            "digest": digest_obj(data), "data": base64.b64encode(data).decode(), **kw}


async def imp(http, file, caps=frozenset(), **args):
    return await call(http, "tools/call", {"name": "vault_import_file", "arguments": {"file": file, **args}}, caps)


async def test_inline_200k(http, vault):
    pdf = make_pdf(200_000)
    await imp(http, fi(pdf), {"upload"})
    assert (vault / "00 - Inbox/Pièces jointes/p.pdf").read_bytes() == pdf
    assert "![[p.pdf]]" in (vault / "00 - Inbox/Pièces jointes/p.md").read_text()


async def test_inline_trop_gros(http):
    r = await imp(http, fi(make_pdf(1048577)), {"upload"})
    assert r["result"]["isError"] and "hors bande" in r["result"]["content"][0]["text"]


async def test_type_refuse(http):
    r = await imp(http, fi(b"MZ", name="a.exe", mime="application/octet-stream"), {"upload"})
    assert r["result"]["isError"]


async def test_digest_faux(http):
    f = fi(b"%PDF-x")
    f["digest"] = digest_obj(b"autre")
    assert (await imp(http, f, {"upload"}))["result"]["isError"]


async def test_dossier_hors_coffre(http):
    assert (await imp(http, fi(b"%PDF-x"), {"upload"}, dossier="../x"))["result"]["isError"]


async def test_dossier_cache(http, vault):
    assert (await imp(http, fi(b"%PDF-x"), {"upload"}, dossier=".obsidian"))["result"]["isError"]
    assert not (vault / ".obsidian").exists()


async def test_sans_data_sans_upload_32021(http):
    f = fi(b"%PDF-x")
    del f["data"]
    assert (await imp(http, f))["error"]["code"] == -32021


async def test_sans_data_avec_upload_upload_required(http):
    f = fi(b"%PDF-x")
    del f["data"]
    assert (await imp(http, f, {"upload"}))["result"]["resultType"] == "upload_required"


async def test_nom_cache_assaini(http, vault):
    await imp(http, fi(b"%PDF-x", name=".cache.pdf"), {"upload"})
    assert (vault / "00 - Inbox/Pièces jointes/cache.pdf").exists()


@pytest.mark.parametrize("note", ["../n.md", "00 - Inbox/n.txt", ".obsidian/n.md", "00 - Inbox"])
async def test_note_liee_invalide_sans_orphelin(http, vault, note):
    r = await imp(http, fi(b"%PDF-x"), {"upload"}, note_liée=note)
    assert r["result"]["isError"]
    assert not (vault / "00 - Inbox/Pièces jointes").exists()


async def test_inline_base64_trop_long_avant_decodage(http):
    f = fi(b"%PDF-x")
    f["data"] = "A" * (1048576 * 4 // 3 + 12)
    r = await imp(http, f, {"upload"})
    assert r["result"]["isError"] and "hors bande" in r["result"]["content"][0]["text"]


async def test_nom_absent(http, vault):
    pdf = b"%PDF-x"
    f = fi(pdf)
    del f["name"]
    f["mimeType"] = "application/pdf"
    await imp(http, f, {"upload"})
    assert (vault / "00 - Inbox/Pièces jointes/fichier").read_bytes() == pdf


async def test_note_liee(http, vault):
    (vault / "00 - Inbox/n.md").write_text("x\n")
    await imp(http, fi(b"%PDF-x"), {"upload"}, note_liée="00 - Inbox/n.md")
    assert "![[p.pdf]]" in (vault / "00 - Inbox/n.md").read_text()


async def test_base64_pour_clients_actuels(http, vault):
    pdf = make_pdf(10_000)
    r = await call(http, "tools/call", {"name": "vault_import_base64", "arguments":
                   {"name": "p.pdf", "mimeType": "application/pdf", "data_base64": base64.b64encode(pdf).decode()}})
    assert (vault / "00 - Inbox/Pièces jointes/p.pdf").read_bytes() == pdf
    assert r["result"]["structuredContent"]["fichier"] == "00 - Inbox/Pièces jointes/p.pdf"


async def test_base64_refuse(http):
    a = {"name": "a.exe", "mimeType": "application/octet-stream", "data_base64": "TVo="}
    r = await call(http, "tools/call", {"name": "vault_import_base64", "arguments": a})
    assert r["result"]["isError"]
    a = {"name": "p.pdf", "mimeType": "application/pdf", "data_base64": base64.b64encode(make_pdf(1048577)).decode()}
    r = await call(http, "tools/call", {"name": "vault_import_base64", "arguments": a})
    assert r["result"]["isError"] and "hors bande" in r["result"]["content"][0]["text"]


async def test_read_note_cache_et_non_md(http, vault):
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian/x.md").write_text("secret")
    (vault / "a.pdf").write_bytes(b"%PDF")
    for c in (".obsidian/x.md", "a.pdf"):
        r = await call(http, "tools/call", {"name": "vault_read_note", "arguments": {"chemin": c}})
        assert r["result"]["isError"]


async def test_read_note_lien_vers_cache(http, vault):
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian/x.md").write_text("secret")
    (vault / "lien.md").symlink_to(vault / ".obsidian/x.md")
    r = await call(http, "tools/call", {"name": "vault_read_note", "arguments": {"chemin": "lien.md"}})
    assert r["result"]["isError"]


async def test_search_ignore_lien_externe(http, vault, tmp_path_factory):
    out = tmp_path_factory.mktemp("dehors") / "s.md"
    out.write_text("MOTSECRET")
    (vault / "lien.md").symlink_to(out)
    r = await call(http, "tools/call", {"name": "vault_search", "arguments": {"query": "MOTSECRET"}})
    assert "MOTSECRET" not in str(r)


async def test_client_sans_caps_n_annonce_pas_l_extension(http):
    r = await call(http, "tools/list", {})
    assert all(t["name"] != "vault_import_file" for t in r["result"]["tools"])


async def test_import_md_intact_sans_note(http, vault):
    md = "# Titre\n\nTexte.\n".encode()
    r = await imp(http, fi(md, name="n.md", mime="text/markdown"), {"upload"})
    assert r["result"]["structuredContent"]["note"] == "00 - Inbox/Pièces jointes/n.md"
    assert (vault / "00 - Inbox/Pièces jointes/n.md").read_bytes() == md
    assert [p.name for p in (vault / "00 - Inbox/Pièces jointes").iterdir()] == ["n.md"]


async def test_import_md_note_liee(http, vault):
    (vault / "00 - Inbox/autre.md").write_text("x\n")
    md = b"# Titre\n"
    await imp(http, fi(md, name="n.md", mime="text/markdown"), {"upload"}, note_liée="00 - Inbox/autre.md")
    assert "![[n.md]]" in (vault / "00 - Inbox/autre.md").read_text()
    assert (vault / "00 - Inbox/Pièces jointes/n.md").read_bytes() == md
    assert [p.name for p in (vault / "00 - Inbox/Pièces jointes").iterdir()] == ["n.md"]


async def test_nom_html_mime_png_refuse(http, vault):
    r = await imp(http, fi(b"<html>", name="x.html", mime="image/png"), {"upload"})
    assert r["result"]["isError"] and not (vault / "00 - Inbox/Pièces jointes").exists()
    f = fi(b"<html>", name="x.html", mime="image/png")
    del f["data"]
    r = await imp(http, f, {"upload"})  # hors bande : refusé dès la demande
    assert r["result"]["isError"]


async def test_import_md_puis_pdf_meme_nom_ne_modifie_pas_le_md(http, vault):
    md = b"# Rapport\n"
    await imp(http, fi(md, name="rapport.md", mime="text/markdown"), {"upload"})
    pj = vault / "00 - Inbox/Pièces jointes"
    avant = (pj / "rapport.md").read_bytes()
    await imp(http, fi(make_pdf(), name="rapport.pdf"), {"upload"})
    assert (pj / "rapport.md").read_bytes() == avant == md
    assert "![[rapport.pdf]]" in (pj / "rapport-2.md").read_text()
