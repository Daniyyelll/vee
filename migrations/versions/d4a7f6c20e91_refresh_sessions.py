"""Store revocable, rotating refresh sessions.

Revision ID: d4a7f6c20e91
Revises: f8b19136a0bf
"""

from alembic import op

revision = "d4a7f6c20e91"
down_revision = "f8b19136a0bf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE refresh_session (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES "user" (id) ON DELETE CASCADE,
            token_hash CHAR(64) NOT NULL UNIQUE,
            token_version INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            last_used_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX ix_refresh_session_user ON refresh_session (user_id)")
    op.execute("CREATE INDEX ix_refresh_session_expiry ON refresh_session (expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE refresh_session")
