"""Remove staff MFA data and enrollment support.

Revision ID: c9e4f1a2b7d6
Revises: b7f2c6d9e310
"""

from alembic import op

revision = "c9e4f1a2b7d6"
down_revision = "b7f2c6d9e310"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        'ALTER TABLE "user" DROP COLUMN IF EXISTS staff_mfa_pending_expires_at, '
        "DROP COLUMN IF EXISTS staff_mfa_last_counter, "
        "DROP COLUMN IF EXISTS staff_mfa_enabled, "
        "DROP COLUMN IF EXISTS staff_mfa_secret"
    )


def downgrade() -> None:
    op.execute(
        'ALTER TABLE "user" ADD COLUMN staff_mfa_secret BYTEA, '
        "ADD COLUMN staff_mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE, "
        "ADD COLUMN staff_mfa_last_counter BIGINT, "
        "ADD COLUMN staff_mfa_pending_expires_at TIMESTAMPTZ"
    )
