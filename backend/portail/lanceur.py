"""Client HTTP du lanceur : seul le lanceur parle à Docker."""

import httpx
from pydantic import BaseModel, ValidationError

from portail.execution import Service


class ErreurLanceur(Exception):
    def __init__(self, statut: int, message: str):
        super().__init__(f"lanceur {statut} : {message}")
        self.statut = statut
        self.message = message


class Resultat(BaseModel):
    code: int | None
    sortie: str
    delai_depasse: bool


class ClientLanceur:
    def __init__(self, url: str, secret: str, transport: httpx.AsyncBaseTransport | None = None):
        self._url = url.rstrip("/")
        self._entetes = {"Authorization": f"Bearer {secret}"}
        self._transport = transport

    async def _poster(self, route: str, corps: dict, delai: float) -> dict:
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=delai) as c:
                r = await c.post(self._url + route, json=corps, headers=self._entetes)
        except httpx.HTTPError as e:
            raise ErreurLanceur(0, f"lanceur injoignable : {type(e).__name__} {e}") from None
        if r.status_code >= 400:
            try:
                message = str(r.json()["erreur"])
            except (ValueError, KeyError, TypeError):
                message = r.text[:500]
            raise ErreurLanceur(r.status_code, message)
        try:
            return r.json() if r.content else {}
        except ValueError:
            raise ErreurLanceur(0, f"réponse non JSON : {r.text[:500]}") from None

    async def lancer(
        self, espace: str, image: str, commande: str, delai_s: int, lecture_seule: list[str]
    ) -> Resultat:
        corps = {
            "espace": espace, "image": image, "commande": commande,
            "delai_s": delai_s, "lecture_seule": lecture_seule,
        }  # fmt: skip
        brut = await self._poster("/lancer", corps, delai_s + 60)
        try:
            return Resultat.model_validate(brut)
        except ValidationError as e:
            raise ErreurLanceur(0, f"réponse invalide : {e}") from None

    async def services(self, espace: str, services: list[Service]) -> None:
        corps = {"espace": espace, "services": [s.model_dump() for s in services]}
        await self._poster("/services", corps, 120)

    async def arreter(self, espace: str) -> None:
        await self._poster("/arreter", {"espace": espace}, 120)

    async def nettoyer(self, espace: str) -> None:
        await self._poster("/nettoyer", {"espace": espace}, 120)
