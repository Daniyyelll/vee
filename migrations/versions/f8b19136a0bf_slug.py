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
    for statement in """
    ALTER TABLE product
    ADD COLUMN product_slug VARCHAR(255) UNIQUE NOT NULL;
    """.split(";"):
        statement = statement.strip()
        if statement:
            op.execute(statement)


def downgrade() -> None:
    """Downgrade schema."""
    #     ALTER TABLE category
    #     DROP COLUMN slug;
    for statement in """
    ALTER TABLE product
    DROP COLUMN slug""".split(";"):
        statement = statement.strip()
        if statement:
            op.execute(statement)
