"""add Foxhole dictionary metadata and resource definitions

Revision ID: 005
Revises: 004
"""

from typing import Sequence, Union

from alembic import op


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE foxhole_item_aliases ADD COLUMN IF NOT EXISTS "
        "alias_type VARCHAR(30) NOT NULL DEFAULT 'custom'"
    )
    op.execute(
        "ALTER TABLE foxhole_item_aliases ADD COLUMN IF NOT EXISTS "
        "priority INTEGER NOT NULL DEFAULT 100"
    )
    op.execute("""
        CREATE TABLE IF NOT EXISTS foxhole_resources (
            resource_key VARCHAR(30) PRIMARY KEY,
            api_name VARCHAR(100) NOT NULL,
            crate_size INTEGER NOT NULL,
            source VARCHAR(50) NOT NULL DEFAULT 'foxholehq',
            source_version VARCHAR(100),
            raw_data JSONB,
            synced_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS unknown_item_queries (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
            raw_query VARCHAR(300) NOT NULL,
            normalized_query VARCHAR(300) NOT NULL,
            count INTEGER NOT NULL DEFAULT 1,
            last_seen_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_unknown_item_query UNIQUE (guild_id, normalized_query)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS foxhole_seed_states (
            guild_id BIGINT PRIMARY KEY REFERENCES guilds(id) ON DELETE CASCADE,
            seed_version INTEGER NOT NULL DEFAULT 0,
            applied_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_unknown_item_query_normalized "
        "ON unknown_item_queries (normalized_query)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS foxhole_seed_states")
    op.execute("DROP TABLE IF EXISTS unknown_item_queries")
    op.execute("DROP TABLE IF EXISTS foxhole_resources")
    op.execute("ALTER TABLE foxhole_item_aliases DROP COLUMN IF EXISTS priority")
    op.execute("ALTER TABLE foxhole_item_aliases DROP COLUMN IF EXISTS alias_type")
