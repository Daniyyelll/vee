"""Add guest order contact snapshots and redeemable coupons.

Revision ID: d8c6e3a41b02
Revises: c6f13a4d9e52
"""

from alembic import op

revision = "d8c6e3a41b02"
down_revision = "c6f13a4d9e52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE "order" ALTER COLUMN user_id DROP NOT NULL')
    op.execute('ALTER TABLE "order" ADD COLUMN guest_name VARCHAR(200)')
    op.execute('ALTER TABLE "order" ADD COLUMN guest_email VARCHAR(320)')
    op.execute('ALTER TABLE "order" ADD COLUMN guest_phone VARCHAR(40)')
    op.execute('ALTER TABLE "order" ADD COLUMN subtotal_price NUMERIC(10, 2)')
    op.execute(
        'ALTER TABLE "order" ADD COLUMN discount_amount '
        "NUMERIC(10, 2) NOT NULL DEFAULT 0"
    )
    op.execute(
        'ALTER TABLE "order" ADD COLUMN shipping_fee NUMERIC(10, 2) NOT NULL DEFAULT 0'
    )
    op.execute('ALTER TABLE "order" ADD COLUMN coupon_code VARCHAR(64)')
    op.execute('UPDATE "order" SET subtotal_price = total_price')
    op.execute('ALTER TABLE "order" ALTER COLUMN subtotal_price SET NOT NULL')
    op.execute("""
        ALTER TABLE "order" ADD CONSTRAINT check_order_customer CHECK (
            (user_id IS NOT NULL AND guest_name IS NULL AND guest_email IS NULL)
            OR (user_id IS NULL AND guest_name IS NOT NULL
                AND guest_email IS NOT NULL AND guest_phone IS NOT NULL)
        )
    """)
    op.execute("""
        ALTER TABLE "order" ADD CONSTRAINT check_order_discount CHECK (
            subtotal_price > 0 AND discount_amount >= 0
            AND shipping_fee >= 0
            AND total_price = subtotal_price + shipping_fee - discount_amount
            AND total_price > 0
        )
    """)
    op.execute("""
        CREATE TABLE coupon (
            id UUID PRIMARY KEY,
            code VARCHAR(64) NOT NULL UNIQUE,
            kind VARCHAR(20) NOT NULL
                CHECK (kind IN ('percent', 'free_shipping')),
            discount_percent NUMERIC(5, 2),
            starts_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            assigned_user_id UUID REFERENCES "user" (id),
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK ((kind = 'percent' AND discount_percent > 0
                    AND discount_percent < 100)
                OR (kind = 'free_shipping' AND discount_percent IS NULL)),
            CHECK (starts_at IS NULL OR expires_at IS NULL
                OR starts_at < expires_at),
            CHECK (starts_at IS NOT NULL OR expires_at IS NOT NULL
                OR assigned_user_id IS NOT NULL)
        )
    """)
    op.execute("CREATE INDEX ix_coupon_assigned_user ON coupon (assigned_user_id)")
    op.execute('ALTER TABLE "order" ADD COLUMN coupon_id UUID REFERENCES coupon (id)')
    op.execute('CREATE INDEX ix_order_coupon ON "order" (coupon_id)')


def downgrade() -> None:
    op.execute("DROP INDEX ix_order_coupon")
    op.execute('ALTER TABLE "order" DROP COLUMN coupon_id')
    op.execute("DROP TABLE coupon")
    op.execute('ALTER TABLE "order" DROP CONSTRAINT check_order_discount')
    op.execute('ALTER TABLE "order" DROP CONSTRAINT check_order_customer')
    op.execute('ALTER TABLE "order" DROP COLUMN coupon_code')
    op.execute('ALTER TABLE "order" DROP COLUMN discount_amount')
    op.execute('ALTER TABLE "order" DROP COLUMN shipping_fee')
    op.execute('ALTER TABLE "order" DROP COLUMN subtotal_price')
    op.execute('ALTER TABLE "order" DROP COLUMN guest_phone')
    op.execute('ALTER TABLE "order" DROP COLUMN guest_email')
    op.execute('ALTER TABLE "order" DROP COLUMN guest_name')
    # A downgrade requires guest orders to be removed or assigned to accounts.
    op.execute('ALTER TABLE "order" ALTER COLUMN user_id SET NOT NULL')
