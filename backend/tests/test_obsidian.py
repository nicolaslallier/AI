"""Coffre Obsidian sur S3 : chemins sûrs, plafonds, listage, anti-écrasement."""

import hashlib

import pytest
from botocore.exceptions import ClientError

from portail.config import Reglages
from portail.obsidian import (
    Coffre,
    Conflit,
    chemin_doc,
    creer_coffre,
    est_note,
    normaliser,
    verifier_ecriture,
)


class FauxS3:
    """Bucket en dictionnaire : clé -> octets. Même interface que le client boto3 utilisé."""

    def __init__(self):
        self.objets: dict[str, bytes] = {}
        self.fermes = 0

    def _etag(self, cle):
        return '"' + hashlib.md5(self.objets[cle]).hexdigest() + '"'

    def _absent(self, op):
        return ClientError({"Error": {"Code": "NoSuchKey", "Message": "absent"}}, op)

    def list_objects_v2(self, Bucket, Prefix, Delimiter, MaxKeys):
        dossiers, contenus = set(), []
        for cle in sorted(self.objets):
            if not cle.startswith(Prefix):
                continue
            reste = cle[len(Prefix) :]
            if Delimiter in reste:
                dossiers.add(Prefix + reste.split(Delimiter)[0] + Delimiter)
            else:
                contenus.append({"Key": cle, "Size": len(self.objets[cle]), "LastModified": "t"})
        tout = sorted(dossiers) + [c["Key"] for c in contenus]
        tronque = len(tout) > MaxKeys
        gardes = set(tout[:MaxKeys])
        return {
            "CommonPrefixes": [{"Prefix": d} for d in sorted(dossiers) if d in gardes],
            "Contents": [c for c in contenus if c["Key"] in gardes],
            "IsTruncated": tronque,
        }

    def head_object(self, Bucket, Key):
        if Key not in self.objets:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {"ETag": self._etag(Key), "ContentLength": len(self.objets[Key])}

    def get_object(self, Bucket, Key):
        if Key not in self.objets:
            raise self._absent("GetObject")
        donnees = self.objets[Key]

        faux = self

        class Corps:
            def read(self, n=-1):
                return donnees if n < 0 else donnees[:n]

            def close(self):
                faux.fermes += 1

        return {"Body": Corps(), "ContentLength": len(donnees), "ETag": self._etag(Key)}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objets[Key] = Body
        return {"ETag": self._etag(Key)}


DOC = "01 - Projets/Portail/Docs/Portail - Guide.md"


@pytest.mark.parametrize(
    "chemin", ["", "../x.md", "a/../../x.md", "/abs.md", "a\\b.md", "a\x00.md", "..", "./"]
)
def test_normaliser_refuse(chemin):
    with pytest.raises(ValueError):
        normaliser(chemin)


def test_normaliser_nfc_et_points():
    assert normaliser("a/./b//é.md") == "a/b/é.md"


@pytest.mark.parametrize(
    "chemin,ok",
    [
        ("a/b.md", True),
        ("a/b.txt", False),
        (".obsidian/x.md", False),
        ("a/.trash/x.md", False),
        ("a/.obsidian/b/x.md", False),
    ],
)
def test_est_note(chemin, ok):
    assert est_note(chemin) is ok


@pytest.mark.parametrize(
    "chemin",
    [
        "01 - Projets/Portail/Notes.md",
        "01 - Projets/Portail/Docs/sous/x.md",
        "01 - Projets/Docs/x.md",
        "02 - Autre/Portail/Docs/x.md",
        "01 - Projets/Portail/Docs/x.txt",
        "01 - Projets/.obsidian/Docs/x.md",
        "01 - Projets/../Docs/x.md",
        "01 - Projets/P/Docs/a\tb.md",
    ],
)
def test_verifier_ecriture_refuse(chemin):
    with pytest.raises(ValueError):
        verifier_ecriture(chemin)


