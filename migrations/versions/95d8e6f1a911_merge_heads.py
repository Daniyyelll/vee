"""merge heads

Revision ID: 95d8e6f1a911
Revises: 8d74c1be29f0, d4a7f6c20e91
Create Date: 2026-10-02 09:24:22.479641

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '95d8e6f1a911'
down_revision: Union[str, Sequence[str], None] = ('8d74c1be29f0', 'd4a7f6c20e91')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
