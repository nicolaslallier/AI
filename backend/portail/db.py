from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _horodatage(**kw):
    return mapped_column(DateTime(timezone=True), server_default=func.now(), **kw)


class Projet(Base):
    __tablename__ = "projet"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    depot_url: Mapped[str | None] = mapped_column(String)
    branche_ref: Mapped[str | None] = mapped_column(String)  # nul : branche par défaut du dépôt
    config_execution: Mapped[str | None] = mapped_column(Text)  # YAML brut
    cree_le: Mapped[datetime] = _horodatage()


class Pipeline(Base):
    __tablename__ = "pipeline"

    id: Mapped[int] = mapped_column(primary_key=True)
    projet_id: Mapped[int] = mapped_column(ForeignKey("projet.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String)
    etat: Mapped[str] = mapped_column(String, default="en_cours", server_default="en_cours")
    cree_le: Mapped[datetime] = _horodatage()
    maj_le: Mapped[datetime] = _horodatage(onupdate=func.now())

    etapes: Mapped[list["Etape"]] = relationship(order_by="Etape.ordre", back_populates="pipeline")


class Etape(Base):
    __tablename__ = "etape"

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipeline.id", ondelete="CASCADE"))
    ordre: Mapped[int]
    agent: Mapped[str] = mapped_column(String)
    etat: Mapped[str] = mapped_column(String, default="a_faire", server_default="a_faire")
    erreur: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(String)  # "repondre" | "rediger"
    sha: Mapped[str | None] = mapped_column(String)  # point de départ calculé une fois
    apercu: Mapped[str | None] = mapped_column(Text)
    modele: Mapped[str | None] = mapped_column(
        String
    )  # choix de l'utilisateur ; sinon celui de l'agent

    pipeline: Mapped[Pipeline] = relationship(back_populates="etapes")
    messages: Mapped[list["Message"]] = relationship(order_by="Message.id", back_populates="etape")
    document: Mapped["Document | None"] = relationship(back_populates="etape")


class Message(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(primary_key=True)
    etape_id: Mapped[int] = mapped_column(ForeignKey("etape.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String)  # user | assistant | system | tool
    contenu: Mapped[str] = mapped_column(Text)
    outil: Mapped[str | None] = mapped_column(String)  # libellé de l'appel, ex. lire(src/a.py)
    cree_le: Mapped[datetime] = _horodatage()

    etape: Mapped[Etape] = relationship(back_populates="messages")


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[int] = mapped_column(primary_key=True)
    titre: Mapped[str] = mapped_column(String(200), default="", server_default="")
    etat: Mapped[str] = mapped_column(String, default="pret", server_default="pret")
    agent: Mapped[str] = mapped_column(
        String, default="orchestrateur", server_default="orchestrateur"
    )
    erreur: Mapped[str | None] = mapped_column(Text)
    cree_le: Mapped[datetime] = _horodatage()
    maj_le: Mapped[datetime] = _horodatage(onupdate=func.now())


class Resume(Base):
    __tablename__ = "resume"

    id: Mapped[int] = mapped_column(primary_key=True)
    jour: Mapped[date] = mapped_column(Date, unique=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="SET NULL")
    )
    cree_le: Mapped[datetime] = _horodatage()


class MessageConversation(Base):
    __tablename__ = "message_conversation"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String)  # user | assistant | system | tool
    contenu: Mapped[str] = mapped_column(Text)
    outil: Mapped[str | None] = mapped_column(String)
    cree_le: Mapped[datetime] = _horodatage()


class ActionConversation(Base):
    __tablename__ = "action_conversation"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), index=True
    )
    nom: Mapped[str] = mapped_column(String)
    parametres: Mapped[dict] = mapped_column(JSON, default=dict)
    # proposee | confirmee | refusee | echouee | perimee
    etat: Mapped[str] = mapped_column(String, default="proposee", server_default="proposee")
    resultat: Mapped[str | None] = mapped_column(Text)
    lien: Mapped[str | None] = mapped_column(String)  # ex. /projets/12, /pipelines/34
    cree_le: Mapped[datetime] = _horodatage()
    maj_le: Mapped[datetime] = _horodatage(onupdate=func.now())


class Document(Base):
    __tablename__ = "document"

    id: Mapped[int] = mapped_column(primary_key=True)
    projet_id: Mapped[int] = mapped_column(ForeignKey("projet.id", ondelete="CASCADE"))
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipeline.id", ondelete="CASCADE"))
    etape_id: Mapped[int] = mapped_column(ForeignKey("etape.id", ondelete="CASCADE"), unique=True)
    type: Mapped[str] = mapped_column(String)
    contenu: Mapped[str] = mapped_column(Text, default="", server_default="")
    etat: Mapped[str] = mapped_column(String, default="brouillon", server_default="brouillon")
    dernier_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("message.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    maj_le: Mapped[datetime] = _horodatage(onupdate=func.now())

    etape: Mapped[Etape] = relationship(back_populates="document")


class Avis(Base):
    __tablename__ = "avis"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("document.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)  # version du document lue par l'agent
    agent: Mapped[str] = mapped_column(String)
    contenu: Mapped[str] = mapped_column(Text, default="", server_default="")
    # en_cours | ouvert | pris_en_compte | ecarte | abandonne
    etat: Mapped[str] = mapped_column(String, default="en_cours", server_default="en_cours")
    cree_le: Mapped[datetime] = _horodatage()


class Tache(Base):
    __tablename__ = "tache"
    __table_args__ = (Index("ix_tache_projet_colonne_rang", "projet_id", "colonne", "rang"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    projet_id: Mapped[int] = mapped_column(ForeignKey("projet.id", ondelete="CASCADE"))
    titre: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    criteres: Mapped[list] = mapped_column(JSON, default=list)
    fichiers: Mapped[list] = mapped_column(JSON, default=list)
    colonne: Mapped[str] = mapped_column(String, default="a_faire", server_default="a_faire")
    rang: Mapped[int] = mapped_column(Integer)
    origine: Mapped[str] = mapped_column(String)  # "agent" | "manuel"
    document_id: Mapped[int | None] = mapped_column(ForeignKey("document.id", ondelete="SET NULL"))
    protegee: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    doc: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    verrou: Mapped[int | None] = mapped_column(ForeignKey("pipeline.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    resume_blocage: Mapped[str | None] = mapped_column(Text)
    cree_le: Mapped[datetime] = _horodatage()
    maj_le: Mapped[datetime] = _horodatage(onupdate=func.now())


class TacheDependance(Base):
    __tablename__ = "tache_dependance"

    tache_id: Mapped[int] = mapped_column(
        ForeignKey("tache.id", ondelete="CASCADE"), primary_key=True
    )
    depend_de_id: Mapped[int] = mapped_column(
        ForeignKey("tache.id", ondelete="CASCADE"), primary_key=True
    )


class TacheEvenement(Base):
    __tablename__ = "tache_evenement"

    id: Mapped[int] = mapped_column(primary_key=True)
    projet_id: Mapped[int] = mapped_column(ForeignKey("projet.id", ondelete="CASCADE"))
    tache_id: Mapped[int] = mapped_column(Integer)  # sans clé étrangère : le journal survit
    type: Mapped[str] = mapped_column(String)  # creation | modification | deplacement | suppression
    auteur: Mapped[str] = mapped_column(String)  # "nicolas" | "agent:<nom>" | "service:<appelant>"
    donnees: Mapped[dict] = mapped_column(JSON, default=dict)
    cree_le: Mapped[datetime] = _horodatage()


class Proposition(Base):
    __tablename__ = "proposition"

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipeline.id", ondelete="CASCADE"))
    etape_id: Mapped[int] = mapped_column(ForeignKey("etape.id", ondelete="CASCADE"))
    projet_id: Mapped[int] = mapped_column(ForeignKey("projet.id", ondelete="CASCADE"))
    sorte: Mapped[str] = mapped_column(String)  # nouvelle | modification | retrait
    cle: Mapped[str | None] = mapped_column(String)
    tache_id: Mapped[int | None] = mapped_column(ForeignKey("tache.id", ondelete="SET NULL"))
    version_tache: Mapped[int | None] = mapped_column(Integer)
    donnees: Mapped[dict] = mapped_column(JSON, default=dict)
    etat: Mapped[str] = mapped_column(String, default="ouverte", server_default="ouverte")
    tache_creee_id: Mapped[int | None] = mapped_column(ForeignKey("tache.id", ondelete="SET NULL"))
    cree_le: Mapped[datetime] = _horodatage()


class ExecutionDev(Base):
    __tablename__ = "execution_dev"

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline.id", ondelete="CASCADE"), unique=True
    )
    tache_id: Mapped[int] = mapped_column(ForeignKey("tache.id", ondelete="CASCADE"))
    n: Mapped[int] = mapped_column(Integer)
    branche: Mapped[str] = mapped_column(String)
    espace: Mapped[str] = mapped_column(String)
    base: Mapped[str] = mapped_column(String)  # branche de référence résolue
    base_sha: Mapped[str] = mapped_column(String)
    # preparation | tests | rouge | code | verification | controles | pr | fini
    # (reprise : attente | preparation | tri | tests | code | verification | controles | reponses
    # | fini)
    phase: Mapped[str] = mapped_column(String)
    renvois: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    interruptions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    remarques: Mapped[list] = mapped_column(JSON, default=list)  # pour la prochaine passe
    fichiers_tests: Mapped[list] = mapped_column(JSON, default=list)
    sortie_rouge: Mapped[str | None] = mapped_column(Text)
    pr_numero: Mapped[int | None] = mapped_column(Integer)
    pr_url: Mapped[str | None] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String, default="normal", server_default="normal")
    depart_revue: Mapped[str | None] = mapped_column(String)  # HEAD après fusion de la base
    # index, dans les contrôles de `pipelines.dev`, du prochain contrôle à faire tourner
    controle_courant: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    notes: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")  # {agent, texte}
    lint_base_ok: Mapped[bool | None] = mapped_column(Boolean)
    fichiers_rouge: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    debut: Mapped[datetime] = _horodatage()


class CommentairePris(Base):
    __tablename__ = "commentaire_pris"
    __table_args__ = (
        UniqueConstraint("tache_id", "type", "github_id", name="uq_commentaire_pris"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tache_id: Mapped[int] = mapped_column(ForeignKey("tache.id", ondelete="CASCADE"))
    execution_id: Mapped[int] = mapped_column(ForeignKey("execution_dev.id", ondelete="CASCADE"))
    github_id: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String)  # revue | ligne | conversation
    auteur: Mapped[str] = mapped_column(String)
    texte: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String)
    chemin: Mapped[str | None] = mapped_column(String)
    ligne: Mapped[int | None] = mapped_column(Integer)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # date GitHub
    tri: Mapped[str | None] = mapped_column(String)  # tests | code | doc | reponse
    consigne: Mapped[str | None] = mapped_column(Text)
    repondu_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommandeLancee(Base):
    __tablename__ = "commande_lancee"

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipeline.id", ondelete="CASCADE"))
    etape_id: Mapped[int] = mapped_column(ForeignKey("etape.id", ondelete="CASCADE"))
    nom: Mapped[str] = mapped_column(String)
    code: Mapped[int | None] = mapped_column(Integer)
    delai_depasse: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    sortie: Mapped[str] = mapped_column(Text, default="", server_default="")
    debut: Mapped[datetime] = _horodatage()
    fin: Mapped[datetime] = _horodatage()


class Audit(Base):
    """Sans clé étrangère : la ligne survit à l'objet qu'elle désigne."""

    __tablename__ = "audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    quand: Mapped[datetime] = _horodatage(index=True)
    auteur: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    objet: Mapped[str] = mapped_column(String)  # pipeline | tache | proposition | …
    objet_id: Mapped[int] = mapped_column(Integer)


class AppelLLM(Base):
    """Un appel au modèle : identifiants, compteurs, durée. Jamais de contenu. Sans clé étrangère :
    la ligne survit à l'objet qu'elle désigne."""

    __tablename__ = "appel_llm"
    __table_args__ = (Index("ix_appel_llm_agent_quand", "agent", "quand"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quand: Mapped[datetime] = _horodatage()
    agent: Mapped[str] = mapped_column(String)
    modele: Mapped[str] = mapped_column(String)
    lieu: Mapped[str] = mapped_column(String, default="portail", server_default="portail")
    version_image: Mapped[str | None] = mapped_column(String)
    mission: Mapped[str | None] = mapped_column(String, index=True)
    pipeline_id: Mapped[int | None] = mapped_column(Integer)
    etape_id: Mapped[int | None] = mapped_column(Integer)
    tache_id: Mapped[int | None] = mapped_column(Integer)
    conversation_id: Mapped[int | None] = mapped_column(Integer)
    jetons_entree: Mapped[int | None] = mapped_column(Integer)
    jetons_sortie: Mapped[int | None] = mapped_column(Integer)
    duree_ms: Mapped[int] = mapped_column(Integer)
    issue: Mapped[str] = mapped_column(String)  # ok | erreur | delai


class CarteDoc(Base):
    """Une carte du kanban de documentation : rédigée par l'usine, validée par Nicolas, écrite
    dans le coffre Obsidian."""

    __tablename__ = "carte_doc"

    id: Mapped[int] = mapped_column(primary_key=True)
    projet_id: Mapped[int] = mapped_column(ForeignKey("projet.id", ondelete="CASCADE"))
    titre: Mapped[str] = mapped_column(String(200))
    genre: Mapped[str] = mapped_column(String)  # readme | architecture | runbook | adr | api | …
    consigne: Mapped[str] = mapped_column(Text, default="", server_default="")
    # a_rediger | redaction | revue | a_valider | publie
    colonne: Mapped[str] = mapped_column(String, default="a_rediger", server_default="a_rediger")
    chemin: Mapped[str] = mapped_column(String, unique=True)  # dans le coffre
    contenu: Mapped[str] = mapped_column(Text, default="", server_default="")
    remarques: Mapped[list] = mapped_column(JSON, default=list)
    renvois: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sha: Mapped[str | None] = mapped_column(String)  # SHA du dépôt lu
    pipeline_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline.id", ondelete="SET NULL"))
    erreur: Mapped[str | None] = mapped_column(Text)  # non nulle : plus tirée par l'usine
    etag: Mapped[str | None] = mapped_column(String)  # ETag S3 de la dernière écriture
    publie_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cree_le: Mapped[datetime] = _horodatage()
    maj_le: Mapped[datetime] = _horodatage(onupdate=func.now())


class Theme(Base):
    """Thème d'affichage : la table ne contient qu'une seule ligne (id = 1)."""

    __tablename__ = "theme"

    id: Mapped[int] = mapped_column(primary_key=True, unique=True)
    nom: Mapped[str] = mapped_column(String(50), default="clair", server_default="clair")
    maj_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def creer_moteur(url: str) -> AsyncEngine:
    return create_async_engine(url)


def fabrique_sessions(moteur: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(moteur, expire_on_commit=False)
