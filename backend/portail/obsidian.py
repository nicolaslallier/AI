"""Coffre Obsidian (bucket S3 `obsidian`) : lecture de tout le coffre, écriture sous
`01 - Projets/<Projet>/Docs/` seulement. Nommé `obsidian` : « coffre » désigne aussi OpenBao.

Jamais de suppression. Le secret S3 n'apparaît ni dans les journaux ni dans les erreurs."""

import asyncio
import logging
import re
import unicodedata

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from portail.config import Reglages

logger = logging.getLogger(__name__)

LECTURE_MAX = 1024 * 1024
ECRITURE_MAX = 200_000
LISTAGE_MAX = 1000
CACHES = {".obsidian", ".trash"}
_DOC = re.compile(r"01 - Projets/[^/]+/Docs/[^/]+\.md")


class Conflit(Exception):
    """La note a changé (ou existe déjà) depuis la dernière écriture du Portail."""


def normaliser(chemin: str) -> str:
    """Chemin relatif au coffre, sans issue possible ; ValueError sinon (copie d'Infra
    `mcp/obsidian/notes.py:normalize_path`)."""
    if not isinstance(chemin, str) or not chemin:
        raise ValueError("chemin vide")
    if "\x00" in chemin or "\\" in chemin or chemin.startswith("/"):
        raise ValueError("chemin invalide")
    parts = [p for p in unicodedata.normalize("NFC", chemin).split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        raise ValueError("chemin invalide")
    return "/".join(parts)


def _visible(parts: list[str]) -> bool:
    return not CACHES.intersection(parts)


def est_note(chemin: str) -> bool:
    return chemin.endswith(".md") and _visible(chemin.split("/"))


def verifier_ecriture(chemin: str) -> str:
    """Le seul endroit où le Portail peut écrire : `01 - Projets/<un segment>/Docs/<fichier>.md`."""
    c = normaliser(chemin)
    if not est_note(c) or not _DOC.fullmatch(c):
        raise ValueError("écriture permise seulement sous 01 - Projets/<Projet>/Docs/")
    return c


def _nettoyer(texte: str) -> str:
    propre = re.sub(r"[/\\:\x00-\x1f]", "-", texte).strip().lstrip(".").strip()
    return propre or "Sans titre"


def chemin_doc(projet: str, titre: str) -> str:
    p = _nettoyer(projet)
    return verifier_ecriture(f"01 - Projets/{p}/Docs/{p} - {_nettoyer(titre)}.md")


def _absent(e: ClientError) -> bool:
    return e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound")


class Coffre:
    def __init__(self, s3, bucket: str, prefixe: str = ""):
        self._s3, self._bucket = s3, bucket
        self._prefixe = normaliser(prefixe.strip("/")) + "/" if prefixe.strip("/") else ""

    async def lister(self, dossier: str = "") -> dict:
        """Un niveau du coffre : sous-dossiers, notes `.md`, `tronque` si plus de 1000 entrées."""
        d = normaliser(dossier) + "/" if dossier.strip("/") else ""
        if not _visible(d.split("/")):
            raise ValueError("dossier caché")
        r = await asyncio.to_thread(
            self._s3.list_objects_v2,
            Bucket=self._bucket,
            Prefix=self._prefixe + d,
            Delimiter="/",
            MaxKeys=LISTAGE_MAX,
        )
        n = len(self._prefixe)
        dossiers = [p["Prefix"][n:].rstrip("/") for p in r.get("CommonPrefixes", [])]
        notes = [
            {"chemin": o["Key"][n:], "taille": o["Size"], "modifie": str(o["LastModified"])}
            for o in r.get("Contents", [])
            if est_note(o["Key"][n:])
        ]
        return {
            "dossiers": [x for x in dossiers if _visible(x.split("/"))],
            "notes": notes,
            "tronque": bool(r.get("IsTruncated")),
        }

    async def lire(self, chemin: str) -> str:
        c = normaliser(chemin)
        if not est_note(c):
            raise ValueError("pas une note")
        try:
            r = await asyncio.to_thread(
                self._s3.get_object, Bucket=self._bucket, Key=self._prefixe + c
            )
        except ClientError as e:
            if _absent(e):
                raise FileNotFoundError(c) from None
            raise
        if r["ContentLength"] > LECTURE_MAX:
            raise ValueError("note trop grosse (1 Mio au plus)")
        return (await asyncio.to_thread(r["Body"].read)).decode("utf-8", errors="replace")

    async def ecrire_doc(
        self, chemin: str, texte: str, etag_connu: str | None, forcer: bool = False
    ) -> str:
        """Seule fonction qui écrit dans le coffre. Refuse (Conflit) d'écraser une note qui
        existe à la première publication, ou qui a changé depuis `etag_connu` ; `forcer` passe
        outre (le bucket est versionné). Renvoie le nouvel ETag."""
        c = verifier_ecriture(chemin)
        corps = texte.encode()
        if len(corps) > ECRITURE_MAX:
            raise ValueError("document trop gros (200 000 octets au plus)")
        cle = self._prefixe + c
        if not forcer:
            # ponytail: HEAD puis PUT, course possible entre les deux ; If-Match S3 si SeaweedFS le gère
            try:
                actuel = (
                    await asyncio.to_thread(self._s3.head_object, Bucket=self._bucket, Key=cle)
                )["ETag"]
            except ClientError as e:
                if not _absent(e):
                    raise
                actuel = None
            if actuel is not None and actuel != etag_connu:
                raise Conflit(c)
        r = await asyncio.to_thread(
            self._s3.put_object,
            Bucket=self._bucket,
            Key=cle,
            Body=corps,
            ContentType="text/markdown; charset=utf-8",
        )
        return r["ETag"]


def creer_coffre(r: Reglages) -> Coffre | None:
    if not r.s3_secret_key:
        logger.warning("coffre Obsidian éteint : PORTAIL_S3_SECRET_KEY absente")
        return None
    s3 = boto3.client(
        "s3",
        endpoint_url=r.s3_url,
        aws_access_key_id=r.s3_access_key,
        aws_secret_access_key=r.s3_secret_key,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )
    return Coffre(s3, r.s3_bucket, r.coffre_prefixe)
