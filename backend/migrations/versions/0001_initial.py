"""schema initial

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def _ts(nom):
    return sa.Column(nom, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "projet",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nom", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        _ts("cree_le"),
    )
    op.create_table(
        "pipeline",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "projet_id", sa.Integer, sa.ForeignKey("projet.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("etat", sa.String, nullable=False, server_default="en_cours"),
        _ts("cree_le"),
        _ts("maj_le"),
    )
    op.create_table(
        "etape",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "pipeline_id",
            sa.Integer,
            sa.ForeignKey("pipeline.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordre", sa.Integer, nullable=False),
        sa.Column("agent", sa.String, nullable=False),
        sa.Column("etat", sa.String, nullable=False, server_default="a_faire"),
        sa.Column("erreur", sa.Text),
        sa.Column("action", sa.String),
    )
    op.create_table(
        "message",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "etape_id", sa.Integer, sa.ForeignKey("etape.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("contenu", sa.Text, nullable=False),
        _ts("cree_le"),
    )
    op.create_table(
        "document",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "projet_id", sa.Integer, sa.ForeignKey("projet.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "pipeline_id",
            sa.Integer,
            sa.ForeignKey("pipeline.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "etape_id",
            sa.Integer,
            sa.ForeignKey("etape.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("contenu", sa.Text, nullable=False, server_default=""),
        sa.Column("etat", sa.String, nullable=False, server_default="brouillon"),
        sa.Column(
            "dernier_message_id", sa.Integer, sa.ForeignKey("message.id", ondelete="SET NULL")
        ),
        _ts("maj_le"),
    )


def downgrade() -> None:
    for t in ("document", "message", "etape", "pipeline", "projet"):
        op.drop_table(t)
