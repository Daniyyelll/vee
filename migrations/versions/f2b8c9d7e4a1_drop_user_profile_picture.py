"""Remove the unused user profile-picture column.

Revision ID: f2b8c9d7e4a1
Revises: e1a42b7c8d90
"""

from alembic import op

revision = "f2b8c9d7e4a1"
down_revision = "e1a42b7c8d90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS profile_picture')


def downgrade() -> None:
    op.execute('ALTER TABLE "user" ADD COLUMN profile_picture VARCHAR')
