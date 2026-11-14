"""Client GitHub App : jeton d'installation, branches, pull requests."""

import base64
import binascii
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote

import httpx
import jwt
from cryptography.hazmat.primitives import serialization

API = "https://api.github.com"
_DEPOT = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_MARGE_S = 300


class ErreurGitHub(Exception):
    pass


def depot_depuis_url(url: str) -> str:
    m = _URL.match(url.strip())
    if not m:
        raise ErreurGitHub("URL de dépôt GitHub invalide")
    return f"{m[1]}/{m[2]}"


def _valider_depot(depot: str) -> None:
    if not _DEPOT.match(depot) or ".." in depot:
        raise ErreurGitHub(f"dépôt invalide : {depot!r}")


class GitHubApp:
    def __init__(
        self,
        app_id: str,
        cle_b64: str,
        transport: httpx.AsyncBaseTransport | None = None,
        horloge: Callable[[], float] = time.time,
    ):
        try:
            pem = base64.b64decode(cle_b64, validate=True)
            serialization.load_pem_private_key(pem, password=None)
        except (binascii.Error, ValueError, TypeError):
            # jamais la valeur de la clé dans le message
            raise ErreurGitHub("clé de l'App GitHub invalide (PEM en base64 attendu)") from None
        self._app_id = app_id
        self._pem = pem
        self._transport = transport
        self._horloge = horloge
        self._cache: dict[int, tuple[str, float]] = {}  # installation -> (jeton, expiration)

    def _jwt(self) -> str:
        t = int(self._horloge())
        return jwt.encode(
            {"iat": t - 60, "exp": t + 540, "iss": self._app_id}, self._pem, algorithm="RS256"
        )

    async def _appel(self, methode: str, chemin: str, jeton: str, corps: dict | None = None) -> Any:
        entetes = {
            "Authorization": f"Bearer {jeton}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=30) as c:
                r = await c.request(methode, API + chemin, json=corps, headers=entetes)
        except httpx.HTTPError as e:
            raise ErreurGitHub(f"GitHub injoignable : {type(e).__name__}") from None
        if r.status_code >= 400:
            raise ErreurGitHub(f"GitHub {r.status_code} sur {methode} {chemin} : {r.text[:300]}")
        try:
            return r.json()
        except ValueError:
            raise ErreurGitHub(f"réponse non JSON sur {methode} {chemin}") from None

    @staticmethod
    def _champ(donnees: Any, cle: str, type_: type) -> Any:
        v = donnees.get(cle) if isinstance(donnees, dict) else None
        if not isinstance(v, type_) or (type_ is int and isinstance(v, bool)):
            raise ErreurGitHub(f"réponse GitHub inattendue : champ {cle!r}")
        return v

    async def jeton(self, depot: str) -> str:
        _valider_depot(depot)
        inst = await self._appel("GET", f"/repos/{depot}/installation", self._jwt())
        iid = self._champ(inst, "id", int)
        en_cache = self._cache.get(iid)
        if en_cache and self._horloge() < en_cache[1]:
            return en_cache[0]
        rep = await self._appel("POST", f"/app/installations/{iid}/access_tokens", self._jwt())
        jeton = self._champ(rep, "token", str)
        try:
            fin = datetime.strptime(
                self._champ(rep, "expires_at", str), "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=UTC)
        except ValueError:
            raise ErreurGitHub("réponse GitHub inattendue : expires_at") from None
        self._cache[iid] = (jeton, fin.timestamp() - _MARGE_S)
        return jeton

    async def _depot(self, methode: str, depot: str, chemin: str, corps: dict | None = None):
        jeton = await self.jeton(depot)
        return await self._appel(methode, f"/repos/{depot}{chemin}", jeton, corps)

    async def branche_defaut(self, depot: str) -> str:
        rep = await self._depot("GET", depot, "")
        return self._champ(rep, "default_branch", str)

    async def branche_protegee(self, depot: str, branche: str) -> bool:
        rep = await self._depot("GET", depot, f"/branches/{quote(branche, safe='')}")
        return self._champ(rep, "protected", bool)

    async def creer_pr(
        self, depot: str, branche: str, base: str, titre: str, corps: str
    ) -> tuple[int, str]:
        rep = await self._depot(
            "POST", depot, "/pulls",
            {"title": titre, "body": corps, "head": branche, "base": base, "draft": True},
        )  # fmt: skip
        return self._champ(rep, "number", int), self._champ(rep, "html_url", str)

    async def etat_pr(self, depot: str, numero: int) -> Literal["ouverte", "fusionnee", "fermee"]:
        rep = await self._depot("GET", depot, f"/pulls/{int(numero)}")
        etat = self._champ(rep, "state", str)
        if etat == "open":
            return "ouverte"
        if etat == "closed":
            return "fusionnee" if rep.get("merged") is True else "fermee"
        raise ErreurGitHub(f"état de PR inattendu : {etat!r}")

    async def commenter(self, depot: str, numero: int, texte: str) -> None:
        await self._depot("POST", depot, f"/issues/{int(numero)}/comments", {"body": texte})

    async def fermer_pr(self, depot: str, numero: int) -> None:
        await self._depot("PATCH", depot, f"/pulls/{int(numero)}", {"state": "closed"})
