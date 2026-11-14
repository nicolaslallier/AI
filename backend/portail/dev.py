"""Orchestrateur du pipeline `dev` : une tâche *Prête* devient une PR en brouillon.

tests (agent) → rouge (portail) → code (agent) → vérification (portail) → revue (agent) → PR.
L'état du pipeline et de ses étapes est écrit ici seul, sans `changer_etat`.
"""

import asyncio
import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portail.agents import Catalogue
from portail.boucle import ErreurOutils, boucle_outils
from portail.config import Reglages
from portail.contexte import construire
from portail.db import CommandeLancee, Etape, ExecutionDev, Message, Pipeline, Projet, Tache
from portail.depots import ErreurDepot, git
from portail.espace import Espace
from portail.etats import Etat
from portail.execution import (
    ConfigExecution,
    commande,
    correspond,
    dossiers_lecture_seule,
    lire_config,
)
from portail.github import ErreurGitHub, depot_depuis_url
from portail.lanceur import ErreurLanceur, Resultat
from portail.llm import ErreurLLM, retirer_reflexion
from portail.moteur import Refus
from portail.outils import OutilsDepot, OutilsEspace, apercu, empreinte
from portail.protections import COURRIEL_CODE, verifier_commits_code
from portail.taches import deplacer_tache

logger = logging.getLogger(__name__)

AUTEUR_TESTS = ("agent-tests", "agent-tests@portail.local")
AUTEUR_CODE = ("agent-code", COURRIEL_CODE)
PROTECTION = "protection des tests"
PASSENT_DEJA = "les tests passent déjà : ils ne testent rien de nouveau"
ILLISIBLE = "revue automatique illisible"
_FIN_SORTIE = 3000


class _Blocage(Exception):
    def __init__(self, raison: str):
        super().__init__(raison)
        self.raison = raison


class Verdict(BaseModel):
    decision: Literal["ok", "renvoyer_tests", "renvoyer_code"]
    remarques: list[str] = []


FORMAT_VERDICT = {
    "type": "json_schema",
    "json_schema": {"name": "verdict", "schema": Verdict.model_json_schema()},
}


def _lire_verdict(texte: str) -> Verdict | None:
    try:
        return Verdict.model_validate_json(texte)
    except ValidationError:
        return None


def slug(titre: str) -> str:
    s = unicodedata.normalize("NFKD", titre).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40].strip("-") or "tache"


def _liste(titre: str, elements: list[str]) -> str:
    return titre + "\n" + "\n".join(f"- {e}" for e in elements)


def _texte_tache(t: Tache) -> str:
    blocs = [f"Tâche : {t.titre}\n\n{t.description or '(pas de description)'}"]
    if t.criteres:
        blocs.append(_liste("Critères d'acceptation :", t.criteres))
    if t.fichiers:
        blocs.append(_liste("Fichiers indicatifs :", t.fichiers))
    return "\n\n".join(blocs)


@dataclass
class _Ctx:
    pipeline_id: int
    ex: ExecutionDev
    projet: Projet
    tache: Tache
    cfg: ConfigExecution
    depot: str
    espace: Espace
    phase: str = ""
    etape_id: int | None = None

    @property
    def racine(self) -> Path:
        return self.espace.racine


