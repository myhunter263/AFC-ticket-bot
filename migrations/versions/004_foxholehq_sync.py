"""add FoxholeHQ sync metadata and normalized recipes

Revision ID: 004
Revises: 003
"""

from typing import Sequence, Union

from alembic import op


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE foxhole_items ADD COLUMN IF NOT EXISTS faction VARCHAR(50)")
    op.execute("ALTER TABLE foxhole_items ADD COLUMN IF NOT EXISTS amount_produced INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE foxhole_items ADD COLUMN IF NOT EXISTS source VARCHAR(50) NOT NULL DEFAULT 'bundled'")
    op.execute("ALTER TABLE foxhole_items ADD COLUMN IF NOT EXISTS source_version VARCHAR(100)")
    op.execute("ALTER TABLE foxhole_items ADD COLUMN IF NOT EXISTS source_updated_at TIMESTAMP")
    op.execute("ALTER TABLE foxhole_items ADD COLUMN IF NOT EXISTS dataset_hash VARCHAR(64)")
    op.execute("ALTER TABLE foxhole_items ADD COLUMN IF NOT EXISTS upstream_fingerprint VARCHAR(64)")
    op.execute("ALTER TABLE foxhole_items ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true")
    op.execute("UPDATE foxhole_items SET is_active = false WHERE source = 'bundled'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_foxhole_items_upstream_fingerprint ON foxhole_items (upstream_fingerprint)")

    op.execute("ALTER TABLE foxhole_item_localizations ALTER COLUMN ru_name DROP NOT NULL")
    op.execute("ALTER TABLE foxhole_item_localizations ADD COLUMN IF NOT EXISTS translation_status VARCHAR(20) NOT NULL DEFAULT 'translated'")
    op.execute("UPDATE foxhole_item_localizations SET translation_status = 'translated' WHERE ru_name IS NOT NULL")
    op.execute("""
        UPDATE foxhole_item_localizations AS localization
        SET ru_name = NULL, translation_status = 'missing'
        FROM foxhole_items AS item
        WHERE localization.item_id = item.id AND localization.ru_name = item.api_name
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS foxhole_production_recipes (
            id SERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES foxhole_items(id) ON DELETE CASCADE,
            production_method VARCHAR(50) NOT NULL,
            output_quantity INTEGER NOT NULL DEFAULT 1,
            output_unit VARCHAR(20) NOT NULL DEFAULT 'crate',
            materials JSONB NOT NULL DEFAULT '{}'::jsonb,
            raw_data JSONB,
            CONSTRAINT uq_foxhole_recipe_method UNIQUE (item_id, production_method)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS foxhole_sync_states (
            source VARCHAR(50) PRIMARY KEY,
            source_version VARCHAR(100),
            source_updated_at TIMESTAMP,
            dataset_hash VARCHAR(64),
            last_attempt_at TIMESTAMP,
            last_success_at TIMESTAMP,
            last_error TEXT,
            item_count INTEGER NOT NULL DEFAULT 0,
            recipe_count INTEGER NOT NULL DEFAULT 0
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS foxhole_sync_states")
    op.execute("DROP TABLE IF EXISTS foxhole_production_recipes")
    op.execute("ALTER TABLE foxhole_item_localizations DROP COLUMN IF EXISTS translation_status")
    op.execute("ALTER TABLE foxhole_item_localizations ALTER COLUMN ru_name SET NOT NULL")
    op.execute("DROP INDEX IF EXISTS ix_foxhole_items_upstream_fingerprint")
    for column in (
        "is_active", "upstream_fingerprint", "dataset_hash", "source_updated_at",
        "source_version", "source", "amount_produced", "faction",
    ):
        op.execute(f"ALTER TABLE foxhole_items DROP COLUMN IF EXISTS {column}")
