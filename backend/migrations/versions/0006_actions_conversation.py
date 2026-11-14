"""actions proposées par l'orchestrateur

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op


def _ts(nom):
    return sa.Column(nom, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.create_table(
        "action_conversation",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer,
            sa.ForeignKey("conversation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nom", sa.String, nullable=False),
        sa.Column("parametres", sa.JSON, nullable=False),
        sa.Column("etat", sa.String, nullable=False, server_default="proposee"),
        sa.Column("resultat", sa.Text),
        sa.Column("lien", sa.String),
        _ts("cree_le"),
        _ts("maj_le"),
    )
    op.create_index(
        "ix_action_conversation_conversation_id", "action_conversation", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_table("action_conversation")
