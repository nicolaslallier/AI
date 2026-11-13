import asyncio

import pytest

from server.vault import Vault, VaultPathError, sanitize_name


@pytest.mark.parametrize("rel", ["../x", "/etc/passwd", "a/../../x"])
def test_resolve_refuse_hors_coffre(vault, rel):
    with pytest.raises(VaultPathError):
        Vault(vault).resolve(rel)


def test_resolve_refuse_lien_qui_sort(vault, tmp_path_factory):
    dehors = tmp_path_factory.mktemp("dehors")
    (vault / "lien").symlink_to(dehors)
    with pytest.raises(VaultPathError):
        Vault(vault).resolve("lien/x.pdf")


@pytest.mark.parametrize("brut,attendu", [
    ("../x.pdf", "..x.pdf"), ("a/b.pdf", "ab.pdf"), ("", "fichier"),
    ("Été\x00.pdf", "Été.pdf"), (".", "fichier"), ("..", "fichier"),
])
def test_sanitize(brut, attendu):
    assert sanitize_name(brut) == attendu


def test_sanitize_long_garde_extension():
    n = sanitize_name("a" * 300 + ".pdf")
    assert len(n) <= 120 and n.endswith(".pdf")


async def test_pas_ecrasement(vault):
    v = Vault(vault)
    a, b = await asyncio.gather(v.write_unique("00 - Inbox", "p.pdf", b"1"),
                                v.write_unique("00 - Inbox", "p.pdf", b"2"))
    assert {a.name, b.name} == {"p.pdf", "p-2.pdf"}


async def test_write_unique_deplace_un_path(vault):
    v = Vault(vault)
    src = vault / "src.bin"
    src.write_bytes(b"z")
    dest = await v.write_unique("00 - Inbox", "p.pdf", src)
    assert dest.read_bytes() == b"z" and not src.exists()


def test_attach_cree_puis_complete(vault):
    v = Vault(vault)
    f = vault / "00 - Inbox" / "p.pdf"
    f.write_bytes(b"x")
    note = v.attach(None, "00 - Inbox", f)
    assert note.read_text().strip() == "![[p.pdf]]"
    v.attach("00 - Inbox/p.md", "00 - Inbox", f)
    assert note.read_text().count("![[p.pdf]]") == 2
