"""Harden identities, checkout, catalog, and audit delivery.

Revision ID: e4c82d7a61f0
Revises: d8c6e3a41b02
"""

from alembic import op

revision = "e4c82d7a61f0"
down_revision = "d8c6e3a41b02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE reset_code ALTER COLUMN expires_at "
        "SET DEFAULT NOW() + INTERVAL '30 minutes'"
    )
    op.execute('ALTER TABLE "user" ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0')
    op.execute('ALTER TABLE "user" DROP CONSTRAINT uq_user_name')
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM "user" GROUP BY lower(email) HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'Resolve case-insensitive duplicate emails first';
            END IF;
        END $$
    """)
    op.execute('CREATE UNIQUE INDEX uq_user_email_lower ON "user" (lower(email))')
    op.execute("""
        CREATE TABLE rate_limit (
            key CHAR(64) PRIMARY KEY,
            hits INTEGER NOT NULL CHECK (hits > 0),
            reset_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_rate_limit_reset ON rate_limit (reset_at)")
    op.execute("""
        CREATE TABLE guest_checkout_request (
            key CHAR(64) PRIMARY KEY,
            request_hash CHAR(64) NOT NULL,
            order_id UUID REFERENCES "order" (id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute('ALTER TABLE "order" ADD COLUMN expires_at TIMESTAMPTZ')
    op.execute(
        'CREATE INDEX ix_order_pending_expiry ON "order" (expires_at) '
        "WHERE status = 'PENDING'"
    )
    op.execute("ALTER TABLE product ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("ALTER TABLE category ADD COLUMN slug VARCHAR(255)")
    op.execute("""
        WITH names AS (
            SELECT id, lower(replace(btrim(category_name), ' ', '-')) AS base,
                   row_number() OVER (
                       PARTITION BY lower(replace(btrim(category_name), ' ', '-'))
                       ORDER BY id
                   ) AS position
            FROM category
        )
        UPDATE category c SET slug = CASE
            WHEN names.position = 1 THEN names.base
            ELSE left(names.base, 218) || '-' || c.id::text
        END
        FROM names WHERE c.id = names.id
    """)
    op.execute("ALTER TABLE category ALTER COLUMN slug SET NOT NULL")
    op.execute("CREATE UNIQUE INDEX uq_category_slug ON category (slug)")
    op.execute(
        "ALTER TABLE product ADD COLUMN currency currency NOT NULL DEFAULT 'EGP'"
    )
    op.execute('ALTER TABLE "order" ADD COLUMN currency currency')
    op.execute("""
        UPDATE "order" o SET currency = COALESCE(
            (SELECT p.currency FROM payment p WHERE p.order_id = o.id), 'EGP'
        )
    """)
    op.execute('ALTER TABLE "order" ALTER COLUMN currency SET NOT NULL')
    op.execute("""
        CREATE TABLE email_outbox (
            id UUID PRIMARY KEY,
            kind VARCHAR(32) NOT NULL,
            payload JSONB NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sent_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX ix_email_outbox_due ON email_outbox (next_attempt_at) "
        "WHERE sent_at IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE reset_code ALTER COLUMN expires_at "
        "SET DEFAULT NOW() + INTERVAL '5 minutes'"
    )
    op.execute("DROP TABLE email_outbox")
    op.execute('ALTER TABLE "order" DROP COLUMN currency')
    op.execute("ALTER TABLE product DROP COLUMN currency")
    op.execute("ALTER TABLE product DROP COLUMN active")
    op.execute("ALTER TABLE category DROP COLUMN slug")
    op.execute("DROP INDEX ix_order_pending_expiry")
    op.execute('ALTER TABLE "order" DROP COLUMN expires_at')
    op.execute("DROP TABLE guest_checkout_request")
    op.execute("DROP TABLE rate_limit")
    op.execute("DROP INDEX uq_user_email_lower")
    # Existing duplicate names may prevent this constraint from being restored.
    op.execute('ALTER TABLE "user" ADD CONSTRAINT uq_user_name UNIQUE (name)')
    op.execute('ALTER TABLE "user" DROP COLUMN token_version')
