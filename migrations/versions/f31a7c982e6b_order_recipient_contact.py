"""Store customer phones and order recipient contact snapshots.

Revision ID: f31a7c982e6b
Revises: b16e26d74a80
"""

from alembic import op

revision = "f31a7c982e6b"
down_revision = "b16e26d74a80"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE "user" ADD COLUMN phone VARCHAR(40)')
    op.execute('ALTER TABLE "order" ADD COLUMN recipient_name TEXT')
    op.execute('ALTER TABLE "order" ADD COLUMN recipient_phone VARCHAR(40)')
    op.execute("""
        UPDATE "order" AS o
        SET recipient_name = u.name, recipient_phone = NULL
        FROM "user" AS u
        WHERE o.user_id = u.id
    """)
    op.execute("""
        UPDATE "order"
        SET recipient_name = guest_name, recipient_phone = guest_phone
        WHERE user_id IS NULL
    """)
    op.execute('ALTER TABLE "order" ALTER COLUMN recipient_name SET NOT NULL')


def downgrade() -> None:
    op.execute('ALTER TABLE "order" DROP COLUMN recipient_phone')
    op.execute('ALTER TABLE "order" DROP COLUMN recipient_name')
    op.execute('ALTER TABLE "user" DROP COLUMN phone')
