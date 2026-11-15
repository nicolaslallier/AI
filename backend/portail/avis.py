"""Avis de l'architecte et du challenger sur un brouillon de spec ou de plan."""

import asyncio
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portail.agents import Catalogue, modele_pour
from portail.boucle import boucle_outils
from portail.contexte import construire
from portail.db import Avis, Document, Etape, Pipeline, Projet
from portail.depots import Depots
from portail.etats import Etat
from portail.llm import ClientLLM, retirer_reflexion
from portail.moteur import spec_courante
from portail.outils import OutilsDepot

logger = logging.getLogger(__name__)


async def _rien(libelle: str, resultat: str) -> None:
    pass


class ServiceAvis:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        catalogue: Catalogue,
        llm: ClientLLM,
        depots: Depots,
    ):
        self._sessions = sessions
        self._catalogue = catalogue
        self._llm = llm
        self._depots = depots
        self.taches: dict[tuple[int, str], asyncio.Task] = {}

    async def lancer(self, document_id: int) -> None:
        async with self._sessions() as s:
            # le verrou le sérialise avec la validation : un document validé n'a plus d'avis
            doc = await s.scalar(
                select(Document).where(Document.id == document_id).with_for_update()
            )
            if doc is None or doc.etat != "brouillon":
                return
            # un pipeline annulé garde des brouillons : pas de nouvel avis sur son arbre clos
            if (
                await s.scalar(select(Pipeline.etat).where(Pipeline.id == doc.pipeline_id))
                == Etat.ECHOUEE
            ):
                return
            noms = self._catalogue.avis.get(doc.type, [])
            for nom in noms:  # une relance remplace l'avis encore en cours du même agent
                if ancienne := self.taches.pop((document_id, nom), None):
                    ancienne.cancel()
            await s.execute(
                update(Avis)
                .where(
                    Avis.document_id == document_id, Avis.etat == "en_cours", Avis.agent.in_(noms)
                )
                .values(etat="abandonne")
            )
            lignes = [Avis(document_id=document_id, version=doc.version, agent=n) for n in noms]
            s.add_all(lignes)
            await s.commit()  # lignes visibles avant que les tâches ne les lisent
            for ligne in lignes:  # aucun await entre le commit et la création des tâches
                tache = asyncio.create_task(
                    self._tache(ligne.id, document_id, doc.contenu, doc.version)
                )
                cle = (document_id, ligne.agent)
                self.taches[cle] = tache  # référence forte

                def _fini(t: asyncio.Task, cle=cle) -> None:
                    if self.taches.get(cle) is t:
                        del self.taches[cle]

                tache.add_done_callback(_fini)

    async def abandonner(self, document_id: int) -> None:
        taches = [t for (d, _), t in self.taches.items() if d == document_id]
        for t in taches:
            t.cancel()
        if taches:
            await asyncio.wait(taches)
        async with self._sessions() as s:
            await s.execute(
                update(Avis)
                .where(Avis.document_id == document_id, Avis.etat == "en_cours")
                .values(etat="abandonne")
            )
            await s.commit()

    async def recuperer_interrompues(self, s: AsyncSession) -> None:
        await s.execute(update(Avis).where(Avis.etat == "en_cours").values(etat="abandonne"))

    async def _tache(self, avis_id: int, document_id: int, contenu: str, version: int) -> None:
        try:
            texte = await self._rediger(avis_id, document_id, contenu, version)
            async with self._sessions() as s:
                # le verrou du document le sérialise avec la validation de Nicolas
                doc = await s.scalar(
                    select(Document).where(Document.id == document_id).with_for_update()
                )
                valeurs = (
                    {"contenu": texte, "etat": "ouvert"}
                    if texte and doc is not None and doc.etat == "brouillon"
                    else {"etat": "abandonne"}
                )
                await s.execute(
                    update(Avis)
                    .where(Avis.id == avis_id, Avis.etat == "en_cours")
                    .values(**valeurs)
                )
                await s.commit()
        except asyncio.CancelledError:
            raise  # la ligne est déjà passée « abandonne » par celui qui annule
        except Exception:
            logger.exception("avis %s abandonné", avis_id)
            async with self._sessions() as s:
                await s.execute(
                    update(Avis)
                    .where(Avis.id == avis_id, Avis.etat == "en_cours")
                    .values(etat="abandonne")
                )
                await s.commit()

    async def _rediger(self, avis_id: int, document_id: int, contenu: str, version: int) -> str:
        async with self._sessions() as s:
            avis = await s.get(Avis, avis_id)
            doc = await s.get(Document, document_id)
            if avis is None or doc is None:  # supprimés pendant l'attente
                return ""
            etape = await s.get(Etape, doc.etape_id)
            projet = await s.get(Projet, (await s.get(Pipeline, etape.pipeline_id)).projet_id)
            annexes = [f"Brouillon à relire (version {version}) :\n\n{contenu}"]
            if doc.type == "plan" and (spec := await spec_courante(s, projet.id)):
                annexes.append("Spec courante :\n\n" + spec.contenu)
        if etape.apercu:
            annexes.append(f"Aperçu du dépôt (SHA {etape.sha}) :\n\n" + etape.apercu)
        agent = self._catalogue.agents[avis.agent]
        auteur = self._catalogue.agents[etape.agent]
        agent = agent.model_copy(update={"modele": modele_pour(agent, auteur)})
        demande = construire(agent, [], None, agent.consigne_avis, annexes)
        if agent.outils and projet.depot_url:
            arbre, _ = await self._depots.preparer(
                projet.id, projet.depot_url, projet.branche_ref, etape.id, etape.sha
            )
            resultat = await boucle_outils(self._llm, agent, demande, OutilsDepot(arbre), _rien)
            texte = resultat.texte
        else:
            reponse = await self._llm.completer(agent.modele, demande, agent.temperature)
            texte = reponse.get("content") or ""
        return retirer_reflexion(texte).strip()
