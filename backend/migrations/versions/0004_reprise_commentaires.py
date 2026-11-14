"""reprise sur commentaires : mode d'exécution, commentaires pris en compte

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op


def _fk(nom, cible):
    return sa.Column(
        nom, sa.Integer, sa.ForeignKey(f"{cible}.id", ondelete="CASCADE"), nullable=False
    )


revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.add_column(
        "execution_dev",
        sa.Column("mode", sa.String, nullable=False, server_default="normal"),
    )
    op.add_column("execution_dev", sa.Column("depart_revue", sa.String))
    op.create_table(
        "commentaire_pris",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("tache_id", "tache"),
        _fk("execution_id", "execution_dev"),
        sa.Column("github_id", sa.BigInteger, nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("auteur", sa.String, nullable=False),
        sa.Column("texte", sa.Text, nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("chemin", sa.String),
        sa.Column("ligne", sa.Integer),
        sa.Column("cree_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tri", sa.String),
        sa.Column("consigne", sa.Text),
        sa.Column("repondu_le", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tache_id", "type", "github_id", name="uq_commentaire_pris"),
    )


def downgrade() -> None:
    op.drop_table("commentaire_pris")
    op.drop_column("execution_dev", "depart_revue")
    op.drop_column("execution_dev", "mode")