def test_verifier_ecriture_accepte():
    assert verifier_ecriture(DOC) == DOC


def test_chemin_doc_nettoie():
    assert chemin_doc("Por/tail", "Guide: ../install") == (
        "01 - Projets/Por-tail/Docs/Por-tail - Guide- ..-install.md"
    )
    verifier_ecriture(chemin_doc("../..", ".."))
    assert chemin_doc("P", 'a?*"<>|#^[]b') == "01 - Projets/P/Docs/P - a----------b.md"


def _coffre(prefixe=""):
    s3 = FauxS3()
    return s3, Coffre(s3, "obsidian", prefixe)


async def test_lister_un_niveau_et_filtre():
    s3, c = _coffre("Maison/")
    for cle in [
        "Maison/a.md",
        "Maison/b.png",
        "Maison/D/c.md",
        "Maison/.obsidian/app.md",
        "Maison/.trash/x.md",
        "Autre/z.md",
    ]:
        s3.objets[cle] = b"x"
    r = await c.lister("")
    assert r["dossiers"] == ["D"]
    assert [n["chemin"] for n in r["notes"]] == ["a.md"]
    assert r["tronque"] is False
    assert [n["chemin"] for n in (await c.lister("D"))["notes"]] == ["D/c.md"]
    with pytest.raises(ValueError):
        await c.lister(".obsidian")


async def test_lister_tronque():
    s3, c = _coffre()
    for i in range(1001):
        s3.objets[f"n{i:04}.md"] = b"x"
    r = await c.lister("")
    assert r["tronque"] is True and len(r["notes"]) == 1000


async def test_lire_prefixe_et_plafond():
    s3, c = _coffre("Maison")
    s3.objets["Maison/a.md"] = "é".encode()
    assert await c.lire("a.md") == "é"
    s3.objets["Maison/gros.md"] = b"x" * (1024 * 1024 + 1)
    with pytest.raises(ValueError):
        await c.lire("gros.md")
    assert s3.fermes == 2
    with pytest.raises(FileNotFoundError):
        await c.lire("absent.md")
    with pytest.raises(ValueError):
        await c.lire(".obsidian/a.md")
    with pytest.raises(ValueError):
        await c.lire("../a.md")


async def test_ecrire_doc_premiere_et_republication():
    s3, c = _coffre("Maison/")
    etag = await c.ecrire_doc(DOC, "v1", None)
    assert s3.objets["Maison/" + DOC] == b"v1"
    etag2 = await c.ecrire_doc(DOC, "v2", etag)
    assert s3.objets["Maison/" + DOC] == b"v2" and etag2 != etag


async def test_ecrire_doc_conflits():
    s3, c = _coffre()
    s3.objets[DOC] = b"note de Nicolas"
    with pytest.raises(Conflit):
        await c.ecrire_doc(DOC, "v1", None)  # première publication sur une note existante
    with pytest.raises(Conflit):
        await c.ecrire_doc(DOC, "v1", '"autre"')  # modifiée depuis la dernière écriture
    assert s3.objets[DOC] == b"note de Nicolas"
    await c.ecrire_doc(DOC, "v1", None, forcer=True)
    assert s3.objets[DOC] == b"v1"


async def test_ecrire_doc_refuse_hors_docs_et_trop_gros():
    s3, c = _coffre()
    with pytest.raises(ValueError):
        await c.ecrire_doc("01 - Projets/P/Notes.md", "x", None)
    with pytest.raises(ValueError):
        await c.ecrire_doc(DOC, "x" * 200_001, None)
    assert s3.objets == {}


def test_creer_coffre_sans_secret():
    assert creer_coffre(Reglages(database_url="x")) is None
    assert isinstance(creer_coffre(Reglages(database_url="x", s3_secret_key="s")), Coffre)


def test_creer_coffre_prefixe_invalide():
    assert (
        creer_coffre(Reglages(database_url="x", s3_secret_key="s", coffre_prefixe="a/../b")) is None
    )
