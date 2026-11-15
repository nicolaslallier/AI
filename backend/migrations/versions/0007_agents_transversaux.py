"""agents transversaux : suite de contrôles du pipeline dev

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.add_column(
        "execution_dev",
        sa.Column("controle_courant", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column("execution_dev", sa.Column("notes", sa.JSON, nullable=False, server_default="[]"))
    op.add_column("execution_dev", sa.Column("lint_base_ok", sa.Boolean))
    op.add_column(
        "execution_dev", sa.Column("fichiers_rouge", sa.JSON, nullable=False, server_default="[]")
    )
    op.execute("UPDATE execution_dev SET phase = 'controles' WHERE phase = 'revue'")


def downgrade() -> None:
    op.execute("UPDATE execution_dev SET phase = 'revue' WHERE phase = 'controles'")
    op.drop_column("execution_dev", "fichiers_rouge")
    op.drop_column("execution_dev", "lint_base_ok")
    op.drop_column("execution_dev", "notes")
    op.drop_column("execution_dev", "controle_courant")
