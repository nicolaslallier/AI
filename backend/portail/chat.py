"""Chat en streaming : une tâche de fond par appel au modèle, diffusée en SSE."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portail import journal
from portail.agents import PRODUITS_ARCHITECTURE, Agent, Catalogue, agent_effectif
from portail.archimate import BlocInvalide
from portail.architecture import annexes_architecture, verifier_bloc
from portail.avis import ServiceAvis
from portail.contexte import construire, jauge
from portail.db import (
    Avis,
    Document,
    Etape,
    Message,
    Pipeline,
    Projet,
    Proposition,
    Tache,
    TacheDependance,
)
from portail.depots import Depots, ErreurDepot
from portail.etats import Etat
from portail.llm import ClientLLM, FiltreReflexion, retirer_reflexion
from portail.missions import Missions, completer, streamer, tourner
from portail.moteur import (
    UN_SEUL_ACTIF,
    Refus,
    annuler_pipeline,
    autre_actif,
    changer_etat,
    dernier_valide,
    spec_courante,
    terminer_etape,
)
from portail.outils import OutilsDepot, apercu
from portail.propositions import (
    PropositionLue,
    _raison,
    enregistrer_propositions,
    lire_propositions,
    plan_du_pipeline,
    schema_propositions,
    tout_accepter,
)
from portail.taches import deplacer_tache

logger = logging.getLogger(__name__)

# le document que le bouton « Rédiger … » produit, selon le produit de l'agent
LIVRABLE = {"vision": "la vision", "plan": "le plan", "architecture": "l'architecture"}


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


def budget_apercu(contexte_max: int) -> int:
    """Jetons de l'aperçu du dépôt : le quart du contexte, au plus 8k (lu huit fois par pipeline)."""
    return min(int(0.25 * contexte_max), 8192)


