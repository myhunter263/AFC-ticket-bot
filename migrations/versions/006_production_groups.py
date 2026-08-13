"""add normalized Foxhole production groups

Revision ID: 006
Revises: 005
"""

from typing import Sequence, Union

from alembic import op


revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE foxhole_items ADD COLUMN IF NOT EXISTS "
        "production_group VARCHAR(20) NOT NULL DEFAULT 'item'"
    )
    op.execute(
        "ALTER TABLE foxhole_item_localizations ADD COLUMN IF NOT EXISTS "
        "production_group_override VARCHAR(20)"
    )
    op.execute("""
        UPDATE foxhole_items
        SET production_group = CASE
            WHEN category IN ('vehicles', 'structures') THEN 'equipment'
            ELSE 'item'
        END,
        mpf_max_crates = CASE
            WHEN category IN ('vehicles', 'structures') THEN 5
            ELSE 9
        END
        WHERE source = 'foxholehq'
    """)
    op.execute("""
        UPDATE foxhole_production_recipes AS recipe
        SET output_unit = CASE
            WHEN recipe.production_method = 'mpf' THEN 'equipment_crate'
            ELSE 'equipment'
        END,
        output_quantity = 1
        FROM foxhole_items AS item
        WHERE recipe.item_id = item.id
          AND item.source = 'foxholehq'
          AND item.category = 'structures'
    """)
    op.execute("""
        UPDATE foxhole_items
        SET production_group = 'item'
        WHERE source = 'foxholehq-resource'
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE foxhole_item_localizations "
        "DROP COLUMN IF EXISTS production_group_override"
    )
    op.execute(
        "ALTER TABLE foxhole_items DROP COLUMN IF EXISTS production_group"
    )
