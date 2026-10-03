"""Assign each deliverable order to one delivery account.

Revision ID: a1d4e8c9b2f0
Revises: 95d8e6f1a911
"""

from alembic import op

revision = "a1d4e8c9b2f0"
down_revision = "95d8e6f1a911"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        'ALTER TABLE "order" ADD COLUMN delivery_user_id UUID '
        'REFERENCES "user" (id) ON DELETE SET NULL'
    )
    op.execute(
        'CREATE INDEX ix_order_delivery_created ON "order" '
        "(delivery_user_id, created_at DESC) WHERE delivery_user_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_order_delivery_created")
    op.execute('ALTER TABLE "order" DROP COLUMN delivery_user_id')
