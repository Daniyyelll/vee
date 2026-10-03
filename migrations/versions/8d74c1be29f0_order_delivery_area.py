"""Record a validated delivery area separately from the street address.

Revision ID: 8d74c1be29f0
Revises: f31a7c982e6b
"""

from alembic import op

revision = "8d74c1be29f0"
down_revision = "f31a7c982e6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing orders have no reliable area value to backfill.
    op.execute('ALTER TABLE "order" ADD COLUMN delivery_area VARCHAR(20)')
    op.execute(
        'ALTER TABLE "order" ADD CONSTRAINT check_order_delivery_area '
        "CHECK (delivery_area IS NULL OR delivery_area IN "
        "('Cairo', 'New Cairo', 'Giza'))"
    )


def downgrade() -> None:
    op.execute('ALTER TABLE "order" DROP CONSTRAINT check_order_delivery_area')
    op.execute('ALTER TABLE "order" DROP COLUMN delivery_area')
