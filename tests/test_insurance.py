import time

from client.rpc import call
from conftest import b64, gabarit, make_pdf
from server.insurance import masquer, parse_police

TEXTE = "Assureur : Assurances Fictives inc.\nNuméro de police : HAB-123456789\nPrime annuelle : 1 234,56 $\nDu 2026-01-01 au 2027-01-01"


def test_masquer():
    assert masquer("HAB-123456789") == "****6789" and masquer("12") == "****" and masquer("abcd") == "****"


def test_parse_police():
    p = parse_police(TEXTE)
    assert (p.assureur, p.numero, p.debut, p.fin) == ("Assurances Fictives inc.", "HAB-123456789", "2026-01-01", "2027-01-01")
    assert p.montants == ["1 234,56 $"]


def test_parse_police_mots_cles_insuffisants():
    assert parse_police("Facture d'électricité : prime de bienvenue") is None
    assert parse_police("ASSURANCE habitation, POLICE n° 1") is not None  # insensible casse/accents


async def imp(http, pdf, name="police.pdf", **args):
    return await call(http, "tools/call", {"name": "vault_import_base64", "arguments":
                      {"name": name, "mimeType": "application/pdf", "data_base64": b64(pdf), **args}})


async def test_import_police(http, vault):
    gabarit(vault)
    r = await imp(http, make_pdf(texte=TEXTE))
    note = (vault / "00 - Inbox/police.md").read_text()
    assert "****6789" in note and "123456789" not in note
    assert "![[police.pdf]]" in note and "Assurances Fictives" in note
    assert "type: ressource" in note and "# Police Assurances Fictives inc." in note
    assert not (vault / "00 - Inbox/Pièces jointes/police.md").exists()
    assert (vault / "00 - Inbox/Pièces jointes/police.pdf").exists()
    assert r["result"]["structuredContent"]["note"] == "00 - Inbox/police.md"


async def test_police_ne_remplace_pas_une_note(http, vault):
    gabarit(vault)
    (vault / "00 - Inbox/police.md").write_text("à moi\n")
    await imp(http, make_pdf(texte=TEXTE))
    assert (vault / "00 - Inbox/police.md").read_text() == "à moi\n"
    assert "****6789" in (vault / "00 - Inbox/police-2.md").read_text()


async def test_pdf_ordinaire_inchange(http, vault):
    gabarit(vault)
    await imp(http, make_pdf(texte="Recette de crêpes\nFarine, oeufs, lait"), name="r.pdf")
    assert (vault / "00 - Inbox/Pièces jointes/r.md").read_text() == "![[r.pdf]]\n"
    assert not (vault / "00 - Inbox/r.md").exists()


async def test_sans_gabarit_note_generique(http, vault):
    await imp(http, make_pdf(texte=TEXTE))
    assert (vault / "00 - Inbox/Pièces jointes/police.md").read_text() == "![[police.pdf]]\n"
    assert not (vault / "00 - Inbox/police.md").exists()


async def test_pdf_malforme_note_generique(http, vault):
    gabarit(vault)
    await imp(http, b"%PDF-1.4\ngarbage assurance police prime")
    assert (vault / "00 - Inbox/Pièces jointes/police.md").exists()
    assert not (vault / "00 - Inbox/police.md").exists()


async def test_police_dossier_invalide_sans_orphelin(http, vault):
    gabarit(vault)
    r = await imp(http, make_pdf(texte=TEXTE), dossier=".obsidian")
    assert r["result"]["isError"] and not (vault / ".obsidian").exists()


async def _note(http, vault, texte):
    gabarit(vault)
    await imp(http, make_pdf(texte=texte))
    return (vault / "00 - Inbox/police.md").read_text()


async def test_numero_jamais_en_clair_mise_en_page_fusionnee(http, vault):
    for t in ("Assureur : Fictive inc. Numéro de police : HAB-123456789 Prime 5 $",
              "Assureur :\nNuméro de police : HAB-123456789\nPrime 5 $"):
        note = await _note(http, vault, t)
        assert "123456789" not in note and "HAB-123456789" not in note and "****6789" in note
        (vault / "00 - Inbox/police.md").unlink()


def test_filet_numero_dans_le_nom_du_pdf():
    from server.insurance import Police, note_police
    n = note_police(Police(numero="HAB-123456789"), "# Titre\n\n## Liens\n", "HAB-123456789.pdf")
    assert "123456789" not in n


def test_montant_lineaire():
    t = time.perf_counter()
    assert parse_police("assureur : X prime " + "123 " * 50000) is not None
    assert time.perf_counter() - t < 1


async def test_injection_neutralisee(http, vault):
    note = await _note(http, vault, 'Assureur : <% tp.system.exec("x") %> [[lien]] $= dv`x` {{y}} | #z\nPolice n° 1 prime')
    for m in ("<%", "%>", "[[lien]]", "$=", "`", "{{", "|", "#z"):
        assert m not in note.replace("![[police.pdf]]", "")
    assert note.count("\n# ") == 1


def test_texte_pdf_limite_pages():
    from server.insurance import MAX_PAGES, texte_pdf
    assert MAX_PAGES == 20 and texte_pdf(b"%PDF garbage") == ""
