"""Add staff MFA, refresh families, audit events, and outbox leases.

Revision ID: b7f2c6d9e310
Revises: a1d4e8c9b2f0
"""

from alembic import op

revision = "b7f2c6d9e310"
down_revision = "a1d4e8c9b2f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        'ALTER TABLE "user" ADD COLUMN staff_mfa_secret BYTEA, '
        "ADD COLUMN staff_mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE, "
        "ADD COLUMN staff_mfa_last_counter BIGINT, "
        "ADD COLUMN staff_mfa_pending_expires_at TIMESTAMPTZ"
    )

    op.execute("ALTER TABLE refresh_session ADD COLUMN family_id UUID")
    op.execute("UPDATE refresh_session SET family_id = id")
    op.execute(
        "ALTER TABLE refresh_session ALTER COLUMN family_id SET NOT NULL, "
        "ADD COLUMN replaced_by_id UUID REFERENCES refresh_session (id), "
        "ADD COLUMN revoked_at TIMESTAMPTZ"
    )
    op.execute(
        "CREATE INDEX ix_refresh_session_family "
        "ON refresh_session (family_id, revoked_at)"
    )

    op.execute(
        """
        CREATE TABLE audit_event (
            id UUID PRIMARY KEY,
            actor_user_id UUID REFERENCES "user" (id) ON DELETE SET NULL,
            action VARCHAR(120) NOT NULL,
            entity_type VARCHAR(80) NOT NULL,
            entity_id TEXT,
            request_id CHAR(32),
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX ix_audit_event_created ON audit_event (created_at DESC)")
    op.execute(
        "CREATE INDEX ix_audit_event_actor ON audit_event "
        "(actor_user_id, created_at DESC)"
    )

    op.execute(
        "ALTER TABLE email_outbox ADD COLUMN claim_token UUID, "
        "ADD COLUMN claimed_at TIMESTAMPTZ"
    )
    op.execute(
        "CREATE INDEX ix_email_outbox_claim ON email_outbox (claimed_at) "
        "WHERE sent_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_email_outbox_claim")
    op.execute(
        "ALTER TABLE email_outbox DROP COLUMN claimed_at, DROP COLUMN claim_token"
    )
    op.execute("DROP TABLE audit_event")
    op.execute("DROP INDEX ix_refresh_session_family")
    op.execute(
        "ALTER TABLE refresh_session DROP COLUMN revoked_at, "
        "DROP COLUMN replaced_by_id, DROP COLUMN family_id"
    )
    op.execute(
        'ALTER TABLE "user" DROP COLUMN staff_mfa_pending_expires_at, '
        "DROP COLUMN staff_mfa_last_counter, DROP COLUMN staff_mfa_enabled, "
        "DROP COLUMN staff_mfa_secret"
    )
