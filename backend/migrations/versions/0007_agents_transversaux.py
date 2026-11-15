"""agents transversaux : suite de contrôles du pipeline dev

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.add_column("document", sa.Column("version", sa.Integer, nullable=False, server_default="1"))
    op.create_table(
        "avis",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "document_id", sa.Integer, sa.ForeignKey("document.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("agent", sa.String, nullable=False),
        sa.Column("contenu", sa.Text, nullable=False, server_default=""),
        sa.Column("etat", sa.String, nullable=False, server_default="en_cours"),
        sa.Column(
            "cree_le", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )  # fmt: skip
    op.create_index("ix_avis_document_id", "avis", ["document_id"])
    op.add_column(
        "execution_dev",
        sa.Column("controle_courant", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column("execution_dev", sa.Column("notes", sa.JSON, nullable=False, server_default="[]"))
    op.add_column("execution_dev", sa.Column("lint_base_ok", sa.Boolean))
    op.add_column(
        "execution_dev", sa.Column("fichiers_rouge", sa.JSON, nullable=False, server_default="[]")
    )
    op.add_column(
        "conversation",
        sa.Column("agent", sa.String, nullable=False, server_default="orchestrateur"),
    )
    op.create_table(
        "resume",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("jour", sa.Date, nullable=False, unique=True),
        sa.Column(
            "conversation_id", sa.Integer, sa.ForeignKey("conversation.id", ondelete="SET NULL")
        ),
        sa.Column(
            "cree_le", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.execute("UPDATE execution_dev SET phase = 'controles' WHERE phase = 'revue'")


def downgrade() -> None:
    op.drop_table("resume")
    op.drop_column("conversation", "agent")
    op.drop_index("ix_avis_document_id", table_name="avis")
    op.drop_table("avis")
    op.drop_column("document", "version")
    op.execute("UPDATE execution_dev SET phase = 'revue' WHERE phase = 'controles'")
    op.drop_column("execution_dev", "fichiers_rouge")
    op.drop_column("execution_dev", "lint_base_ok")
    op.drop_column("execution_dev", "notes")
    op.drop_column("execution_dev", "controle_courant")
