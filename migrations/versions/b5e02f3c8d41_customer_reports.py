"""Add customer product and review reports.

Revision ID: b5e02f3c8d41
Revises: a4d91e2b7c30
"""

from alembic import op

revision = "b5e02f3c8d41"
down_revision = "a4d91e2b7c30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE report (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES "user" (id),
            product_id UUID REFERENCES product (id),
            review_id UUID REFERENCES review (id) ON DELETE SET NULL,
            target_type VARCHAR NOT NULL CHECK (target_type IN ('product', 'review')),
            reason VARCHAR NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'resolved', 'dismissed')),
            resolution VARCHAR,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT check_report_target CHECK (
                (target_type = 'product' AND product_id IS NOT NULL
                    AND review_id IS NULL)
                OR (target_type = 'review' AND product_id IS NULL)
            )
        )
    """)
    # Keep moderation history even if an admin removes the reported review.
    op.execute("""
        CREATE UNIQUE INDEX uq_report_open_product ON report (user_id, product_id)
        WHERE status = 'open' AND product_id IS NOT NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_report_open_review ON report (user_id, review_id)
        WHERE status = 'open' AND review_id IS NOT NULL
    """)
    op.execute("CREATE INDEX ix_report_user_created ON report (user_id, created_at)")
    op.execute("CREATE INDEX ix_report_status_created ON report (status, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE report")
