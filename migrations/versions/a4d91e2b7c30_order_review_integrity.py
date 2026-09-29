"""Preserve order names and enforce review integrity.

Revision ID: a4d91e2b7c30
Revises: 9af72ba65e06
"""

from alembic import op

revision = "a4d91e2b7c30"
down_revision = "9af72ba65e06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing duplicates/invalid ratings must be resolved before upgrading.
    # Do not silently delete customer feedback to satisfy these constraints.
    op.execute("ALTER TABLE order_item ADD COLUMN product_name VARCHAR")
    op.execute("""
        UPDATE order_item AS oi SET product_name = p.product_name
        FROM product AS p WHERE p.id = oi.product_id
    """)
    op.execute("ALTER TABLE order_item ALTER COLUMN product_name SET NOT NULL")
    op.execute("""
        ALTER TABLE review ADD CONSTRAINT uq_review_user_product
        UNIQUE (user_id, product_id)
    """)
    op.execute("""
        ALTER TABLE review ADD CONSTRAINT check_review_rating
        CHECK (rating BETWEEN 1 AND 5)
    """)
    op.execute("""
        UPDATE order_item AS oi SET is_reviewed = EXISTS (
            SELECT 1 FROM review r JOIN "order" o ON o.user_id = r.user_id
            WHERE o.id = oi.order_id AND r.product_id = oi.product_id
        )
    """)
    op.execute('CREATE INDEX ix_order_user_created ON "order" (user_id, created_at)')
    op.execute("CREATE INDEX ix_order_item_order ON order_item (order_id)")
    op.execute(
        "CREATE INDEX ix_review_product_created ON review (product_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_review_product_created")
    op.execute("DROP INDEX ix_order_item_order")
    op.execute("DROP INDEX ix_order_user_created")
    op.execute("ALTER TABLE review DROP CONSTRAINT check_review_rating")
    op.execute("ALTER TABLE review DROP CONSTRAINT uq_review_user_product")
    op.execute("ALTER TABLE order_item DROP COLUMN product_name")
