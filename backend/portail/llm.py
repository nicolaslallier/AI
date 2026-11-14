"""Client LiteLLM en streaming et filtre des blocs <think>."""

import json
from collections.abc import AsyncIterator

import httpx

_OUVRE, _FERME = "<think>", "</think>"


class ErreurLLM(Exception):
    pass


class ClientLLM:
    def __init__(self, url: str, cle: str, transport: httpx.AsyncBaseTransport | None = None):
        self._url = url.rstrip("/")
        self._cle = cle
        self._transport = transport

    async def flux(
        self, modele: str, messages: list[dict], temperature: float | None
    ) -> AsyncIterator[str]:
        corps: dict = {"model": modele, "messages": messages, "stream": True}
        if temperature is not None:
            corps["temperature"] = temperature
        try:
            async with (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(300, connect=10), transport=self._transport
                ) as client,
                client.stream(
                    "POST",
                    f"{self._url}/v1/chat/completions",
                    json=corps,
                    headers={"Authorization": f"Bearer {self._cle}"} if self._cle else {},
                ) as reponse,
            ):
                if not reponse.is_success:
                    debut = (await reponse.aread()).decode(errors="replace")[:300]
                    raise ErreurLLM(f"LiteLLM a répondu {reponse.status_code} : {debut}")
                async for ligne in reponse.aiter_lines():
                    if not ligne.startswith("data: "):
                        continue
                    donnees = ligne[6:].strip()
                    if donnees == "[DONE]":
                        return
                    try:
                        choix = json.loads(donnees)["choices"]
                        contenu = choix[0]["delta"].get("content") if choix else None
                    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
                        raise ErreurLLM(f"Réponse de LiteLLM illisible : {donnees[:200]}") from e
                    if contenu:
                        yield contenu
                raise ErreurLLM("flux interrompu")
        except httpx.TimeoutException as e:
            raise ErreurLLM(f"LiteLLM : délai dépassé ({e.__class__.__name__})") from e
        except httpx.HTTPError as e:
            raise ErreurLLM(f"LiteLLM injoignable : {e}") from e

    async def completer(
        self,
        modele: str,
        messages: list[dict],
        temperature: float | None,
        outils: list[dict] | None = None,
        response_format: dict | None = None,
    ) -> dict:
        corps: dict = {"model": modele, "messages": messages, "stream": False}
        if temperature is not None:
            corps["temperature"] = temperature
        if outils is not None:
            corps["tools"] = outils
        if response_format is not None:
            corps["response_format"] = response_format
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(300, connect=10), transport=self._transport
            ) as client:
                reponse = await client.post(
                    f"{self._url}/v1/chat/completions",
                    json=corps,
                    headers={"Authorization": f"Bearer {self._cle}"} if self._cle else {},
                )
        except httpx.TimeoutException as e:
            raise ErreurLLM(f"LiteLLM : délai dépassé ({e.__class__.__name__})") from e
        except httpx.HTTPError as e:
            raise ErreurLLM(f"LiteLLM injoignable : {e}") from e
        if not reponse.is_success:
            raise ErreurLLM(f"LiteLLM a répondu {reponse.status_code} : {reponse.text[:300]}")
        try:
            return reponse.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise ErreurLLM(f"Réponse de LiteLLM illisible : {reponse.text[:200]}") from e


def _suffixe_prefixe(texte: str, balise: str) -> int:
    """Longueur du plus long suffixe de `texte` qui commence `balise`."""
    for n in range(min(len(texte), len(balise) - 1), 0, -1):
        if balise.startswith(texte[-n:]):
            return n
    return 0


class FiltreReflexion:
    def __init__(self, retenir: bool = False) -> None:
        self._tampon = ""
        self._dedans = False
        # retenir : tant qu'aucune balise n'est vue, rien n'est émis, pour qu'un </think>
        # orphelin (<think> placé dans le prompt) efface ce qui précède. Au détriment du flux :
        # le chat diffuse sans retenir et recalcule le texte final avec retirer_reflexion.
        self._retenir = retenir
        self._indecis = True

    def envoyer(self, morceau: str) -> str:
        self._tampon += morceau
        visible = ""
        while True:
            if self._indecis:
                f, o = self._tampon.find(_FERME), self._tampon.find(_OUVRE)
                if f >= 0 and (o < 0 or f < o):
                    self._tampon = self._tampon[f + len(_FERME) :]
                    self._indecis = False
                    continue
                if o < 0 and self._retenir:
                    return visible
                self._indecis = False
            balise = _FERME if self._dedans else _OUVRE
            i = self._tampon.find(balise)
            if i >= 0:
                if not self._dedans:
                    visible += self._tampon[:i]
                self._tampon = self._tampon[i + len(balise) :]
                self._dedans = not self._dedans
                continue
            garde = _suffixe_prefixe(self._tampon, balise)
            fin = len(self._tampon) - garde
            if not self._dedans:
                visible += self._tampon[:fin]
            self._tampon = self._tampon[fin:]
            return visible

    def finir(self) -> str:
        self._indecis = False
        reste = "" if self._dedans else self._tampon
        self._tampon = ""
        return reste


def retirer_reflexion(texte: str) -> str:
    f = FiltreReflexion(retenir=True)
    return f.envoyer(texte) + f.finir()
