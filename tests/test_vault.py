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
    ("../x.pdf", "x.pdf"), (".x.pdf", "x.pdf"), (". .pdf", "pdf"), ("a/b.pdf", "ab.pdf"), ("", "fichier"),
    ("Été\x00.pdf", "Été.pdf"), (".", "fichier"), ("..", "fichier"),
    ("a[b]|c#d^e.pdf", "abcde.pdf"), ("[[x]].pdf", "x.pdf"),
    ("<% tp.x %>.pdf", "tp.x .pdf"), ("{{a}}$`b`.pdf", "ab.pdf"),
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


async def test_attach_cree_puis_complete(vault):
    v = Vault(vault)
    f = vault / "00 - Inbox" / "p.pdf"
    f.write_bytes(b"x")
    note = await v.attach(None, "00 - Inbox", f)
    assert note.read_text().strip() == "![[p.pdf]]"
    await v.attach("00 - Inbox/p.md", "00 - Inbox", f)
    assert note.read_text().count("![[p.pdf]]") == 2


async def test_attach_n_ecrase_pas_une_note_existante(vault):
    v = Vault(vault)
    (vault / "00 - Inbox" / "p.md").write_text("avant\n")
    f = vault / "00 - Inbox" / "p.pdf"
    f.write_bytes(b"x")
    note = await v.attach(None, "00 - Inbox", f)
    assert (vault / "00 - Inbox" / "p.md").read_text() == "avant\n"  # jamais modifiée
    assert note.name == "p-2.md" and "![[p.pdf]]" in note.read_text()


async def test_write_unique_ne_suit_pas_un_lien_brise(vault, tmp_path_factory):
    cible = tmp_path_factory.mktemp("dehors") / "cible.pdf"
    (vault / "00 - Inbox" / "p.pdf").symlink_to(cible)
    dest = await Vault(vault).write_unique("00 - Inbox", "p.pdf", b"1")
    assert dest.name == "p-2.pdf" and not cible.exists()


async def test_write_unique_path_ne_suit_pas_un_lien_brise(vault, tmp_path_factory):
    cible = tmp_path_factory.mktemp("dehors") / "cible.pdf"
    (vault / "00 - Inbox" / "p.pdf").symlink_to(cible)
    src = vault / "src.bin"
    src.write_bytes(b"z")
    dest = await Vault(vault).write_unique("00 - Inbox", "p.pdf", src)
    assert dest.name == "p-2.pdf" and not cible.exists()


@pytest.mark.parametrize("note", ["00 - Inbox/p.txt", ".obsidian/x.md", "00 - Inbox/.staging/x.md", "p"])
async def test_attach_refuse_note_invalide(vault, note):
    f = vault / "00 - Inbox" / "p.pdf"
    f.write_bytes(b"x")
    with pytest.raises(VaultPathError):
        await Vault(vault).attach(note, "00 - Inbox", f)


async def test_attach_refuse_note_qui_est_un_dossier(vault):
    (vault / "00 - Inbox" / "d.md").mkdir()
    f = vault / "00 - Inbox" / "p.pdf"
    f.write_bytes(b"x")
    with pytest.raises(VaultPathError):
        await Vault(vault).attach("00 - Inbox/d.md", "00 - Inbox", f)


@pytest.mark.parametrize("brut", ["a\u202eb.pdf", "a\u200bb.pdf", "a\ufeffb.pdf"])
def test_sanitize_retire_caracteres_de_format(brut):
    assert sanitize_name(brut) == "ab.pdf"
