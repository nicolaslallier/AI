"""Chat en streaming : une tâche de fond par appel au modèle, diffusée en SSE."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portail.agents import Agent, Catalogue
from portail.boucle import boucle_outils
from portail.contexte import construire, jauge
from portail.db import Document, Etape, Message, Pipeline, Projet
from portail.depots import Depots, ErreurDepot
from portail.etats import Etat
from portail.llm import ClientLLM, FiltreReflexion, retirer_reflexion
from portail.moteur import (
    Refus,
    annuler_pipeline,
    changer_etat,
    dernier_valide,
    spec_courante,
    terminer_etape,
)
from portail.outils import OutilsDepot, apercu

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


async def annexes(s: AsyncSession, agent: Agent, etape: Etape, projet_id: int) -> list[str]:
    """Messages système ajoutés après le prompt de l'agent (comptés dans la jauge)."""
    sortie = []
    if agent.produit == "plan":
        if spec := await spec_courante(s, projet_id):
            sortie.append("Spec courante :\n\n" + spec.contenu)
        if plan := await dernier_valide(s, projet_id, "plan"):
            sortie.append("Plan validé précédent (à réviser) :\n\n" + plan.contenu)
    # produit == "taches" : annexes de la tâche 9
    if etape.apercu:
        sortie.append(f"Aperçu du dépôt (SHA {etape.sha}) :\n\n" + etape.apercu)
    return sortie


def _sse(type_: str, donnees: dict) -> str:
    return f"event: {type_}\ndata: {json.dumps(donnees, ensure_ascii=False)}\n\n"


