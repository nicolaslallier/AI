"""Client LiteLLM en streaming et filtre des blocs <think>."""

import json
import logging
import time
from collections.abc import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portail import journal, metriques
from portail.db import AppelLLM

logger = logging.getLogger(__name__)

_OUVRE, _FERME = "<think>", "</think>"


class ErreurLLM(Exception):
    pass


class ClientLLM:
    def __init__(
        self,
        url: str,
        cle: str,
        transport: httpx.AsyncBaseTransport | None = None,
        sessions: async_sessionmaker[AsyncSession] | None = None,
        version: str = "",
    ):
        self._url = url.rstrip("/")
        self._cle = cle
        self._transport = transport
        self._sessions = sessions
        self._version = version

    @staticmethod
    def _mesurer(ctx: dict, modele: str, issue: str, usage: dict, duree: float) -> None:
        try:
            agent = ctx.get("agent", "inconnu")
            et = {"agent": agent, "modele": modele, "lieu": ctx.get("lieu", "portail")}
            metriques.LLM_APPELS.labels(**et, issue=issue).inc()
            metriques.LLM_DUREE.labels(**et).observe(duree)
            entree, sortie = usage.get("prompt_tokens"), usage.get("completion_tokens")
            for sens, n in (("entree", entree), ("sortie", sortie)):
                if isinstance(n, int | float):
                    metriques.LLM_JETONS.labels(**et, sens=sens).inc(n)
            max_ = ctx.get("contexte_max")
            if isinstance(entree, int | float) and isinstance(max_, int) and max_ > 0:
                metriques.CONTEXTE_REMPLISSAGE.labels(agent=agent).observe(entree / max_)
        except Exception:  # noqa: BLE001 (une métrique ne doit jamais arrêter l'appel)
            journal.erreur(logger, "métriques de l'appel_llm non enregistrées")

    async def _noter(self, modele: str, issue: str, usage: dict | None, debut: float) -> None:
        """Une ligne et des métriques par appel, sans aucun contenu ; n'échoue jamais."""
        ctx = journal.contexte.get()
        usage = usage if isinstance(usage, dict) else {}
        self._mesurer(ctx, modele, issue, usage, time.monotonic() - debut)
        if self._sessions is None:
            return
        try:
            async with self._sessions() as s:
                s.add(
                    AppelLLM(
                        agent=ctx.get("agent", "inconnu"),
                        modele=modele,
                        lieu=ctx.get("lieu", "portail"),
                        version_image=ctx.get("version_image", self._version or None),
                        mission=ctx.get("mission"),
                        pipeline_id=ctx.get("pipeline"),
                        etape_id=ctx.get("etape"),
                        tache_id=ctx.get("tache"),
                        conversation_id=ctx.get("conversation"),
                        jetons_entree=usage.get("prompt_tokens"),
                        jetons_sortie=usage.get("completion_tokens"),
                        duree_ms=int((time.monotonic() - debut) * 1000),
                        issue=issue,
                    )
                )
                await s.commit()
        except Exception:  # noqa: BLE001 (l'inscription ne doit jamais arrêter l'appel)
            journal.erreur(logger, "appel_llm non inscrit")

    async def flux(
        self, modele: str, messages: list[dict], temperature: float | None
    ) -> AsyncIterator[str]:
        corps: dict = {
            "model": modele,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if temperature is not None:
            corps["temperature"] = temperature
        debut, usage = time.monotonic(), None
        try:
            for essai in (1, 2):
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
                    if reponse.status_code == 400 and essai == 1:
                        del corps["stream_options"]  # LiteLLM sans usage en flux : on s'en passe
                        continue
                    if not reponse.is_success:
                        extrait = (await reponse.aread()).decode(errors="replace")[:300]
                        raise ErreurLLM(f"LiteLLM a répondu {reponse.status_code} : {extrait}")
                    async for ligne in reponse.aiter_lines():
                        if not ligne.startswith("data: "):
                            continue
                        donnees = ligne[6:].strip()
                        if donnees == "[DONE]":
                            await self._noter(modele, "ok", usage, debut)
                            return
                        try:
                            morceau = json.loads(donnees)
                            if "error" in morceau:  # message fixe : jamais le texte amont
                                raise ErreurLLM("LiteLLM a renvoyé une erreur dans le flux")
                            usage = morceau.get("usage") or usage
                            choix = morceau.get("choices")  # absent sur le morceau d'usage
                            contenu = choix[0]["delta"].get("content") if choix else None
                        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
                            raise ErreurLLM(
                                f"Réponse de LiteLLM illisible : {donnees[:200]}"
                            ) from e
                        if contenu:
                            yield contenu
                    raise ErreurLLM("flux interrompu")
        except httpx.TimeoutException as e:
            await self._noter(modele, "delai", None, debut)
            raise ErreurLLM(f"LiteLLM : délai dépassé ({e.__class__.__name__})") from e
        except httpx.HTTPError as e:
            await self._noter(modele, "erreur", None, debut)
            raise ErreurLLM(f"LiteLLM injoignable : {e}") from e
        except ErreurLLM:
            await self._noter(modele, "erreur", None, debut)
            raise

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
        debut = time.monotonic()
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
            await self._noter(modele, "delai", None, debut)
            raise ErreurLLM(f"LiteLLM : délai dépassé ({e.__class__.__name__})") from e
        except httpx.HTTPError as e:
            await self._noter(modele, "erreur", None, debut)
            raise ErreurLLM(f"LiteLLM injoignable : {e}") from e
        if not reponse.is_success:
            await self._noter(modele, "erreur", None, debut)
            raise ErreurLLM(f"LiteLLM a répondu {reponse.status_code} : {reponse.text[:300]}")
        try:
            corps_reponse = reponse.json()
            message = corps_reponse["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            await self._noter(modele, "erreur", None, debut)
            raise ErreurLLM(f"Réponse de LiteLLM illisible : {reponse.text[:200]}") from e
        await self._noter(modele, "ok", corps_reponse.get("usage"), debut)
        return message


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
