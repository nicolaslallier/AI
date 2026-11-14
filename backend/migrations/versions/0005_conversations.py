"""conversations libres avec l'orchestrateur

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
        "conversation",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("titre", sa.String(200), nullable=False, server_default=""),
        sa.Column("etat", sa.String, nullable=False, server_default="pret"),
        sa.Column("erreur", sa.Text),
        _ts("cree_le"),
        _ts("maj_le"),
    )
    op.create_table(
        "message_conversation",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer,
            sa.ForeignKey("conversation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("contenu", sa.Text, nullable=False),
        sa.Column("outil", sa.String),
        _ts("cree_le"),
    )
    op.create_index(
        "ix_message_conversation_conversation_id", "message_conversation", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_table("message_conversation")
    op.drop_table("conversation")
