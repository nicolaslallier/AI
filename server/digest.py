"""Digest sha-256 en base64url, sans remplissage `=` (brouillon 8a859b8)."""
import base64
import hashlib


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def sha256_b64url(data: bytes) -> str:
    return _b64url(hashlib.sha256(data).digest())


class Sha256Stream:
    def __init__(self) -> None:
        self._h = hashlib.sha256()

    def update(self, chunk: bytes) -> None:
        self._h.update(chunk)

    def b64url(self) -> str:
        return _b64url(self._h.digest())
