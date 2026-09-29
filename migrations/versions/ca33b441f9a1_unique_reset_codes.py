"""Require reset codes to be unique.

Revision ID: ca33b441f9a1
Revises: 7c3396c2c1ef
"""

from alembic import op

revision = "ca33b441f9a1"
down_revision = "7c3396c2c1ef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX uq_reset_code_code ON reset_code (code)")


def downgrade() -> None:
    op.execute("DROP INDEX uq_reset_code_code")
