"""Arbitre des modèles locaux : un appel à la fois par modèle, l'interactif avant le fond."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

Priorite = Literal["interactif", "fond"]
# après ce nombre de passages interactifs d'affilée, un appel de fond qui attend passe
_RAFALE_MAX = 3


class _Modele:
    def __init__(self) -> None:
        self.occupe = False
        self.files: dict[str, deque[asyncio.Future]] = {"interactif": deque(), "fond": deque()}
        self.rafale = 0  # passages interactifs consécutifs pendant qu'un fond attend


class Arbitre:
    def __init__(self) -> None:
        self._modeles: dict[str, _Modele] = {}

    @asynccontextmanager
    async def tour(self, modele: str, priorite: Priorite) -> AsyncIterator[None]:
        m = self._modeles.setdefault(modele, _Modele())
        if m.occupe:
            f = asyncio.get_running_loop().create_future()
            m.files[priorite].append(f)
            try:
                await f
            except asyncio.CancelledError:
                if f.cancelled():
                    if f in m.files[priorite]:  # sinon `_liberer` l'a déjà écartée
                        m.files[priorite].remove(f)
                else:  # le tour nous avait déjà été donné : le rendre
                    self._liberer(m)
                raise
        else:
            m.occupe = True
        try:
            yield
        finally:
            self._liberer(m)

    @staticmethod
    def _liberer(m: _Modele) -> None:
        for file in m.files.values():  # écarter les attentes annulées avant leur réveil
            while file and file[0].done():
                file.popleft()
        interactif, fond = m.files["interactif"], m.files["fond"]
        if fond and (m.rafale >= _RAFALE_MAX or not interactif):
            m.rafale = 0
            suivant = fond.popleft()
        elif interactif:
            m.rafale = m.rafale + 1 if fond else 0
            suivant = interactif.popleft()
        else:
            m.occupe = False
            m.rafale = 0
            return
        suivant.set_result(None)  # le modèle reste occupé : il passe au suivant


class LLMArbitre:
    """Même interface que `ClientLLM`, chaque appel passant par l'arbitre."""

    def __init__(self, llm, arbitre: Arbitre, priorite: Priorite) -> None:
        self._llm, self._arbitre, self._priorite = llm, arbitre, priorite

    async def flux(self, modele: str, messages: list[dict], temperature: float | None):
        async with self._arbitre.tour(modele, self._priorite):
            async for morceau in self._llm.flux(modele, messages, temperature):
                yield morceau

    async def completer(
        self,
        modele: str,
        messages: list[dict],
        temperature: float | None,
        outils: list[dict] | None = None,
        response_format: dict | None = None,
    ) -> dict:
        async with self._arbitre.tour(modele, self._priorite):
            return await self._llm.completer(modele, messages, temperature, outils, response_format)
