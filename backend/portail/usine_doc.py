"""Usine de documentation : une carte *À rédiger* du kanban doc devient une note du coffre.

rédaction (documentaliste, lecture seule du dépôt) → revue (verdict) → *À valider* → Nicolas
valide → écriture dans le coffre Obsidian → *Publié*. Rien n'est écrit dans le dépôt ; la seule
écriture dans le coffre passe par `valider`, appelée par la route du même nom.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portail import journal
from portail.agents import Catalogue, modele_pour
from portail.audit import inscrire
from portail.boucle import ErreurOutils
from portail.config import Reglages
from portail.contexte import construire
from portail.db import CarteDoc, Etape, Message, Pipeline, Projet
from portail.depots import Depots, ErreurDepot
from portail.dev import FORMAT_VERDICT, Verdict, lire_verdict
from portail.etats import Etat
from portail.llm import ErreurLLM, retirer_reflexion
from portail.missions import Missions, completer, tourner
from portail.moteur import Refus
from portail.notifications import Notifieur, lien_absolu
from portail.obsidian import Conflit
from portail.outils import OutilsDepot

logger = logging.getLogger(__name__)

GENRES = ("readme", "architecture", "runbook", "adr", "api", "guide", "autre")
EN_COURS = ("redaction", "revue")
TEXTE_MAX = 200_000  # octets, plafond d'écriture du coffre
_LECTURE = ["lister", "lire", "chercher"]


class _Echec(Exception):
    pass


def _fiche(carte: CarteDoc, projet: Projet) -> str:
    return (
        f"Document à rédiger pour le projet « {projet.nom} » : {carte.titre}\n"
        f"Genre : {carte.genre}\n\nConsigne de Nicolas :\n{carte.consigne or '(aucune)'}"
    )


def frontmatter(carte: CarteDoc, projet: str, maintenant: datetime) -> str:
    """JSON est du YAML valide : les valeurs sont toujours bien échappées."""
    champs = {
        "type": "doc", "projet": projet, "genre": carte.genre, "source": "portail",
        "depot_sha": carte.sha or "", "genere_le": maintenant.isoformat(timespec="seconds"),
    }  # fmt: skip
    lignes = [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in champs.items()]
    return "---\n" + "\n".join(lignes) + "\n---\n\n"


class UsineDoc:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        catalogue: Catalogue,
        llm,
        depots: Depots,
        coffre,
        reglages: Reglages,
        notifieur: Notifieur | None = None,
        missions: Missions | None = None,
    ):
        self._sessions = sessions
        self._catalogue = catalogue
        self._llm = llm
        self._depots = depots
        self.coffre = coffre  # None : coffre éteint, la validation répond 503
        self._reglages = reglages
        self._notifieur = notifieur
        self._missions = missions
        self.taches: dict[int, asyncio.Task] = {}  # par carte

    # --- tirage -------------------------------------------------------------

    async def tour(self, places: int) -> list[asyncio.Task]:
        """Démarre jusqu'à `places` cartes *À rédiger* sans erreur, par `id`."""
        lancees = []
        while len(lancees) < places:
            async with self._sessions() as s:
                carte = await s.scalar(
                    select(CarteDoc)
                    .join(Projet, Projet.id == CarteDoc.projet_id)
                    .where(
                        CarteDoc.colonne == "a_rediger",
                        CarteDoc.erreur.is_(None),
                        Projet.depot_url.is_not(None),
                    )
                    .order_by(CarteDoc.id)
                    .limit(1)
                    .with_for_update(skip_locked=True, of=CarteDoc)
                )
                if carte is None:
                    break
                pipeline = Pipeline(projet_id=carte.projet_id, type="doc", etat=Etat.EN_COURS)
                s.add(pipeline)
                await s.flush()
                carte.pipeline_id, carte.colonne = pipeline.id, "redaction"
                inscrire(s, "ordonnanceur", "pipeline.lancer", "pipeline", pipeline.id)
                await s.commit()
            lancees.append(self._lancer(carte.id))
        return lancees

    def _lancer(self, carte_id: int) -> asyncio.Task:
        tache = asyncio.create_task(self._executer(carte_id))
        self.taches[carte_id] = tache  # référence forte

        def _fini(t: asyncio.Task) -> None:
            if self.taches.get(carte_id) is t:
                del self.taches[carte_id]

        tache.add_done_callback(_fini)
        return tache

    async def reprendre(self) -> None:
        """Au démarrage : rien n'est en cours, tout repart d'*À rédiger*."""
        # ponytail: pas de compteur d'interruptions, une carte qui fait planter le Portail
        # repart à chaque démarrage ; en ajouter un si ça arrive
        async with self._sessions() as s:
            pipelines = select(Pipeline.id).where(
                Pipeline.type == "doc", Pipeline.etat == Etat.EN_COURS
            )
            await s.execute(
                update(Etape)
                .where(Etape.pipeline_id.in_(pipelines), Etape.etat == Etat.EN_COURS)
                .values(etat=Etat.ECHOUEE, erreur="interrompue par un redémarrage")
            )
            await s.execute(
                update(Pipeline)
                .where(Pipeline.type == "doc", Pipeline.etat == Etat.EN_COURS)
                .values(etat=Etat.ECHOUEE)
            )
            await s.execute(
                update(CarteDoc).where(CarteDoc.colonne.in_(EN_COURS)).values(colonne="a_rediger")
            )
            await s.commit()

    # --- déroulement ----------------------------------------------------------

    async def _executer(self, carte_id: int) -> None:
        journal.commencer(carte_doc=carte_id)
        delai = asyncio.timeout(self._reglages.duree_max_tache_s)
        try:
            async with delai:
                await self._derouler(carte_id)
            return
        except _Echec as e:
            cause = str(e)
        except TimeoutError:
            cause = "durée maximale dépassée" if delai.expired() else "délai dépassé"
        except (ErreurDepot, ErreurLLM, ErreurOutils) as e:  # messages déjà sans secret
            cause = str(e)[:300]
        except Exception as e:  # noqa: BLE001 — une carte ne reste jamais en cours
            journal.erreur(logger, "usine doc : carte %s, erreur inattendue", carte_id)
            cause = f"erreur inattendue : {type(e).__name__}"
        await self._echouer(carte_id, cause)

    async def _derouler(self, carte_id: int) -> None:
        redacteur_nom, relecteur_nom = self._catalogue.pipelines["doc"][:2]
        redacteur = self._catalogue.agents[redacteur_nom].model_copy(update={"outils": _LECTURE})
        relecteur = self._catalogue.agents[relecteur_nom]
        relecteur = relecteur.model_copy(update={"modele": modele_pour(relecteur, redacteur)})
        async with self._sessions() as s:
            carte = await s.get(CarteDoc, carte_id)
            projet = await s.get(Projet, carte.projet_id)
        journal.lier(pipeline=carte.pipeline_id)
        while True:
            etape_id = arbre_id = await self._etape(carte.pipeline_id, redacteur_nom)
            try:  # un arbre par passe, lu par le rédacteur puis par la revue
                arbre, sha = await self._depots.preparer(
                    projet.id, projet.depot_url, projet.branche_ref, arbre_id, None
                )
                outils = OutilsDepot(arbre, max_octets=redacteur.contexte_max)
                annexes = [_fiche(carte, projet)]
                if carte.remarques:
                    annexes += [
                        f"Brouillon précédent :\n\n{carte.contenu}",
                        "Remarques à prendre en compte :\n"
                        + "\n".join(f"- {r}" for r in carte.remarques),
                    ]
                consigne = "Rédige le document demandé, à partir du code du dépôt."
                texte = await self._agent(etape_id, redacteur, annexes, consigne, outils)
                if not texte or len(texte.encode()) > TEXTE_MAX:
                    raise _Echec("document vide ou trop long")
                await self._fin_etape(etape_id, carte_id, contenu=texte, sha=sha, colonne="revue")
                carte.contenu, carte.sha = texte, sha
                etape_id = await self._etape(carte.pipeline_id, relecteur_nom)
                verdict = await self._verdict(etape_id, relecteur, carte, projet, arbre)
            finally:
                await self._depots.liberer(arbre_id)
            if verdict.decision != "ok" and carte.renvois < self._reglages.renvois_max:
                carte.renvois += 1
                carte.remarques = verdict.remarques or ["à reprendre (sans détail)"]
                await self._fin_etape(
                    etape_id, carte_id, renvois=carte.renvois, remarques=carte.remarques,
                    colonne="redaction",
                )  # fmt: skip
                continue
            await self._fin_etape(
                etape_id, carte_id, remarques=verdict.remarques, colonne="a_valider"
            )
            break
        async with self._sessions() as s:
            await s.execute(
                update(Pipeline).where(Pipeline.id == carte.pipeline_id).values(etat=Etat.TERMINEE)
            )
            await s.commit()
        if self._notifieur:  # jamais le titre : ntfy est public
            lien = lien_absolu(self._reglages.url_publique, "/docs")
            try:
                await self._notifieur.envoyer(f"Portail — doc D{carte_id}", "Doc à valider", lien)
            except Exception as e:  # noqa: BLE001 — jamais str(e) : pas de fuite
                logger.warning("usine doc : notification impossible (%s)", type(e).__name__)

    async def _agent(self, etape_id: int, agent, annexes, consigne, outils) -> str:
        journal.nouvelle_mission(agent.nom, agent.contexte_max)
        messages = construire(agent, [], None, consigne, annexes)

        async def sur_appel(libelle: str, resultat: str) -> None:
            await self._message(etape_id, "tool", resultat[:2000], libelle)

        r = await tourner(self._llm, self._missions, agent, messages, outils, sur_appel)
        texte = retirer_reflexion(r.texte).strip()
        await self._message(etape_id, "assistant", texte or "(réponse vide)")
        return texte

    async def _verdict(self, etape_id, relecteur, carte, projet, arbre) -> Verdict:
        """Illisible même après une relance : le document passe *À valider*, Nicolas tranche."""
        annexes = [_fiche(carte, projet), f"Document à relire :\n\n{carte.contenu}"]
        consigne = (
            "Relis ce document : est-il fidèle au code du dépôt, complet et clair ? "
            "Rends ton verdict en JSON ; pour un renvoi, utilise renvoyer_code."
        )
        outils = OutilsDepot(arbre, max_octets=relecteur.contexte_max)
        texte = await self._agent(etape_id, relecteur, annexes, consigne, outils)
        verdict = lire_verdict(texte)
        if verdict is None:
            messages = construire(relecteur, [], None, consigne, annexes) + [
                {"role": "assistant", "content": texte},
                {"role": "user", "content": "Réponse invalide : renvoie uniquement le JSON."},
            ]
            texte = (
                await completer(self._llm, self._missions, relecteur, messages, FORMAT_VERDICT)
            ).strip()
            await self._message(etape_id, "assistant", texte or "(réponse vide)")
            verdict = lire_verdict(texte)
        return verdict or Verdict(decision="ok", remarques=["verdict illisible de la revue"])

    # --- écritures en base -----------------------------------------------------

    async def _etape(self, pipeline_id: int, agent: str) -> int:
        async with self._sessions() as s:
            n = len(
                (await s.scalars(select(Etape.id).where(Etape.pipeline_id == pipeline_id))).all()
            )
            etape = Etape(pipeline_id=pipeline_id, ordre=n, agent=agent, etat=Etat.EN_COURS)
            s.add(etape)
            await s.commit()
        journal.lier(etape=etape.id, agent=agent, mission=None, contexte_max=None)
        return etape.id

    async def _fin_etape(self, etape_id: int, carte_id: int, **carte) -> None:
        async with self._sessions() as s:
            await s.execute(update(Etape).where(Etape.id == etape_id).values(etat=Etat.TERMINEE))
            await s.execute(update(CarteDoc).where(CarteDoc.id == carte_id).values(**carte))
            await s.commit()

    async def _message(self, etape_id: int, role: str, contenu: str, outil: str | None = None):
        async with self._sessions() as s:
            s.add(Message(etape_id=etape_id, role=role, contenu=contenu, outil=outil))
            await s.commit()

    async def _echouer(self, carte_id: int, cause: str) -> None:
        async with self._sessions() as s:
            carte = await s.get(CarteDoc, carte_id)
            if carte is None:
                return
            carte.erreur, carte.colonne = cause, "a_rediger"
            await s.execute(
                update(Etape)
                .where(Etape.pipeline_id == carte.pipeline_id, Etape.etat == Etat.EN_COURS)
                .values(etat=Etat.ECHOUEE, erreur=cause)
            )
            await s.execute(
                update(Pipeline).where(Pipeline.id == carte.pipeline_id).values(etat=Etat.ECHOUEE)
            )
            await s.commit()

    # --- publication -----------------------------------------------------------

    async def valider(self, carte_id: int, forcer: bool = False) -> None:
        """La seule écriture dans le coffre. Le verrou de la carte sérialise deux validations."""
        if self.coffre is None:
            raise Refus(503, "coffre Obsidian éteint")
        async with self._sessions() as s:
            carte = await s.scalar(
                select(CarteDoc).where(CarteDoc.id == carte_id).with_for_update()
            )
            if carte is None:
                raise Refus(404, "carte introuvable")
            if carte.colonne != "a_valider":
                raise Refus(409, "seule une carte « à valider » se publie")
            projet = await s.get(Projet, carte.projet_id)
            maintenant = datetime.now(UTC)
            texte = frontmatter(carte, projet.nom, maintenant) + carte.contenu
            try:
                etag = await self.coffre.ecrire_doc(carte.chemin, texte, carte.etag, forcer)
            except Conflit as e:
                raise Refus(409, "la note du coffre a changé : forcer pour écraser") from e
            except ValueError as e:
                raise Refus(422, str(e)) from e
            except Exception as e:  # message fixe : jamais le secret S3
                logger.warning(
                    "usine doc : écriture dans le coffre impossible (%s)", type(e).__name__
                )
                raise Refus(502, "écriture dans le coffre impossible") from e
            carte.etag, carte.publie_le, carte.colonne = etag, maintenant, "publie"
            await s.commit()
