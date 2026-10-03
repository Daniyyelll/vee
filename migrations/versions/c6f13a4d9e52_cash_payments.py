"""Make payment records usable for cash collection without a provider.

Revision ID: c6f13a4d9e52
Revises: b5e02f3c8d41
"""

from alembic import op

revision = "c6f13a4d9e52"
down_revision = "b5e02f3c8d41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Do not invent provider IDs or silently rewrite historical transactions.
    # Existing duplicates, non-cash payments or missing amounts require review.
    op.execute("ALTER TABLE payment ALTER COLUMN provider_transaction_id DROP NOT NULL")
    op.execute("ALTER TABLE payment ALTER COLUMN amount SET NOT NULL")
    op.execute(
        "ALTER TABLE payment ADD CONSTRAINT check_payment_amount CHECK (amount > 0)"
    )
    op.execute("ALTER TABLE payment ADD CONSTRAINT uq_payment_order UNIQUE (order_id)")
    op.execute("""
        ALTER TABLE payment ADD CONSTRAINT check_payment_cash_only
        CHECK (payment_method = 'CASH')
    """)
    op.execute("""
        ALTER TABLE payment
        ADD COLUMN collected_at TIMESTAMPTZ,
        ADD COLUMN collected_by UUID REFERENCES "user" (id),
        ADD COLUMN refunded_at TIMESTAMPTZ,
        ADD COLUMN refunded_by UUID REFERENCES "user" (id),
        ADD COLUMN refund_reason VARCHAR
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE payment DROP COLUMN refund_reason,
        DROP COLUMN refunded_by, DROP COLUMN refunded_at,
        DROP COLUMN collected_by, DROP COLUMN collected_at
    """)
    op.execute("ALTER TABLE payment DROP CONSTRAINT check_payment_cash_only")
    op.execute("ALTER TABLE payment DROP CONSTRAINT uq_payment_order")
    op.execute("ALTER TABLE payment DROP CONSTRAINT check_payment_amount")
    op.execute("ALTER TABLE payment ALTER COLUMN amount DROP NOT NULL")
    # Cash has no provider transaction ID. Retain nullability on downgrade
    # rather than deleting cash records or manufacturing external references.
