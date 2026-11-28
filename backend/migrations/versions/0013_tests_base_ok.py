"""execution_dev.tests_base_ok : la suite complète passait-elle sur la base

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.add_column("execution_dev", sa.Column("tests_base_ok", sa.Boolean))


def downgrade() -> None:
    op.drop_column("execution_dev", "tests_base_ok")
