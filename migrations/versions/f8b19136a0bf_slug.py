"""slug

Revision ID: f8b19136a0bf
Revises: f2b8c9d7e4a1
Create Date: 2026-09-28 04:00:42.793119

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f8b19136a0bf"
down_revision: Union[str, Sequence[str], None] = "f2b8c9d7e4a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ALTER TABLE category
    # ADD COLUMN slug VARCHAR(255) UNIQUE NOT NULL;
    op.execute("ALTER TABLE product ADD COLUMN product_slug VARCHAR(255)")
    # Existing rows predate slugs. Include the UUID so backfills cannot collide.
    op.execute("""
        UPDATE product SET product_slug =
            left(lower(regexp_replace(
                trim(product_name), '[^a-zA-Z0-9]+', '-', 'g'
            )), 200)
            || '-' || id::text
    """)
    op.execute("ALTER TABLE product ALTER COLUMN product_slug SET NOT NULL")
    op.execute(
        "ALTER TABLE product ADD CONSTRAINT uq_product_slug UNIQUE (product_slug)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    #     ALTER TABLE category
    #     DROP COLUMN slug;
    op.execute("ALTER TABLE product DROP COLUMN product_slug")