async def annexes(
    s: AsyncSession, catalogue: Catalogue, agent: Agent, etape: Etape, projet_id: int
) -> list[str]:
    """Messages système ajoutés après le prompt de l'agent (comptés dans la jauge)."""
    sortie = []
    if agent.produit in ("volet", "architecture"):
        sortie += await annexes_architecture(s, catalogue, etape)
    if agent.produit == "plan":
        if spec := await spec_courante(s, projet_id):
            sortie.append("Spec courante :\n\n" + spec.contenu)
        if plan := await dernier_valide(s, projet_id, "plan"):
            sortie.append("Plan validé précédent (à réviser) :\n\n" + plan.contenu)
    if agent.produit == "taches":
        if plan := await plan_du_pipeline(s, etape.pipeline_id):
            sortie.append("Plan validé :\n\n" + plan.contenu)
        taches = (
            await s.scalars(select(Tache).where(Tache.projet_id == projet_id).order_by(Tache.id))
        ).all()
        deps: dict[int, list[str]] = {}
        for a, b in (
            await s.execute(
                select(TacheDependance.tache_id, TacheDependance.depend_de_id)
                .join(Tache, Tache.id == TacheDependance.tache_id)
                .where(Tache.projet_id == projet_id)
                .order_by(TacheDependance.depend_de_id)
            )
        ).all():
            deps.setdefault(a, []).append(f"T{b}")
        # tout ce qu'une modification acceptée réécrit : l'agent doit le voir pour le reprendre
        champs = ("id", "titre", "description", "criteres", "fichiers", "colonne", "protegee")
        liste = [
            {
                **{c: getattr(t, c) for c in champs},
                "verrou": t.verrou,
                "depend_de": deps.get(t.id, []),
            }
            for t in taches
        ]
        sortie.append("Tâches existantes (JSON) :\n\n" + json.dumps(liste, ensure_ascii=False))
    ouverts = (
        await s.execute(
            select(Avis.agent, Avis.contenu)
            .join(Document, Document.id == Avis.document_id)
            .where(Document.etape_id == etape.id, Avis.etat == "ouvert")
            .order_by(Avis.id)
        )
    ).all()
    if ouverts:
        sortie.append(
            "Avis ouverts à prendre en compte :\n\n" + "\n".join(f"- {a} : {c}" for a, c in ouverts)
        )
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
        avis: ServiceAvis | None = None,
        missions: Missions | None = None,
    ):
        self._missions = missions
        self._sessions = sessions
        self._catalogue = catalogue
        self._llm = llm
        self.diffuseur = diffuseur
        self._depots = depots
        self._avis = avis
        self.taches: dict[int, asyncio.Task] = {}

    async def _etape(self, s: AsyncSession, etape_id: int) -> Etape:
        # ordre des verrous : projet d'abord, puis l'étape (deux envois simultanés se sérialisent)
        projet_id = await s.scalar(
            select(Pipeline.projet_id)
            .join(Etape, Etape.pipeline_id == Pipeline.id)
            .where(Etape.id == etape_id)
        )
        if projet_id is None:
            raise Refus(404, "étape introuvable")
        await s.scalar(select(Projet.id).where(Projet.id == projet_id).with_for_update())
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
        agent = agent_effectif(self._catalogue, etape.agent, etape.modele)
        if agent is None:
            raise Refus(409, f"agent « {etape.agent} » absent de agents.yaml")
        return agent

    def _agent_conversation(self, etape: Etape) -> Agent:
        agent = self._agent(etape)
        if agent.produit == "taches":
            raise Refus(409, "étape de propositions : utiliser le kanban")
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
            agent,
            messages,
            doc,
            consigne,
            await annexes(s, self._catalogue, agent, etape, pipeline.projet_id),
        )

    async def envoyer(self, etape_id: int, contenu: str, modele: str | None = None) -> None:
        async with self._sessions() as s:
            etape = await self._etape_relancable(s, etape_id)
            spec = self._agent_conversation(etape).produit == "spec"
            if etape.etat == Etat.EN_COURS:
                raise Refus(409, "une réponse est déjà en cours")
            if etape.etat != Etat.EN_ATTENTE:
                raise Refus(409, "étape non active")
            contenu = contenu.strip()
            if not contenu:
                raise Refus(422, "le message est vide")
            if modele and modele not in self._catalogue.modeles_permis:
                raise Refus(422, f"modèle non permis : {modele}")
            if (
                spec
                and not etape.modele
                and not await s.scalar(select(Message.id).where(Message.etape_id == etape_id))
            ):  # figé dès le premier message (choisi, sinon celui de l'agent)
                etape.modele = modele or self._agent(etape).modele
            agent = self._agent(etape)
            if modele and modele != agent.modele:
                raise Refus(409, f"modèle déjà figé : {agent.modele}")
            avec = await self._demande(s, etape, agent) + [{"role": "user", "content": contenu}]
            if jauge(agent, avec).niveau == "plein":
                raise Refus(
                    409,
                    "contexte presque plein : clique « Rédiger "
                    f"{LIVRABLE.get(agent.produit, 'la spec')} » pour continuer",
                )
            s.add(Message(etape_id=etape_id, role="user", contenu=contenu))
            etape.action = "repondre"
            await changer_etat(s, etape, Etat.EN_COURS)
            await s.commit()
        self.lancer(etape_id)

    async def rediger(self, etape_id: int) -> None:
        async with self._sessions() as s:
            etape = await self._etape_relancable(s, etape_id)
            agent = self._agent_conversation(etape)
            if etape.etat != Etat.EN_ATTENTE:
                raise Refus(
                    409,
                    "étape non active"
                    if etape.etat != Etat.EN_COURS
                    else "une réponse est déjà en cours",
                )
            if not agent.consigne_redaction:
                raise Refus(409, "cet agent ne rédige pas de document")
            if agent.produit == "spec" and not etape.modele:  # le modèle auteur est figé
                etape.modele = agent.modele
            etape.action = "rediger"
            await changer_etat(s, etape, Etat.EN_COURS)
            await s.commit()
        self.lancer(etape_id)

    async def reessayer(self, etape_id: int) -> None:
        async with self._sessions() as s:
            etape = await self._etape_relancable(s, etape_id)
            if etape.etat != Etat.ECHOUEE:
                raise Refus(409, "seule une étape échouée peut être relancée")
            pipeline = await s.get(Pipeline, etape.pipeline_id)
            if pipeline.type == "doc":  # l'usine de doc mène ses étapes : on relance la carte
                raise Refus(409, "une étape doc se relance depuis sa carte du kanban doc")
            if pipeline.type in UN_SEUL_ACTIF and await autre_actif(
                s, pipeline.projet_id, pipeline.type, sauf=pipeline.id
            ):
                raise Refus(409, f"une autre {pipeline.type} est active pour ce projet")
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
            texte = await asyncio.to_thread(apercu, arbre, budget_apercu(agent.contexte_max))
            async with self._sessions() as s:
                e = await s.get(Etape, etape.id)
                e.sha, e.apercu = sha, texte
                await s.commit()
        return arbre

    async def _streamer(self, etape_id: int, agent: Agent, demande: list[dict]) -> str:
        if agent.service:

            async def publier(part: str) -> None:
                self.diffuseur.ajouter_partiel(etape_id, part)
                self.diffuseur.publier(etape_id, {"type": "delta", "texte": part})

            return await streamer(self._llm, self._missions, agent, demande, publier)
        filtre = FiltreReflexion()
        brut = ""
        async for morceau in self._llm.flux(
            agent.modele, demande, agent.temperature, agent.sortie_max, agent.reflexion
        ):
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

        resultat = await tourner(
            self._llm,
            self._missions,
            agent,
            demande,
            OutilsDepot(arbre, max_octets=agent.contexte_max),
            sur_appel,
        )
        visible = resultat.texte.strip()
        if visible:
            self.diffuseur.publier(etape_id, {"type": "delta", "texte": visible})
        return visible, resultat.limite_atteinte

    async def _proposer(
        self, agent: Agent, demande: list[dict], taches: dict[int, str | None]
    ) -> list[PropositionLue]:
        """Réponse JSON de l'agent de tâches ; une seule relance si elle est invalide."""
        format_ = {
            "type": "json_schema",
            "json_schema": {
                "name": "propositions",
                "schema": schema_propositions(sorted(i for i, r in taches.items() if r is None)),
            },
        }
        for essai in range(2):
            texte = (await completer(self._llm, self._missions, agent, demande, format_)).strip()
            try:
                return lire_propositions(texte, taches, ecarter=bool(essai))
            except ValueError as e:
                if essai:
                    raise ValueError(f"propositions invalides : {e}") from None
                demande = demande + [
                    {"role": "assistant", "content": texte},
                    {
                        "role": "user",
                        "content": f"Réponse invalide : {e}. Renvoie uniquement le JSON corrigé.",
                    },
                ]

    async def _enregistrer(
        self, s: AsyncSession, etape: Etape, agent: Agent, lues: list[PropositionLue]
    ) -> Etape | None:
        refus = await enregistrer_propositions(s, etape, lues, f"agent:{agent.nom}")
        if refus:
            s.add(
                Message(
                    etape_id=etape.id,
                    role="system",
                    contenu="propositions écartées : " + "; ".join(refus),
                )
            )
            await s.flush()
        if agent.sans_validation:  # le plan validé vaut accord : droit au kanban
            await tout_accepter(s, etape.id)
            # les tâches créées (pas les modifiées) partent en Prête, que le dev les prenne
            for tid in await s.scalars(
                select(Proposition.tache_creee_id)
                .where(Proposition.etape_id == etape.id, Proposition.tache_creee_id.is_not(None))
                .order_by(Proposition.id)
            ):
                await deplacer_tache(
                    s, await s.get(Tache, tid), "prete", None, f"agent:{agent.nom}"
                )
        ouvertes = await s.scalar(
            select(func.count()).where(
                Proposition.etape_id == etape.id, Proposition.etat == "ouverte"
            )
        )
        if ouvertes:
            await changer_etat(s, etape, Etat.EN_ATTENTE)
            return None
        return await terminer_etape(s, self._catalogue, etape)

    async def _tache(self, etape_id: int) -> None:
        d = self.diffuseur
        journal.commencer(etape=etape_id)
        try:
            async with self._sessions() as s:
                etape = await s.get(Etape, etape_id)
                journal.lier(pipeline=etape.pipeline_id)
                agent = self._agent(etape)
                journal.nouvelle_mission(agent.nom, agent.contexte_max)
                projet = await s.get(Projet, (await s.get(Pipeline, etape.pipeline_id)).projet_id)
            arbre = None
            if projet.depot_url and agent.outils:
                arbre = await self._preparer(etape, agent, projet)
            async with self._sessions() as s:
                etape = await s.get(Etape, etape_id)
                action = etape.action
                consigne = agent.consigne_redaction if action != "repondre" else None
                demande = await self._demande(s, etape, agent, consigne)
                cles = {
                    t.id: _raison(t, projet.id)
                    for t in await s.scalars(select(Tache).where(Tache.projet_id == projet.id))
                }
            limite, visible, suivante, a_relire = False, "", None, None
            erreur = None
            for essai in range(2):  # un produit d'architecture au bloc invalide : une relance
                if action == "taches":
                    lues = await self._proposer(agent, demande, cles)
                elif arbre is None:
                    visible = await self._streamer(etape_id, agent, demande)
                else:
                    visible, limite = await self._boucle(etape_id, agent, demande, arbre)
                if not (
                    visible and action != "repondre" and agent.produit in PRODUITS_ARCHITECTURE
                ):
                    break
                erreur = await self._erreur_bloc(etape_id, visible)
                if not erreur:
                    break
                if not essai:
                    demande = demande + [
                        {"role": "assistant", "content": visible},
                        {
                            "role": "user",
                            "content": f"Réponse invalide : {erreur}. "
                            "Rends le document complet corrigé.",
                        },
                    ]
            async with self._sessions() as s:
                etape = await self._etape(s, etape_id)  # projet verrouillé d'abord
                if etape.etat != Etat.EN_COURS:  # annulée entre-temps : on n'écrase rien
                    return
                if action == "taches":
                    suivante = await self._enregistrer(s, etape, agent, lues)
                elif not visible:
                    await changer_etat(s, etape, Etat.ECHOUEE, "réponse vide du modèle")
                    await s.commit()
                    await self._depots.liberer(etape_id)
                    d.publier(etape_id, {"type": "erreur", "message": "réponse vide du modèle"})
                    return
                else:
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
                        brouillon = await s.scalar(
                            select(Document.id).where(Document.etape_id == etape_id)
                        )
                        if erreur and (brouillon is None or agent.sans_validation):
                            raise BlocInvalide(erreur)  # étape échouée
                        if erreur:  # retouche ratée : le brouillon reste, Nicolas est prévenu
                            s.add(
                                Message(
                                    etape_id=etape_id,
                                    role="assistant",
                                    contenu="Je n'ai pas réussi à produire un document valide : "
                                    f"{erreur}. Le brouillon précédent est conservé.",
                                )
                            )
                        else:
                            etat_doc = "validee" if agent.sans_validation else "brouillon"
                            a_relire = await self._ecrire_document(
                                s, etape, agent, visible, etat_doc
                            )
                    if agent.sans_validation:  # volet accepté d'office : pas d'avis, on enchaîne
                        a_relire = None
                        suivante = await terminer_etape(s, self._catalogue, etape)
                    else:
                        await changer_etat(s, etape, Etat.EN_ATTENTE)
                await s.commit()
            if suivante:
                self.lancer(suivante.id)
            d.publier(etape_id, {"type": "fin"})
            if agent.sans_validation:  # étape terminée : son arbre ne sert plus, comme à valider
                await self._depots.liberer(etape_id)
            if a_relire and self._avis:
                try:
                    await self._avis.lancer(a_relire)
                except Exception:  # noqa: BLE001
                    journal.erreur(logger, "avis non lancés pour le document %s", a_relire)
        except Exception as exc:  # noqa: BLE001 - toute erreur doit finir en étape échouée
            try:
                async with self._sessions() as s:
                    etape = await self._etape(s, etape_id)
                    if etape.etat != Etat.EN_COURS:  # annulée entre-temps : on n'écrase rien
                        return
                    await changer_etat(s, etape, Etat.ECHOUEE, str(exc))
                    await s.commit()
            except Exception:  # noqa: BLE001
                # l'événement terminal part quand même : les abonnés ne doivent pas rester bloqués
                journal.erreur(logger, "impossible d'enregistrer l'échec de l'étape %s", etape_id)
            try:
                await self._depots.liberer(etape_id)
            except Exception:  # noqa: BLE001
                journal.erreur(logger, "impossible de libérer l'arbre de l'étape %s", etape_id)
            d.publier(etape_id, {"type": "erreur", "message": str(exc)})
        finally:
            d.oublier(etape_id)

    async def _erreur_bloc(self, etape_id: int, contenu: str) -> str | None:
        async with self._sessions() as s:
            etape = await s.get(Etape, etape_id)
            try:
                await verifier_bloc(s, self._catalogue, etape, contenu)
            except BlocInvalide as e:
                return str(e)

    async def _ecrire_document(
        self, s: AsyncSession, etape: Etape, agent: Agent, contenu: str, etat: str = "brouillon"
    ) -> int:
        dernier = await s.scalar(select(func.max(Message.id)).where(Message.etape_id == etape.id))
        pipeline = await s.get(Pipeline, etape.pipeline_id)
        doc = await s.scalar(select(Document).where(Document.etape_id == etape.id))
        if doc is None:
            doc = Document(projet_id=pipeline.projet_id, pipeline_id=pipeline.id, etape_id=etape.id)
            s.add(doc)
        else:
            doc.version += 1
        doc.type = agent.produit
        doc.contenu = contenu
        doc.etat = etat
        doc.dernier_message_id = dernier
        doc.maj_le = datetime.now(UTC)
        await s.flush()
        return doc.id

    async def _bloc_valide(self, s: AsyncSession, etape: Etape, contenu: str) -> None:
        """Refus 422 si le document d'architecture porte un bloc de modèle invalide."""
        agent = self._catalogue.agents.get(etape.agent)
        if agent and agent.produit in PRODUITS_ARCHITECTURE:
            try:
                await verifier_bloc(s, self._catalogue, etape, contenu)
            except BlocInvalide as e:
                raise Refus(422, str(e)) from None

    async def corriger(self, etape_id: int, contenu: str) -> Document:
        if not contenu.strip():
            raise Refus(422, "le document est vide")
        async with self._sessions() as s:
            etape = await self._etape_relancable(s, etape_id)
            doc = await s.scalar(select(Document).where(Document.etape_id == etape_id))
            if doc is None:
                raise Refus(409, "aucun brouillon à corriger")
            if doc.etat != "brouillon":
                spec = self._agent(etape).produit == "spec"
                raise Refus(409, "spec déjà validée" if spec else "document déjà validé")
            if etape.etat == Etat.EN_COURS:
                raise Refus(409, "une réponse est en cours")
            await self._bloc_valide(s, etape, contenu)
            doc.contenu = contenu
            doc.version += 1
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
                livrable = LIVRABLE.get(self._agent(etape).produit, "la spec")
                raise Refus(409, f"rien à valider : clique d'abord « Rédiger {livrable} »")
            await self._bloc_valide(s, etape, doc.contenu)
            doc.etat = "validee"
            doc.maj_le = datetime.now(UTC)
            suivante = await terminer_etape(s, self._catalogue, etape)
            await s.commit()
        if self._avis:
            try:
                await self._avis.abandonner(doc.id)
            except Exception:  # noqa: BLE001
                journal.erreur(logger, "avis non abandonnés pour le document %s", doc.id)
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
            # ordre des verrous : projet d'abord, comme _tache et les propositions
            projet_id = await s.scalar(select(Pipeline.projet_id).where(Pipeline.id == pipeline_id))
            await s.scalar(select(Projet.id).where(Projet.id == projet_id).with_for_update())
            pipeline = await s.scalar(
                select(Pipeline).where(Pipeline.id == pipeline_id).with_for_update()
            )
            await annuler_pipeline(s, pipeline)
            await s.commit()
            docs = (
                await s.scalars(select(Document.id).where(Document.pipeline_id == pipeline_id))
            ).all()
        # avant de libérer : un avis en cours ne finit pas `ouvert` ni ne recrée l'arbre
        for doc_id in docs if self._avis else ():
            try:
                await self._avis.abandonner(doc_id)
            except Exception:  # noqa: BLE001
                journal.erreur(logger, "avis non abandonnés pour le document %s", doc_id)
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