class Orchestrateur:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        catalogue: Catalogue,
        llm,
        lanceur,
        github,
        reglages: Reglages,
        horloge: Callable[[], datetime] = lambda: datetime.now(UTC),
        depot_de: Callable[[str], str] = depot_depuis_url,
    ):
        self._sessions = sessions
        self._catalogue = catalogue
        self._llm = llm
        self._lanceur = lanceur
        self._github = github
        self._reglages = reglages
        self._horloge = horloge
        self._depot_de = depot_de
        self.taches: dict[int, asyncio.Task] = {}

    # --- cycle de vie ---------------------------------------------------

    async def demarrer(self, session: AsyncSession, tache: Tache) -> Pipeline:
        """Dans la transaction de l'appelant : pipeline, exécution, tâche en cours verrouillée."""
        projet = await session.get(Projet, tache.projet_id)
        base = projet.branche_ref or await self._github.branche_defaut(
            self._depot_de(projet.depot_url or "")
        )
        n = 1 + await session.scalar(select(func.count()).where(ExecutionDev.tache_id == tache.id))
        branche = f"portail/tache-{tache.id}-{slug(tache.titre)}" + (f"-{n}" if n > 1 else "")
        pipeline = Pipeline(projet_id=projet.id, type="dev", etat=Etat.EN_COURS)
        session.add(pipeline)
        await session.flush()
        session.add(
            ExecutionDev(
                pipeline_id=pipeline.id, tache_id=tache.id, n=n, branche=branche,
                espace=f"tache-{tache.id}-{n}", base=base, base_sha="", phase="preparation",
                remarques=[], fichiers_tests=[],
            )
        )  # fmt: skip
        await deplacer_tache(session, tache, "en_cours", None, "portail")
        tache.verrou = pipeline.id
        await session.flush()
        return pipeline

    def lancer(self, pipeline_id: int) -> None:
        tache = asyncio.create_task(self.executer(pipeline_id))
        self.taches[pipeline_id] = tache  # référence forte

        def _fini(t: asyncio.Task) -> None:
            if self.taches.get(pipeline_id) is t:
                del self.taches[pipeline_id]

        tache.add_done_callback(_fini)

    async def executer(self, pipeline_id: int) -> None:
        delai = asyncio.timeout(self._reglages.duree_max_tache_s)
        try:
            async with delai:
                await self._derouler(pipeline_id)
            return
        except _Blocage as e:
            raison = e.raison
        except TimeoutError:
            raison = "durée maximale dépassée"
            if not delai.expired():  # un délai interne, pas celui de la tâche
                logger.exception("pipeline dev %s : erreur inattendue", pipeline_id)
                raison = "erreur inattendue : TimeoutError"
        except Refus as e:  # config stockée qui ne passe plus la validation
            raison = e.message
        except (ErreurLanceur, ErreurGitHub, ErreurDepot, ErreurLLM, ErreurOutils) as e:
            raison = str(e)
        except Exception as e:  # dernier recours : une tâche ne reste jamais verrouillée en cours
            logger.exception("pipeline dev %s : erreur inattendue", pipeline_id)
            raison = f"erreur inattendue : {type(e).__name__}"
        await self.bloquer(pipeline_id, raison)

    async def _derouler(self, pipeline_id: int) -> None:
        ctx = await self._charger(pipeline_id)
        phase = ctx.ex.phase
        if phase not in ("preparation", "fini"):  # phase relancée : on repart de HEAD
            await ctx.espace.remettre_a_zero()
        phases = {
            "preparation": self._preparation, "tests": self._tests, "rouge": self._rouge,
            "code": self._code, "verification": self._verification, "revue": self._revue,
            "pr": self._pr,
        }  # fmt: skip
        while phase != "fini":
            await self._maj(ctx, phase=phase)
            ctx.phase = phase
            phase = await phases[phase](ctx)

    async def _charger(self, pipeline_id: int) -> _Ctx:
        async with self._sessions() as s:
            ex = await s.scalar(select(ExecutionDev).where(ExecutionDev.pipeline_id == pipeline_id))
            tache = await s.get(Tache, ex.tache_id)
            projet = await s.get(Projet, tache.projet_id)
        if not projet.depot_url or not projet.config_execution:
            raise _Blocage("projet sans dépôt ou sans configuration d'exécution")
        return _Ctx(
            pipeline_id=pipeline_id, ex=ex, projet=projet, tache=tache,
            cfg=lire_config(projet.config_execution), depot=self._depot_de(projet.depot_url),
            espace=Espace(self._reglages.espaces_dir / ex.espace, projet.depot_url),
        )  # fmt: skip

    # --- écritures en base ----------------------------------------------

    async def _maj(self, ctx: _Ctx, **champs) -> None:
        async with self._sessions() as s:
            await s.execute(
                update(ExecutionDev).where(ExecutionDev.id == ctx.ex.id).values(**champs)
            )
            await s.commit()
        for k, v in champs.items():
            setattr(ctx.ex, k, v)

    async def _etape(self, ctx: _Ctx, agent: str, action: str | None = None) -> None:
        async with self._sessions() as s:
            dernier = await s.scalar(
                select(func.max(Etape.ordre)).where(Etape.pipeline_id == ctx.pipeline_id)
            )
            etape = Etape(
                pipeline_id=ctx.pipeline_id, ordre=(dernier if dernier is not None else -1) + 1,
                agent=agent, action=action, etat=Etat.EN_COURS,
            )  # fmt: skip
            s.add(etape)
            await s.commit()
        ctx.etape_id = etape.id

    async def _finir_etape(self, ctx: _Ctx, erreur: str | None = None) -> None:
        etat = Etat.ECHOUEE if erreur else Etat.TERMINEE
        async with self._sessions() as s:
            await s.execute(
                update(Etape).where(Etape.id == ctx.etape_id).values(etat=etat, erreur=erreur)
            )
            await s.commit()

    async def _message(self, ctx: _Ctx, role: str, contenu: str, outil: str | None = None):
        async with self._sessions() as s:
            s.add(Message(etape_id=ctx.etape_id, role=role, contenu=contenu, outil=outil))
            await s.commit()

    # --- commandes --------------------------------------------------------

    async def _commande(self, ctx: _Ctx, nom: str, fichiers: list[str] = ()) -> Resultat:
        """Lance une commande nommée ; pendant `code` et `verification`, protège les tests."""
        protege = ctx.phase in ("code", "verification")
        lecture_seule, avant = [], {}
        if protege:  # recalculé à chaque fois : jamais en cache
            lecture_seule = dossiers_lecture_seule(ctx.cfg, ctx.racine)
            avant = await asyncio.to_thread(empreinte, ctx.racine, ctx.cfg.protege)
        debut = self._horloge()
        r = await self._lanceur.lancer(
            ctx.ex.espace, ctx.cfg.image, commande(ctx.cfg, nom, fichiers),
            self._reglages.delai_commande_s, lecture_seule,
        )  # fmt: skip
        sortie = r.sortie
        if protege and (restaures := await self._restaurer_proteges(ctx, avant)):
            sortie += f"\n[fichiers de tests restaurés : {', '.join(restaures)}]"
        async with self._sessions() as s:
            s.add(
                CommandeLancee(
                    pipeline_id=ctx.pipeline_id, etape_id=ctx.etape_id, nom=nom, code=r.code,
                    delai_depasse=r.delai_depasse, sortie=sortie, debut=debut, fin=self._horloge(),
                )
            )  # fmt: skip
            await s.commit()
        return Resultat(code=r.code, sortie=sortie, delai_depasse=r.delai_depasse)

    async def _restaurer_proteges(self, ctx: _Ctx, avant: dict[str, str]) -> list[str]:
        apres = await asyncio.to_thread(empreinte, ctx.racine, ctx.cfg.protege)
        changes = {c for c in avant.keys() | apres.keys() if avant.get(c) != apres.get(c)}
        if not changes:
            return []
        faits = set(await ctx.espace.restaurer(lambda c: c not in changes))
        # le statut git ne voit pas les fichiers ignorés : un nouveau conftest.py ignoré compte
        reste = sorted(changes - faits)
        suivis = set()
        if reste:
            suivis = set((await git("ls-files", "-z", "--", *reste, cwd=ctx.racine)).split("\0"))
        racine = ctx.racine.resolve()
        for c in reste:
            p = racine / c
            if c in suivis or p.parent.resolve() != p.parent:
                continue
            if p.is_symlink() or p.is_file():
                p.unlink()
                faits.add(c)
        return sorted(faits & changes)

    def _outil_lancer(self, ctx: _Ctx):
        async def lancer(nom: str) -> str:
            tests = ctx.phase == "tests"
            fichiers = await self._fichiers_tests(ctx) if tests else ctx.ex.fichiers_tests
            r = await self._commande(ctx, nom, fichiers)
            return f"code {r.code}\n{r.sortie}"

        return lancer

    async def _fichiers_tests(self, ctx: _Ctx) -> list[str]:
        """Tests changés dans cette passe, plus ceux des passes précédentes encore présents."""
        candidats = {*await ctx.espace.changements(), *ctx.ex.fichiers_tests}
        return sorted(
            c
            for c in candidats
            if correspond(c, ctx.cfg.chemins_tests) and (ctx.racine / c).is_file()
        )

    # --- agents -----------------------------------------------------------

    async def _agent(
        self, ctx: _Ctx, nom: str, annexes: list[str], consigne: str, outils: OutilsDepot
    ) -> tuple[str, list[dict]]:
        agent = self._catalogue.agents[nom]
        await self._etape(ctx, nom)
        messages = construire(agent, [], None, consigne, annexes)

        async def sur_appel(libelle: str, resultat: str) -> None:
            await self._message(ctx, "tool", resultat[:2000], libelle)

        r = await boucle_outils(self._llm, agent, messages, outils, sur_appel)
        if r.limite_atteinte:
            await self._message(
                ctx, "system", f"limite de {agent.tours_max} appels d'outils atteinte"
            )
        texte = r.texte.strip()
        await self._message(ctx, "assistant", texte or "(réponse vide)")
        return texte, messages

    def _remarques(self, ctx: _Ctx) -> list[str]:
        if not ctx.ex.remarques:
            return []
        return [_liste("Remarques à prendre en compte :", ctx.ex.remarques)]

    # --- phases -------------------------------------------------------------

    async def _preparation(self, ctx: _Ctx) -> str:
        await self._etape(ctx, "portail", "preparation")
        if not await self._github.branche_protegee(ctx.depot, ctx.ex.base):
            raise _Blocage("branche par défaut non protégée")
        jeton = await self._github.jeton(ctx.depot)
        sha = await ctx.espace.cloner(ctx.projet.depot_url, jeton, ctx.ex.base, ctx.ex.branche)
        if ctx.cfg.services:
            await self._lanceur.services(ctx.ex.espace, ctx.cfg.services)
        r = await self._commande(ctx, "installer")
        if r.code != 0:
            raise _Blocage(f"installation échouée :\n{r.sortie[-_FIN_SORTIE:]}")
        await self._maj(ctx, base_sha=sha)
        await self._finir_etape(ctx)
        return "tests"

    async def _tests(self, ctx: _Ctx) -> str:
        agent = self._catalogue.agents["tests"]
        texte_apercu = await asyncio.to_thread(apercu, ctx.racine, int(0.25 * agent.contexte_max))
        annexes = [
            _texte_tache(ctx.tache),
            _liste("Chemins de tests autorisés :", ctx.cfg.protege),
            "Aperçu du dépôt :\n\n" + texte_apercu,
            *self._remarques(ctx),
        ]
        outils = OutilsEspace(ctx.racine, "tests", ctx.cfg, self._outil_lancer(ctx))
        await self._agent(ctx, "tests", annexes, "Écris les tests de cette tâche.", outils)
        annules = await ctx.espace.restaurer(lambda c: correspond(c, ctx.cfg.protege))
        if annules:
            await self._message(
                ctx, "system", _liste("Changements hors des tests annulés :", annules)
            )
        fichiers = await self._fichiers_tests(ctx)
        if not fichiers:
            raise _Blocage("aucun test écrit")
        await self._maj(ctx, fichiers_tests=fichiers)
        await ctx.espace.commiter(*AUTEUR_TESTS, f"test: {ctx.tache.titre}")
        await self._finir_etape(ctx)
        # après un renvoi de la revue, le code existe déjà : pas de vérification rouge
        return "code" if ctx.ex.renvois else "rouge"

    async def _rouge(self, ctx: _Ctx) -> str:
        await self._etape(ctx, "portail", "rouge")
        r = await self._commande(ctx, "tests_cibles", ctx.ex.fichiers_tests)
        if r.delai_depasse:
            raise _Blocage(
                f"délai dépassé pendant la vérification rouge :\n{r.sortie[-_FIN_SORTIE:]}"
            )
        if r.code == 5:
            raise _Blocage("aucun test collecté")
        if r.code == 0:
            async with self._sessions() as s:
                deja = await s.scalar(
                    select(func.count()).where(
                        Etape.pipeline_id == ctx.pipeline_id,
                        Etape.action == "rouge",
                        Etape.erreur == PASSENT_DEJA,
                    )
                )
            if deja:
                raise _Blocage(PASSENT_DEJA)
            await self._finir_etape(ctx, PASSENT_DEJA)
            await self._maj(ctx, remarques=[PASSENT_DEJA])
            return "tests"
        await self._maj(ctx, sortie_rouge=r.sortie, remarques=[])
        await self._finir_etape(ctx)
        return "code"

    async def _code(self, ctx: _Ctx) -> str:
        annexes = [
            _texte_tache(ctx.tache),
            _liste("Fichiers de tests de la tâche (à faire passer) :", ctx.ex.fichiers_tests),
        ]
        if ctx.ex.sortie_rouge:
            annexes.append("Sortie des tests avant ton travail :\n\n" + ctx.ex.sortie_rouge)
        annexes += self._remarques(ctx)
        outils = OutilsEspace(ctx.racine, "code", ctx.cfg, self._outil_lancer(ctx))
        await self._agent(ctx, "code", annexes, "Écris le code qui fait passer ces tests.", outils)
        annules = await ctx.espace.restaurer(lambda c: not correspond(c, ctx.cfg.protege))
        if annules:
            await self._message(ctx, "system", _liste("Changements de tests annulés :", annules))
        await ctx.espace.commiter(*AUTEUR_CODE, f"feat: {ctx.tache.titre}")  # vide : pas d'erreur
        await self._finir_etape(ctx)
        return "verification"

    async def _verification(self, ctx: _Ctx) -> str:
        await self._etape(ctx, "portail", "verification")
        for nom, fichiers in (("tests_cibles", ctx.ex.fichiers_tests), ("tests", [])):
            r = await self._commande(ctx, nom, fichiers)
            if r.code != 0:
                raise _Blocage(f"vérification échouée ({nom}) :\n{r.sortie[-_FIN_SORTIE:]}")
        if violations := await verifier_commits_code(ctx.espace, ctx.ex.base_sha, ctx.cfg):
            raise _Blocage(f"{PROTECTION} : " + ", ".join(violations))
        await self._finir_etape(ctx)
        return "revue"

    async def _revue(self, ctx: _Ctx) -> str:
        agent = self._catalogue.agents["revue"]
        diff = await ctx.espace.diff(ctx.ex.base_sha)
        annexes = [_texte_tache(ctx.tache), "Diff de la tâche :\n\n" + (diff or "(vide)")]
        consigne = "Relis ce diff et rends ton verdict en JSON."
        texte, messages = await self._agent(
            ctx, "revue", annexes, consigne, OutilsDepot(ctx.racine)
        )
        verdict = _lire_verdict(texte)
        if verdict is None:  # une seule relance, avec le format imposé
            messages += [
                {"role": "assistant", "content": texte},
                {"role": "user", "content": "Réponse invalide : renvoie uniquement le JSON."},
            ]
            rep = await self._llm.completer(
                agent.modele, messages, agent.temperature, response_format=FORMAT_VERDICT
            )
            texte = retirer_reflexion(rep.get("content") or "").strip()
            await self._message(ctx, "assistant", texte or "(réponse vide)")
            verdict = _lire_verdict(texte)
        if verdict is None:
            verdict, non_resolues = Verdict(decision="ok", remarques=[ILLISIBLE]), [ILLISIBLE]
        elif verdict.decision == "ok":
            non_resolues = []
        elif ctx.ex.renvois < self._reglages.renvois_max:
            await self._message(ctx, "system", _resume(verdict))
            await self._maj(ctx, renvois=ctx.ex.renvois + 1, remarques=verdict.remarques)
            await self._finir_etape(ctx)
            return "tests" if verdict.decision == "renvoyer_tests" else "code"
        else:
            non_resolues = verdict.remarques or [f"{verdict.decision} après le dernier renvoi"]
        await self._message(ctx, "system", _resume(verdict))
        await self._maj(ctx, remarques=non_resolues)
        await self._finir_etape(ctx)
        return "pr"

    async def _pr(self, ctx: _Ctx) -> str:
        await self._etape(ctx, "portail", "pr")
        jeton = await self._github.jeton(ctx.depot)
        await ctx.espace.pousser(jeton, ctx.ex.branche)
        async with self._sessions() as s:
            precedentes = (
                await s.scalars(
                    select(ExecutionDev).where(
                        ExecutionDev.tache_id == ctx.tache.id,
                        ExecutionDev.id != ctx.ex.id,
                        ExecutionDev.pr_numero.is_not(None),
                    )
                )
            ).all()
            resume = await s.scalar(
                select(Message.contenu)
                .join(Etape, Etape.id == Message.etape_id)
                .where(
                    Etape.pipeline_id == ctx.pipeline_id,
                    Etape.agent == "revue",
                    Message.role == "system",
                )
                .order_by(Message.id.desc())
                .limit(1)
            )
        if ctx.ex.pr_numero is None:
            numero, url = await self._github.creer_pr(
                ctx.depot, ctx.ex.branche, ctx.ex.base, ctx.tache.titre, self._corps(ctx, resume)
            )
            await self._maj(ctx, pr_numero=numero, pr_url=url)
        async with self._sessions() as s:
            await s.scalar(select(Projet.id).where(Projet.id == ctx.projet.id).with_for_update())
            tache = await s.get(Tache, ctx.tache.id)
            verrou, tache.verrou = tache.verrou, None  # levé le temps du déplacement
            await s.flush()
            await deplacer_tache(s, tache, "en_revue", None, "portail")
            tache.verrou = verrou
            await s.execute(
                update(Pipeline)
                .where(Pipeline.id == ctx.pipeline_id)
                .values(etat=Etat.TERMINEE, maj_le=self._horloge())
            )
            await s.execute(
                update(Etape).where(Etape.id == ctx.etape_id).values(etat=Etat.TERMINEE)
            )
            await s.execute(
                update(ExecutionDev).where(ExecutionDev.id == ctx.ex.id).values(phase="fini")
            )
            await s.commit()
        await self._au_mieux("nettoyer", self._lanceur.nettoyer(ctx.ex.espace))
        for p in precedentes:  # au mieux : la nouvelle PR est ouverte, quoi qu'il arrive ici
            try:
                if await self._github.etat_pr(ctx.depot, p.pr_numero) == "ouverte":
                    await self._github.commenter(
                        ctx.depot, p.pr_numero, f"Remplacée par {ctx.ex.pr_url}"
                    )
                    await self._github.fermer_pr(ctx.depot, p.pr_numero)
            except Exception:
                logger.exception("fermeture de l'ancienne PR %s impossible", p.pr_numero)
        return "fini"

    def _corps(self, ctx: _Ctx, resume: str | None) -> str:
        kanban, pipeline = f"/projets/{ctx.projet.id}/kanban", f"/pipelines/{ctx.pipeline_id}"
        blocs = [
            f"Tâche du portail : [kanban]({kanban}) · [pipeline]({pipeline})",
            _liste("## Critères d'acceptation\n", ctx.tache.criteres or ["(aucun)"]),
            "## Revue\n\n" + (resume or "(pas de résumé)"),
        ]
        if ctx.ex.remarques:
            blocs.append(_liste("## Remarques non résolues\n", ctx.ex.remarques))
        return "\n\n".join(blocs)

    # --- blocage ------------------------------------------------------------

    async def _au_mieux(self, quoi: str, attente):
        """Attend `attente` ; une erreur est seulement journalisée (rend alors None)."""
        try:
            return await attente
        except Exception:
            logger.exception("pipeline dev : %s impossible", quoi)
            return None

    async def bloquer(self, pipeline_id: int, raison: str) -> None:
        logger.warning("pipeline dev %s bloqué : %s", pipeline_id, raison)
        try:
            async with self._sessions() as s:
                pipeline = await s.get(Pipeline, pipeline_id)
                ex = await s.scalar(
                    select(ExecutionDev).where(ExecutionDev.pipeline_id == pipeline_id)
                )
                depot_url = await s.scalar(
                    select(Projet.depot_url).where(Projet.id == pipeline.projet_id)
                )
        except Exception:
            logger.exception("blocage du pipeline %s : lecture impossible", pipeline_id)
            return
        if pipeline.etat in (Etat.TERMINEE, Etat.ECHOUEE):
            return
        espace = Espace(self._reglages.espaces_dir / ex.espace, depot_url)
        pousse = False
        if not raison.startswith(PROTECTION):
            pousse = await self._au_mieux("pousser", self._pousser_si_commits(espace, ex))
        await self._au_mieux("nettoyer", self._lanceur.nettoyer(ex.espace))
        await self._au_mieux("supprimer", espace.supprimer())
        try:
            async with self._sessions() as s:
                await s.scalar(
                    select(Projet.id).where(Projet.id == pipeline.projet_id).with_for_update()
                )
                etapes = (
                    await s.scalars(
                        select(Etape).where(Etape.pipeline_id == pipeline_id).order_by(Etape.ordre)
                    )
                ).all()
                for e in etapes:
                    if e.etat == Etat.EN_COURS:
                        e.etat, e.erreur = Etat.ECHOUEE, raison
                lignes = [raison, ""] + [
                    f"- {e.agent}{f' ({e.action})' if e.action else ''} : {e.etat}" for e in etapes
                ]
                if pousse:
                    lignes.append(f"\nbranche poussée : {ex.branche}")
                tache = await s.get(
                    Tache, ex.tache_id, with_for_update=True, populate_existing=True
                )
                if tache is not None and tache.verrou == pipeline_id:
                    tache.verrou = None
                    await s.flush()
                    await deplacer_tache(s, tache, "bloquee", None, "portail")
                    tache.resume_blocage = "\n".join(lignes)
                await s.execute(
                    update(Pipeline)
                    .where(Pipeline.id == pipeline_id)
                    .values(etat=Etat.ECHOUEE, maj_le=self._horloge())
                )
                await s.commit()
        except Exception:
            logger.exception("blocage du pipeline %s : état non enregistré", pipeline_id)

    async def _pousser_si_commits(self, espace: Espace, ex: ExecutionDev) -> bool:
        """Pousse la branche (sans PR) si un agent y a commité ; rend True si poussée."""
        if not ex.base_sha or not espace.racine.is_dir():
            return False
        agents = {AUTEUR_TESTS[1], AUTEUR_CODE[1]}
        if not any(a in agents for _, a, _ in await espace.commits(ex.base_sha)):
            return False
        jeton = await self._github.jeton(self._depot_de(espace.depot_url))
        await espace.pousser(jeton, ex.branche)
        return True


def _resume(v: Verdict) -> str:
    texte = f"Décision : {v.decision}"
    return _liste(texte + "\n", v.remarques) if v.remarques else texte
