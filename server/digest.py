"""Digest sha-256 en base64url, sans remplissage `=` (brouillon 8a859b8)."""
import base64
import hashlib


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def sha256_b64url(data: bytes) -> str:
    return _b64url(hashlib.sha256(data).digest())


def digest_obj(data: bytes) -> dict:
    """Objet `digest` du brouillon : `{"algorithm": "sha-256", "value": <base64url>}`."""
    return {"algorithm": "sha-256", "value": sha256_b64url(data)}


class Sha256Stream:
    def __init__(self) -> None:
        self._h = hashlib.sha256()

    def update(self, chunk: bytes) -> None:
        self._h.update(chunk)

    def b64url(self) -> str:
        return _b64url(self._h.digest())

    def digest_obj(self) -> dict:
        return {"algorithm": "sha-256", "value": self.b64url()}