class ServiceChat:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        catalogue: Catalogue,
        llm: ClientLLM,
        diffuseur: Diffuseur,
        depots: Depots,
    ):
        self._sessions = sessions
        self._catalogue = catalogue
        self._llm = llm
        self.diffuseur = diffuseur
        self._depots = depots
        self.taches: dict[int, asyncio.Task] = {}

    async def _etape(self, s: AsyncSession, etape_id: int) -> Etape:
        # verrou de ligne : deux envois simultanés ne passent pas tous les deux
        etape = await s.scalar(select(Etape).where(Etape.id == etape_id).with_for_update())
        if etape is None:
            raise Refus(404, "étape introuvable")
        return etape

    async def _etape_relancable(self, s: AsyncSession, etape_id: int) -> Etape:
        etape = await self._etape(s, etape_id)
        if etape.erreur == "annulé":  # l'annulation est définitive
            raise Refus(409, "étape annulée")
        return etape

    def _agent(self, etape: Etape):
        agent = self._catalogue.agents.get(etape.agent)
        if agent is None:
            raise Refus(409, f"agent « {etape.agent} » absent de agents.yaml")
        return agent

    async def _contexte(self, s: AsyncSession, etape: Etape):
        messages = (
            await s.scalars(
                select(Message).where(Message.etape_id == etape.id).order_by(Message.id)
            )
        ).all()
        doc = await s.scalar(select(Document).where(Document.etape_id == etape.id))
        return messages, doc

    async def _demande(
        self, s: AsyncSession, etape: Etape, agent: Agent, consigne: str | None = None
    ) -> list[dict]:
        messages, doc = await self._contexte(s, etape)
        pipeline = await s.get(Pipeline, etape.pipeline_id)
        return construire(
            agent, messages, doc, consigne, await annexes(s, agent, etape, pipeline.projet_id)
        )

    async def envoyer(self, etape_id: int, contenu: str) -> None:
        async with self._sessions() as s:
            etape = await self._etape_relancable(s, etape_id)
            if etape.etat == Etat.EN_COURS:
                raise Refus(409, "une réponse est déjà en cours")
            if etape.etat != Etat.EN_ATTENTE:
                raise Refus(409, "étape non active")
            contenu = contenu.strip()
            if not contenu:
                raise Refus(422, "le message est vide")
            agent = self._agent(etape)
            avec = await self._demande(s, etape, agent) + [{"role": "user", "content": contenu}]
            if jauge(agent, avec).niveau == "plein":
                raise Refus(
                    409, "contexte presque plein : clique « Rédiger la spec » pour continuer"
                )
            s.add(Message(etape_id=etape_id, role="user", contenu=contenu))
            etape.action = "repondre"
            await changer_etat(s, etape, Etat.EN_COURS)
            await s.commit()
        self.lancer(etape_id)

    async def rediger(self, etape_id: int) -> None:
        async with self._sessions() as s:
            etape = await self._etape_relancable(s, etape_id)
            if etape.etat != Etat.EN_ATTENTE:
                raise Refus(
                    409,
                    "étape non active"
                    if etape.etat != Etat.EN_COURS
                    else "une réponse est déjà en cours",
                )
            if not self._agent(etape).consigne_redaction:
                raise Refus(409, "cet agent ne rédige pas de document")
            etape.action = "rediger"
            await changer_etat(s, etape, Etat.EN_COURS)
            await s.commit()
        self.lancer(etape_id)

    async def reessayer(self, etape_id: int) -> None:
        async with self._sessions() as s:
            etape = await self._etape_relancable(s, etape_id)
            if etape.etat != Etat.ECHOUEE:
                raise Refus(409, "seule une étape échouée peut être relancée")
            await changer_etat(s, etape, Etat.EN_COURS)
            await s.commit()
        self.lancer(etape_id)

    def lancer(self, etape_id: int) -> None:
        """Lance la tâche de fond d'une étape déjà mise en_cours (et commitée)."""
        tache = asyncio.create_task(self._tache(etape_id))
        self.taches[etape_id] = tache  # référence forte : asyncio ne garde qu'une référence faible

        def _fini(t: asyncio.Task) -> None:
            if self.taches.get(etape_id) is t:
                del self.taches[etape_id]

        tache.add_done_callback(_fini)

    async def _preparer(self, etape: Etape, agent: Agent, projet: Projet) -> Path:
        try:
            arbre, sha = await self._depots.preparer(
                projet.id, projet.depot_url, projet.branche_ref, etape.id, etape.sha
            )
        except ErreurDepot as e:
            raise ErreurDepot(f"dépôt : {e}") from None
        if etape.apercu is None:  # première préparation : point de départ figé pour l'étape
            texte = await asyncio.to_thread(apercu, arbre, int(0.25 * agent.contexte_max))
            async with self._sessions() as s:
                e = await s.get(Etape, etape.id)
                e.sha, e.apercu = sha, texte
                await s.commit()
        return arbre

    async def _streamer(self, etape_id: int, agent: Agent, demande: list[dict]) -> str:
        filtre = FiltreReflexion()
        brut = ""
        async for morceau in self._llm.flux(agent.modele, demande, agent.temperature):
            brut += morceau
            if part := filtre.envoyer(morceau):
                self.diffuseur.ajouter_partiel(etape_id, part)
                self.diffuseur.publier(etape_id, {"type": "delta", "texte": part})
        return retirer_reflexion(brut).strip()

    async def _boucle(
        self, etape_id: int, agent: Agent, demande: list[dict], arbre: Path
    ) -> tuple[str, bool]:
        async def sur_appel(libelle: str, resultat: str) -> None:
            async with self._sessions() as s:
                s.add(
                    Message(etape_id=etape_id, role="tool", outil=libelle, contenu=resultat[:2000])
                )
                await s.commit()
            self.diffuseur.publier(etape_id, {"type": "outil", "libelle": libelle})

        resultat = await boucle_outils(self._llm, agent, demande, OutilsDepot(arbre), sur_appel)
        visible = resultat.texte.strip()
        if visible:
            self.diffuseur.publier(etape_id, {"type": "delta", "texte": visible})
        return visible, resultat.limite_atteinte

    async def _tache(self, etape_id: int) -> None:
        d = self.diffuseur
        try:
            async with self._sessions() as s:
                etape = await s.get(Etape, etape_id)
                agent = self._agent(etape)
                projet = await s.get(Projet, (await s.get(Pipeline, etape.pipeline_id)).projet_id)
            arbre = None
            if projet.depot_url and agent.outils:
                arbre = await self._preparer(etape, agent, projet)
            async with self._sessions() as s:
                etape = await s.get(Etape, etape_id)
                action = etape.action
                consigne = agent.consigne_redaction if action != "repondre" else None
                demande = await self._demande(s, etape, agent, consigne)
            limite = False
            if arbre is None:
                visible = await self._streamer(etape_id, agent, demande)
            else:
                visible, limite = await self._boucle(etape_id, agent, demande, arbre)
            async with self._sessions() as s:
                etape = await self._etape(s, etape_id)
                if etape.etat != Etat.EN_COURS:  # annulée entre-temps : on n'écrase rien
                    return
                if not visible:
                    await changer_etat(s, etape, Etat.ECHOUEE, "réponse vide du modèle")
                    await s.commit()
                    await self._depots.liberer(etape_id)
                    d.publier(etape_id, {"type": "erreur", "message": "réponse vide du modèle"})
                    return
                if limite:
                    s.add(
                        Message(
                            etape_id=etape_id,
                            role="system",
                            contenu=f"limite de {agent.tours_max} appels d'outils atteinte : "
                            "la réponse peut être incomplète",
                        )
                    )
                    await s.flush()
                if action == "repondre":
                    s.add(Message(etape_id=etape_id, role="assistant", contenu=visible))
                else:
                    await self._ecrire_document(s, etape, agent, visible)
                await changer_etat(s, etape, Etat.EN_ATTENTE)
                await s.commit()
            d.publier(etape_id, {"type": "fin"})
        except Exception as exc:  # noqa: BLE001 - toute erreur doit finir en étape échouée
            try:
                async with self._sessions() as s:
                    etape = await self._etape(s, etape_id)
                    if etape.etat != Etat.EN_COURS:  # annulée entre-temps : on n'écrase rien
                        return
                    await changer_etat(s, etape, Etat.ECHOUEE, str(exc))
                    await s.commit()
            except Exception:
                # l'événement terminal part quand même : les abonnés ne doivent pas rester bloqués
                logger.exception("impossible d'enregistrer l'échec de l'étape %s", etape_id)
            try:
                await self._depots.liberer(etape_id)
            except Exception:
                logger.exception("impossible de libérer l'arbre de l'étape %s", etape_id)
            d.publier(etape_id, {"type": "erreur", "message": str(exc)})
        finally:
            d.oublier(etape_id)

    async def _ecrire_document(
        self, s: AsyncSession, etape: Etape, agent: Agent, contenu: str
    ) -> None:
        dernier = await s.scalar(select(func.max(Message.id)).where(Message.etape_id == etape.id))
        pipeline = await s.get(Pipeline, etape.pipeline_id)
        doc = await s.scalar(select(Document).where(Document.etape_id == etape.id))
        if doc is None:
            doc = Document(projet_id=pipeline.projet_id, pipeline_id=pipeline.id, etape_id=etape.id)
            s.add(doc)
        doc.type = agent.produit
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
            suivante = await terminer_etape(s, self._catalogue, etape)
            await s.commit()
        await self._depots.liberer(etape_id)
        if suivante:
            self.lancer(suivante.id)
        return etape.pipeline_id

    async def annuler(self, pipeline_id: int) -> None:
        async with self._sessions() as s:
            if await s.get(Pipeline, pipeline_id) is None:
                raise Refus(404, "pipeline introuvable")
            ids = (
                await s.scalars(
                    select(Etape.id).where(
                        Etape.pipeline_id == pipeline_id,
                        Etape.etat.in_([Etat.EN_COURS, Etat.EN_ATTENTE]),
                    )
                )
            ).all()
        # la tâche de fond s'arrête avant l'annulation : elle ne peut plus rien écrire après
        taches = [t for i in ids if (t := self.taches.get(i))]
        for t in taches:
            t.cancel()
        if taches:
            await asyncio.wait(taches)
        async with self._sessions() as s:
            pipeline = await s.scalar(
                select(Pipeline).where(Pipeline.id == pipeline_id).with_for_update()
            )
            await annuler_pipeline(s, pipeline)
            await s.commit()
        for i in ids:
            self.diffuseur.publier(i, {"type": "erreur", "message": "annulé"})
            await self._depots.liberer(i)

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
