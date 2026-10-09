"""Store the two editable landing image slots.

Revision ID: ca4e9d7b21f0
Revises: c9e4f1a2b7d6
"""

from alembic import op

revision = "ca4e9d7b21f0"
down_revision = "c9e4f1a2b7d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE landing_image (
            slot VARCHAR(16) PRIMARY KEY CHECK (slot IN ('hero', 'ritual')),
            image_url TEXT NOT NULL,
            small_image_url TEXT NOT NULL,
            alt_text VARCHAR(240) NOT NULL CHECK (length(trim(alt_text)) > 0),
            caption VARCHAR(300) NOT NULL DEFAULT '',
            focal_x SMALLINT NOT NULL DEFAULT 50 CHECK (focal_x BETWEEN 0 AND 100),
            focal_y SMALLINT NOT NULL DEFAULT 50 CHECK (focal_y BETWEEN 0 AND 100),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        INSERT INTO landing_image
            (slot, image_url, small_image_url, alt_text, caption, focal_y)
        VALUES
            ('hero', '/images/vee-atelier.webp',
             '/images/vee-atelier-640.webp',
             'Vee concept cosmetics in soft peach-blush and rose gold, ' ||
             'arranged on sunlit natural stone',
             'Visual concept. Products shown are illustrative.', 54),
            ('ritual', '/images/stone-ritual.webp',
             '/images/stone-ritual-640.webp',
             'Ivory and amber concept cosmetics on natural limestone, ' ||
             'surrounded by dried botanicals',
             'Visual concept. Products shown are illustrative.', 58)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE landing_image")
