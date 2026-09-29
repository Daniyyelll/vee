"""Add the last successful login timestamp to users.

Revision ID: e1a42b7c8d90
Revises: ca33b441f9a1
"""

from alembic import op

revision = "e1a42b7c8d90"
down_revision = "ca33b441f9a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE "user" ADD COLUMN last_login TIMESTAMPTZ')


def downgrade() -> None:
    op.execute('ALTER TABLE "user" DROP COLUMN last_login')
