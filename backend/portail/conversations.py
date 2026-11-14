"""Conversations libres avec l'agent orchestrateur, hors de tout projet (sur le modèle du chat)."""

import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portail.agents import Agent, Catalogue
from portail.boucle import boucle_outils
from portail.chat import Diffuseur, _sse
from portail.contexte import jauge
from portail.db import Conversation, MessageConversation
from portail.llm import ClientLLM, FiltreReflexion, retirer_reflexion
from portail.moteur import Refus
from portail.outils_portail import OutilsPortail
from portail.schemas import ConversationDetail, MessageOut

logger = logging.getLogger(__name__)

AGENT = "orchestrateur"


def construire_conversation(agent: Agent, messages: list[MessageConversation]) -> list[dict]:
    """Les messages `tool` ne sont pas rejoués : ils servent à l'affichage."""
    sortie = [{"role": "system", "content": agent.prompt_systeme}]
    sortie += [
        {"role": m.role, "content": m.contenu}
        for m in messages
        if m.role in ("user", "assistant", "system")
    ]
    return sortie


class ServiceConversation:
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

    def _agent(self) -> Agent:
        agent = self._catalogue.agents.get(AGENT)
        if agent is None:
            raise Refus(409, f"agent « {AGENT} » absent de agents.yaml")
        return agent

    async def _conversation(self, s: AsyncSession, cid: int) -> Conversation:
        c = await s.scalar(select(Conversation).where(Conversation.id == cid).with_for_update())
        if c is None:
            raise Refus(404, "conversation introuvable")
        return c

    async def _messages(self, s: AsyncSession, cid: int) -> list[MessageConversation]:
        return list(
            (
                await s.scalars(
                    select(MessageConversation)
                    .where(MessageConversation.conversation_id == cid)
                    .order_by(MessageConversation.id)
                )
            ).all()
        )

    async def creer(self) -> Conversation:
        async with self._sessions() as s:
            c = Conversation()
            s.add(c)
            await s.commit()
            await s.refresh(c)
            return c

    async def lister(self) -> list[Conversation]:
        async with self._sessions() as s:
            q = select(Conversation).order_by(Conversation.maj_le.desc(), Conversation.id.desc())
            return list((await s.scalars(q)).all())

    async def detail(self, cid: int) -> ConversationDetail:
        async with self._sessions() as s:
            c = await s.get(Conversation, cid)
            if c is None:
                raise Refus(404, "conversation introuvable")
            messages = await self._messages(s, cid)
        agent = self._catalogue.agents.get(AGENT)
        return ConversationDetail(
            id=c.id,
            titre=c.titre,
            etat=c.etat,
            erreur=c.erreur,
            messages=[MessageOut.model_validate(m, from_attributes=True) for m in messages],
            jauge=jauge(agent, construire_conversation(agent, messages)) if agent else None,
        )

    async def renommer(self, cid: int, titre: str) -> None:
        async with self._sessions() as s:
            c = await self._conversation(s, cid)
            c.titre = titre.strip()
            await s.commit()

    async def envoyer(self, cid: int, contenu: str) -> None:
        async with self._sessions() as s:
            c = await self._conversation(s, cid)
            agent = self._agent()
            if c.etat == "en_cours":
                raise Refus(409, "une réponse est déjà en cours")
            contenu = contenu.strip()
            if not contenu:
                raise Refus(422, "le message est vide")
            avec = construire_conversation(agent, await self._messages(s, cid))
            if jauge(agent, avec + [{"role": "user", "content": contenu}]).niveau == "plein":
                raise Refus(409, "contexte plein : ouvre une nouvelle conversation")
            s.add(MessageConversation(conversation_id=cid, role="user", contenu=contenu))
            if not c.titre:
                c.titre = contenu[:60]
            c.etat, c.erreur = "en_cours", None
            await s.commit()
        self.lancer(cid)

    async def reessayer(self, cid: int) -> None:
        async with self._sessions() as s:
            c = await self._conversation(s, cid)
            if c.etat != "erreur":
                raise Refus(409, "rien à relancer")
            self._agent()
            c.etat, c.erreur = "en_cours", None
            await s.commit()
        self.lancer(cid)

    def lancer(self, cid: int) -> None:
        """Lance la tâche de fond d'une conversation déjà mise en_cours (et commitée)."""
        tache = asyncio.create_task(self._tache(cid))
        self.taches[cid] = tache  # référence forte : asyncio ne garde qu'une référence faible

        def _fini(t: asyncio.Task) -> None:
            if self.taches.get(cid) is t:
                del self.taches[cid]

        tache.add_done_callback(_fini)

    async def supprimer(self, cid: int) -> None:
        async with self._sessions() as s:
            c = await self._conversation(s, cid)
            if c.etat == "en_cours":
                raise Refus(409, "une réponse est en cours")
            await s.delete(c)  # les messages suivent (ON DELETE CASCADE)
            await s.commit()

    async def _streamer(self, cid: int, agent: Agent, demande: list[dict]) -> str:
        filtre = FiltreReflexion()
        brut = ""
        async for morceau in self._llm.flux(agent.modele, demande, agent.temperature):
            brut += morceau
            if part := filtre.envoyer(morceau):
                self.diffuseur.ajouter_partiel(cid, part)
                self.diffuseur.publier(cid, {"type": "delta", "texte": part})
        return retirer_reflexion(brut).strip()

    async def _boucle(self, cid: int, agent: Agent, demande: list[dict]) -> tuple[str, bool]:
        async def sur_appel(libelle: str, resultat: str) -> None:
            async with self._sessions() as s:
                s.add(
                    MessageConversation(
                        conversation_id=cid, role="tool", outil=libelle, contenu=resultat[:2000]
                    )
                )
                await s.commit()
            self.diffuseur.publier(cid, {"type": "outil", "libelle": libelle})

        outils = OutilsPortail(self._sessions, agent.outils)
        resultat = await boucle_outils(self._llm, agent, demande, outils, sur_appel)
        visible = resultat.texte.strip()
        if visible:
            self.diffuseur.publier(cid, {"type": "delta", "texte": visible})
        return visible, resultat.limite_atteinte

    async def _tache(self, cid: int) -> None:
        d = self.diffuseur
        try:
            agent = self._agent()
            async with self._sessions() as s:
                demande = construire_conversation(agent, await self._messages(s, cid))
            limite = False
            if agent.outils:
                visible, limite = await self._boucle(cid, agent, demande)
            else:
                visible = await self._streamer(cid, agent, demande)
            async with self._sessions() as s:
                c = await self._conversation(s, cid)
                if c.etat != "en_cours":
                    return
                if not visible:
                    c.etat, c.erreur = "erreur", "réponse vide du modèle"
                    await s.commit()
                    d.publier(cid, {"type": "erreur", "message": "réponse vide du modèle"})
                    return
                if limite:
                    s.add(
                        MessageConversation(
                            conversation_id=cid,
                            role="system",
                            contenu=f"limite de {agent.tours_max} appels d'outils atteinte : "
                            "la réponse peut être incomplète",
                        )
                    )
                    await s.flush()
                s.add(MessageConversation(conversation_id=cid, role="assistant", contenu=visible))
                c.etat = "pret"
                await s.commit()
            d.publier(cid, {"type": "fin"})
        except Exception as exc:  # noqa: BLE001 - toute erreur doit finir en conversation en erreur
            try:
                async with self._sessions() as s:
                    c = await self._conversation(s, cid)
                    if c.etat == "en_cours":
                        c.etat, c.erreur = "erreur", str(exc)
                        await s.commit()
            except Exception:
                # l'événement terminal part quand même : les abonnés ne doivent pas rester bloqués
                logger.exception("impossible d'enregistrer l'échec de la conversation %s", cid)
            d.publier(cid, {"type": "erreur", "message": str(exc)})
        finally:
            d.oublier(cid)

    async def etat(self, cid: int) -> str:
        async with self._sessions() as s:
            c = await s.get(Conversation, cid)
        if c is None:
            raise Refus(404, "conversation introuvable")
        return c.etat

    async def flux(self, cid: int) -> AsyncIterator[str]:
        # on s'abonne avant de lire l'état : une fin publiée entre les deux n'est pas perdue
        partiel, file = self.diffuseur.abonner(cid)
        try:
            if await self.etat(cid) != "en_cours":
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
            self.diffuseur.desabonner(cid, file)

    async def recuperer_interrompues(self, s: AsyncSession) -> int:
        """Au démarrage, aucune tâche de fond ne tourne : les `en_cours` sont orphelines."""
        r = await s.execute(
            update(Conversation)
            .where(Conversation.etat == "en_cours")
            .values(etat="erreur", erreur="interrompue par un redémarrage du serveur")
        )
        return r.rowcount
