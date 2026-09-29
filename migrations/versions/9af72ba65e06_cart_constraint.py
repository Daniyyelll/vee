"""cart constraint

Revision ID: 9af72ba65e06
Revises: f8b19136a0bf
Create Date: 2026-09-29 03:31:17.106823

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9af72ba65e06'
down_revision: Union[str, Sequence[str], None] = 'f8b19136a0bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for statement in """
    ALTER TABLE cart_item
    ADD CONSTRAINT uq_cart_item_cart_product
    UNIQUE (cart_id, product_id);
    
    ALTER TABLE cart_item
    ADD CONSTRAINT check_cart_item_positive_quantity
    CHECK (quantity > 0);    
    """.split(";"):
        statement = statement.strip()
        op.execute(statement)


def downgrade() -> None:
    """Downgrade schema."""
    pass
