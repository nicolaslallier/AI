"""execution_dev.tests_base_ok : la suite complète passait-elle sur la base

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    op.add_column("execution_dev", sa.Column("tests_base_ok", sa.Boolean))


def downgrade() -> None:
    op.drop_column("execution_dev", "tests_base_ok")
