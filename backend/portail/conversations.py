"""Conversations libres avec un agent de chat (orchestrateur ou PM), hors de tout projet (sur le modèle du chat)."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portail import journal
from portail.actions import executer_action
from portail.agents import Agent, Catalogue
from portail.audit import inscrire
from portail.chat import Diffuseur, ServiceChat, _sse
from portail.contexte import jauge
from portail.db import ActionConversation, Conversation, MessageConversation, Tache
from portail.llm import ClientLLM, FiltreReflexion, retirer_reflexion
from portail.missions import Missions, streamer, tourner
from portail.moteur import Refus
from portail.outils_portail import OutilsPortail
from portail.schemas import ActionOut, ConversationDetail, MessageOut

logger = logging.getLogger(__name__)

AGENTS = ("orchestrateur", "pm")


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
        chat: ServiceChat,
        annuler_tache: Callable[[int], Awaitable[None]],
        reveiller: Callable[[], None],
        missions: Missions | None = None,
    ):
        self._missions = missions
        self._sessions = sessions
        self._catalogue = catalogue
        self._llm = llm
        self.diffuseur = diffuseur
        self._chat = chat
        self._annuler_tache = annuler_tache
        self._reveiller = reveiller
        self.taches: dict[int, asyncio.Task] = {}

    def _agent(self, c: Conversation) -> Agent:
        agent = self._catalogue.agents.get(c.agent)
        if agent is None:
            raise Refus(409, f"agent « {c.agent} » absent de agents.yaml")
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

    async def creer(self, agent: str = "orchestrateur") -> Conversation:
        if agent not in AGENTS:
            raise Refus(422, f"agent inconnu : {agent}")
        if agent not in self._catalogue.agents:
            raise Refus(409, f"agent « {agent} » absent de agents.yaml")
        async with self._sessions() as s:
            c = Conversation(agent=agent)
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
            actions = (
                await s.scalars(
                    select(ActionConversation)
                    .where(ActionConversation.conversation_id == cid)
                    .order_by(ActionConversation.id)
                )
            ).all()
        agent = self._catalogue.agents.get(c.agent)
        return ConversationDetail(
            id=c.id,
            agent=c.agent,
            titre=c.titre,
            etat=c.etat,
            erreur=c.erreur,
            messages=[MessageOut.model_validate(m, from_attributes=True) for m in messages],
            actions=[ActionOut.model_validate(a, from_attributes=True) for a in actions],
            jauge=jauge(agent, construire_conversation(agent, messages)) if agent else None,
        )

    async def renommer(self, cid: int, titre: str) -> None:
        async with self._sessions() as s:
            c = await self._conversation(s, cid)
            c.titre = titre.strip()
            await s.commit()

    async def _perimer(self, s: AsyncSession, cid: int) -> None:
        """Sous le verrou de la conversation : une action ne s'exécute jamais hors de son fil."""
        ids = (
            await s.scalars(
                update(ActionConversation)
                .where(
                    ActionConversation.conversation_id == cid,
                    ActionConversation.etat == "proposee",
                )
                .values(etat="perimee")
                .returning(ActionConversation.id)
            )
        ).all()
        if ids:
            n = ", ".join(f"n°{i}" for i in sorted(ids))
            s.add(
                MessageConversation(
                    conversation_id=cid,
                    role="system",
                    contenu=f"Action(s) {n} périmée(s) : Nicolas a écrit un nouveau message "
                    "sans confirmer.",
                )
            )

    async def envoyer(self, cid: int, contenu: str) -> None:
        async with self._sessions() as s:
            c = await self._conversation(s, cid)
            agent = self._agent(c)
            if c.etat == "en_cours":
                raise Refus(409, "une réponse est déjà en cours")
            contenu = contenu.strip()
            if not contenu:
                raise Refus(422, "le message est vide")
            avec = construire_conversation(agent, await self._messages(s, cid))
            if jauge(agent, avec + [{"role": "user", "content": contenu}]).niveau == "plein":
                raise Refus(409, "contexte plein : ouvre une nouvelle conversation")
            await self._perimer(s, cid)
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
            self._agent(c)
            await self._perimer(s, cid)  # le tour relancé reproposera s'il le faut
            c.etat, c.erreur = "en_cours", None
            await s.commit()
        self.lancer(cid)

    async def _verrouiller(
        self, s: AsyncSession, action_id: int
    ) -> tuple[Conversation, ActionConversation]:
        """Conversation d'abord, puis l'action : même ordre que `envoyer`, qui périme."""
        cid = await s.scalar(
            select(ActionConversation.conversation_id).where(ActionConversation.id == action_id)
        )
        if cid is None:
            raise Refus(404, "action introuvable")
        c = await self._conversation(s, cid)
        a = await s.scalar(
            select(ActionConversation)
            .where(ActionConversation.id == action_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if a is None:
            raise Refus(404, "action introuvable")
        if c.etat == "en_cours":
            raise Refus(409, "attends la fin de la réponse")
        if a.etat == "perimee":
            raise Refus(409, "action périmée")
        if a.etat != "proposee":
            raise Refus(409, "action déjà traitée")
        return c, a

    def _systeme(self, s: AsyncSession, c: Conversation, contenu: str) -> None:
        s.add(MessageConversation(conversation_id=c.id, role="system", contenu=contenu))
        c.etat, c.erreur = "en_cours", None

    async def confirmer(self, action_id: int, auteur: str) -> None:
        """Seul chemin d'exécution d'une action : le clic de Nicolas, une seule fois."""
        async with self._sessions() as s:
            c, a = await self._verrouiller(s, action_id)
            cid, nom = c.id, a.nom
            inscrire(s, auteur, "action.confirmer", "action_conversation", action_id)
            if nom == "annuler_tache":
                # passée confirmee et commitée d'abord : jamais exécutée deux fois
                tache_id = a.parametres["tache_id"]
                t = await s.get(Tache, tache_id)
                a.etat, a.lien = "confirmee", t and f"/projets/{t.projet_id}/kanban"
                c.etat, c.erreur = "en_cours", None
                await s.commit()
                try:
                    await self._annuler(action_id, nom, tache_id)
                finally:
                    self._reveiller()
                    self.lancer(cid)
                return
            etapes: list[int] = []
            try:
                async with s.begin_nested():
                    ex = await executer_action(s, self._catalogue, a)
                a.etat, a.resultat, a.lien = "confirmee", ex.resultat, ex.lien
                etapes = ex.etapes_a_lancer
                texte = f"Action n°{action_id} ({nom}) confirmée par Nicolas : {ex.resultat}"
            except (Refus, SQLAlchemyError) as e:
                if isinstance(e, Refus):
                    motif = e.message
                else:  # course rare (projet ou tâche supprimé entre-temps…)
                    journal.erreur(logger, "action %s : erreur de base à l'exécution", action_id)
                    motif = "le portail a changé entre-temps, réessaie de proposer l'action"
                a.etat, a.resultat = "echouee", motif
                texte = f"Action n°{action_id} ({nom}) refusée par le portail : {motif}"
            self._systeme(s, c, texte)
            await s.commit()
        for etape_id in etapes:
            self._chat.lancer(etape_id)
        self._reveiller()  # une tâche a pu entrer dans « Prête »
        self.lancer(cid)

    async def _annuler(self, action_id: int, nom: str, tache_id: int) -> None:
        try:
            await self._annuler_tache(tache_id)
            etat, resultat = "confirmee", "tâche annulée, revenue à faire"
            texte = f"Action n°{action_id} ({nom}) confirmée par Nicolas : {resultat}"
        except Exception as e:  # l'action est déjà confirmee : noter l'échec  # noqa: BLE001
            if not isinstance(e, Refus):
                journal.erreur(logger, "action %s : annulation de la tâche %s", action_id, tache_id)
            etat, resultat = "echouee", e.message if isinstance(e, Refus) else f"erreur : {e}"
            texte = f"Action n°{action_id} ({nom}) refusée par le portail : {resultat}"
        async with self._sessions() as s:
            a = await s.get(ActionConversation, action_id)
            c = await self._conversation(s, a.conversation_id)
            a.etat, a.resultat = etat, resultat
            self._systeme(s, c, texte)
            await s.commit()

    async def refuser(self, action_id: int, auteur: str) -> None:
        async with self._sessions() as s:
            c, a = await self._verrouiller(s, action_id)
            cid = c.id
            inscrire(s, auteur, "action.refuser", "action_conversation", action_id)
            a.etat = "refusee"
            self._systeme(s, c, f"Nicolas a refusé l'action n°{action_id} ({a.nom})")
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
        if agent.service:

            async def publier(part: str) -> None:
                self.diffuseur.ajouter_partiel(cid, part)
                self.diffuseur.publier(cid, {"type": "delta", "texte": part})

            return await streamer(self._llm, self._missions, agent, demande, publier)
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

        outils = OutilsPortail(self._sessions, agent.outils, self._catalogue, cid)
        resultat = await tourner(self._llm, self._missions, agent, demande, outils, sur_appel)
        visible = resultat.texte.strip()
        if visible:
            self.diffuseur.publier(cid, {"type": "delta", "texte": visible})
        return visible, resultat.limite_atteinte

    async def _tache(self, cid: int) -> None:
        d = self.diffuseur
        journal.commencer(conversation=cid)
        try:
            async with self._sessions() as s:
                agent = self._agent(await self._conversation(s, cid))
                journal.nouvelle_mission(agent.nom, agent.contexte_max)
                demande = construire_conversation(agent, await self._messages(s, cid))
            limite = False
            if agent.outils:
                visible, limite = await self._boucle(cid, agent, demande)
            else:
                visible = await self._streamer(cid, agent, demande)
            async with self._sessions() as s:
                c = await self._conversation(s, cid)
                if c.etat != "en_cours":
                    d.publier(cid, {"type": "fin"})  # les abonnés ne restent pas bloqués
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
            except Exception:  # noqa: BLE001
                # l'événement terminal part quand même : les abonnés ne doivent pas rester bloqués
                journal.erreur(
                    logger, "impossible d'enregistrer l'échec de la conversation %s", cid
                )
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
