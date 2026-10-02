"""Limit coupon uses across all customers.

Revision ID: b16e26d74a80
Revises: e4c82d7a61f0
"""

from alembic import op

revision = "b16e26d74a80"
down_revision = "e4c82d7a61f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE coupon ADD COLUMN max_uses INTEGER")
    op.execute(
        "ALTER TABLE coupon ADD CONSTRAINT check_coupon_max_uses "
        "CHECK (max_uses IS NULL OR max_uses > 0)"
    )
    # The original scope check was unnamed. Find it by its distinctive
    # assigned_user_id clause so this works on existing databases too.
    op.execute("""
        DO $$
        DECLARE old_check TEXT;
        BEGIN
            SELECT conname INTO old_check
            FROM pg_constraint
            WHERE conrelid = 'coupon'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%assigned_user_id IS NOT NULL%'
            LIMIT 1;
            IF old_check IS NULL THEN
                RAISE EXCEPTION 'Existing coupon scope constraint not found';
            END IF;
            EXECUTE format('ALTER TABLE coupon DROP CONSTRAINT %I', old_check);
        END $$;
    """)
    op.execute("""
        ALTER TABLE coupon ADD CONSTRAINT check_coupon_scope CHECK (
            starts_at IS NOT NULL OR expires_at IS NOT NULL
            OR assigned_user_id IS NOT NULL OR max_uses IS NOT NULL
        )
    """)


def downgrade() -> None:
    # Usage-only coupons have no equivalent in the old schema. Reject a
    # downgrade that would silently change their validity.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM coupon WHERE starts_at IS NULL
                    AND expires_at IS NULL AND assigned_user_id IS NULL
            ) THEN
                RAISE EXCEPTION 'Usage-only coupons prevent this downgrade';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE coupon DROP CONSTRAINT check_coupon_scope")
    op.execute("""
        ALTER TABLE coupon ADD CONSTRAINT check_coupon_scope_legacy CHECK (
            starts_at IS NOT NULL OR expires_at IS NOT NULL
            OR assigned_user_id IS NOT NULL
        )
    """)
    op.execute("ALTER TABLE coupon DROP CONSTRAINT check_coupon_max_uses")
    op.execute("ALTER TABLE coupon DROP COLUMN max_uses")
