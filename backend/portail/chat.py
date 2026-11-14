"""Chat en streaming : une tâche de fond par appel au modèle, diffusée en SSE."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portail.agents import Catalogue
from portail.contexte import construire, jauge
from portail.db import Document, Etape, Message, Pipeline
from portail.etats import Etat
from portail.llm import ClientLLM, FiltreReflexion
from portail.moteur import Refus, changer_etat, terminer_etape

logger = logging.getLogger(__name__)


class Diffuseur:
    def __init__(self) -> None:
        self.partiels: dict[int, str] = {}
        self.abonnes: dict[int, set[asyncio.Queue]] = {}

    def abonner(self, etape_id: int) -> tuple[str, asyncio.Queue]:
        file: asyncio.Queue = asyncio.Queue()
        self.abonnes.setdefault(etape_id, set()).add(file)
        return self.partiels.get(etape_id, ""), file

    def desabonner(self, etape_id: int, file: asyncio.Queue) -> None:
        files = self.abonnes.get(etape_id, set())
        files.discard(file)
        if not files:
            self.abonnes.pop(etape_id, None)

    def publier(self, etape_id: int, evenement: dict) -> None:
        for file in self.abonnes.get(etape_id, ()):
            file.put_nowait(evenement)

    def ajouter_partiel(self, etape_id: int, texte: str) -> None:
        self.partiels[etape_id] = self.partiels.get(etape_id, "") + texte

    def oublier(self, etape_id: int) -> None:
        self.partiels.pop(etape_id, None)


def _sse(type_: str, donnees: dict) -> str:
    return f"event: {type_}\ndata: {json.dumps(donnees, ensure_ascii=False)}\n\n"


class ServiceChat:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        catalogue: Catalogue,
        llm: ClientLLM,
        diffuseur: Diffuseur,
    ):
        self._sessions = sessions
        self._catalogue = catalogue
        self._llm = llm
        self.diffuseur = diffuseur
        self.taches: dict[int, asyncio.Task] = {}

    async def _etape(self, s: AsyncSession, etape_id: int) -> Etape:
        # verrou de ligne : deux envois simultanés ne passent pas tous les deux
        etape = await s.scalar(select(Etape).where(Etape.id == etape_id).with_for_update())
        if etape is None:
            raise Refus(404, "étape introuvable")
        return etape

    async def _contexte(self, s: AsyncSession, etape: Etape):
        messages = (
            await s.scalars(
                select(Message).where(Message.etape_id == etape.id).order_by(Message.id)
            )
        ).all()
        doc = await s.scalar(select(Document).where(Document.etape_id == etape.id))
        return messages, doc

    async def envoyer(self, etape_id: int, contenu: str) -> None:
        async with self._sessions() as s:
            etape = await self._etape(s, etape_id)
            if etape.etat == Etat.EN_COURS:
                raise Refus(409, "une réponse est déjà en cours")
            if etape.etat != Etat.EN_ATTENTE:
                raise Refus(409, "étape non active")
            contenu = contenu.strip()
            if not contenu:
                raise Refus(422, "le message est vide")
            agent = self._catalogue.agents[etape.agent]
            messages, doc = await self._contexte(s, etape)
            avec = construire(agent, messages, doc) + [{"role": "user", "content": contenu}]
            if jauge(agent, avec).niveau == "plein":
                raise Refus(
                    409, "contexte presque plein : clique « Rédiger la spec » pour continuer"
                )
            s.add(Message(etape_id=etape_id, role="user", contenu=contenu))
            etape.action = "repondre"
            await changer_etat(s, etape, Etat.EN_COURS)
            await s.commit()
        self._lancer(etape_id)

    async def rediger(self, etape_id: int) -> None:
        async with self._sessions() as s:
            etape = await self._etape(s, etape_id)
            if etape.etat != Etat.EN_ATTENTE:
                raise Refus(
                    409,
                    "étape non active"
                    if etape.etat != Etat.EN_COURS
                    else "une réponse est déjà en cours",
                )
            if not self._catalogue.agents[etape.agent].consigne_redaction:
                raise Refus(409, "cet agent ne rédige pas de document")
            etape.action = "rediger"
            await changer_etat(s, etape, Etat.EN_COURS)
            await s.commit()
        self._lancer(etape_id)

    async def reessayer(self, etape_id: int) -> None:
        async with self._sessions() as s:
            etape = await self._etape(s, etape_id)
            if etape.etat != Etat.ECHOUEE:
                raise Refus(409, "seule une étape échouée peut être relancée")
            await changer_etat(s, etape, Etat.EN_COURS)
            await s.commit()
        self._lancer(etape_id)

    def _lancer(self, etape_id: int) -> None:
        tache = asyncio.create_task(self._tache(etape_id))
        self.taches[etape_id] = tache  # référence forte : asyncio ne garde qu'une référence faible

        def _fini(t: asyncio.Task) -> None:
            if self.taches.get(etape_id) is t:
                del self.taches[etape_id]

        tache.add_done_callback(_fini)

    async def _tache(self, etape_id: int) -> None:
        d = self.diffuseur
        try:
            async with self._sessions() as s:
                etape = await s.get(Etape, etape_id)
                agent = self._catalogue.agents[etape.agent]
                action = etape.action
                messages, doc = await self._contexte(s, etape)
                consigne = agent.consigne_redaction if action == "rediger" else None
                demande = construire(agent, messages, doc, consigne)
            filtre = FiltreReflexion()
            visible = ""
            async for morceau in self._llm.flux(agent.modele, demande, agent.temperature):
                if part := filtre.envoyer(morceau):
                    visible += part
                    d.ajouter_partiel(etape_id, part)
                    d.publier(etape_id, {"type": "delta", "texte": part})
            visible = (visible + filtre.finir()).strip()
            async with self._sessions() as s:
                etape = await self._etape(s, etape_id)
                if not visible:
                    await changer_etat(s, etape, Etat.ECHOUEE, "réponse vide du modèle")
                    await s.commit()
                    d.publier(etape_id, {"type": "erreur", "message": "réponse vide du modèle"})
                    return
                if action == "rediger":
                    await self._ecrire_document(s, etape, visible)
                else:
                    s.add(Message(etape_id=etape_id, role="assistant", contenu=visible))
                await changer_etat(s, etape, Etat.EN_ATTENTE)
                await s.commit()
            d.publier(etape_id, {"type": "fin"})
        except Exception as exc:  # noqa: BLE001 - toute erreur doit finir en étape échouée
            try:
                async with self._sessions() as s:
                    etape = await self._etape(s, etape_id)
                    await changer_etat(s, etape, Etat.ECHOUEE, str(exc))
                    await s.commit()
            except Exception:
                # l'événement terminal part quand même : les abonnés ne doivent pas rester bloqués
                logger.exception("impossible d'enregistrer l'échec de l'étape %s", etape_id)
            d.publier(etape_id, {"type": "erreur", "message": str(exc)})
        finally:
            d.oublier(etape_id)

    async def _ecrire_document(self, s: AsyncSession, etape: Etape, contenu: str) -> None:
        dernier = await s.scalar(select(func.max(Message.id)).where(Message.etape_id == etape.id))
        pipeline = await s.get(Pipeline, etape.pipeline_id)
        doc = await s.scalar(select(Document).where(Document.etape_id == etape.id))
        if doc is None:
            doc = Document(projet_id=pipeline.projet_id, pipeline_id=pipeline.id, etape_id=etape.id)
            s.add(doc)
        doc.type = pipeline.type
        doc.contenu = contenu
        doc.etat = "brouillon"
        doc.dernier_message_id = dernier
        doc.maj_le = datetime.now(UTC)

    async def corriger(self, etape_id: int, contenu: str) -> Document:
        if not contenu.strip():
            raise Refus(422, "le document est vide")
        async with self._sessions() as s:
            etape = await self._etape(s, etape_id)
            doc = await s.scalar(select(Document).where(Document.etape_id == etape_id))
            if doc is None:
                raise Refus(409, "aucun brouillon à corriger")
            if doc.etat != "brouillon":
                raise Refus(409, "spec déjà validée")
            if etape.etat == Etat.EN_COURS:
                raise Refus(409, "une réponse est en cours")
            doc.contenu = contenu
            doc.maj_le = datetime.now(UTC)
            await s.commit()
            await s.refresh(doc)
            return doc

    async def valider(self, etape_id: int) -> int:
        """Valide le brouillon, termine l'étape ; renvoie l'id du pipeline."""
        async with self._sessions() as s:
            etape = await self._etape(s, etape_id)
            if etape.etat == Etat.EN_COURS:
                raise Refus(409, "une réponse est en cours")
            doc = await s.scalar(select(Document).where(Document.etape_id == etape_id))
            if etape.etat != Etat.EN_ATTENTE or doc is None or doc.etat != "brouillon":
                raise Refus(409, "rien à valider : clique d'abord « Rédiger la spec »")
            doc.etat = "validee"
            doc.maj_le = datetime.now(UTC)
            await terminer_etape(s, etape)
            await s.commit()
            return etape.pipeline_id

    async def etat(self, etape_id: int) -> str:
        async with self._sessions() as s:
            etape = await s.get(Etape, etape_id)
        if etape is None:
            raise Refus(404, "étape introuvable")
        return etape.etat

    async def flux(self, etape_id: int) -> AsyncIterator[str]:
        # on s'abonne avant de lire l'état : une fin publiée entre les deux n'est pas perdue
        partiel, file = self.diffuseur.abonner(etape_id)
        try:
            if await self.etat(etape_id) != Etat.EN_COURS:
                yield _sse("fin", {})
                return
            yield _sse("partiel", {"texte": partiel})
            while True:
                evenement = await file.get()
                type_ = evenement["type"]
                yield _sse(type_, {k: v for k, v in evenement.items() if k != "type"})
                if type_ in ("fin", "erreur"):
                    return
        finally:
            self.diffuseur.desabonner(etape_id, file)
