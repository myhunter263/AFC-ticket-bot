"""add Foxhole catalog and parsed order items

Revision ID: 003
Revises: 002
"""

from typing import Sequence, Union

from alembic import op


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # These tables were historically created by SQLAlchemy at startup but were
    # missing from migration 001. IF NOT EXISTS makes the repair production-safe.
    op.execute("""
        CREATE TABLE IF NOT EXISTS ticket_assignees (
            id SERIAL PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL, assigned_at TIMESTAMP NOT NULL DEFAULT now(), assigned_by BIGINT NOT NULL,
            CONSTRAINT uq_ticket_assignee UNIQUE (ticket_id, user_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS ticket_reports (
            id SERIAL PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            author_id BIGINT NOT NULL, content TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_points (
            id SERIAL PRIMARY KEY, guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL, points INTEGER NOT NULL DEFAULT 0, total_earned INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP NOT NULL DEFAULT now(), CONSTRAINT uq_user_points UNIQUE (guild_id, user_id)
        )
    """)
    op.execute("ALTER TABLE ticket_panels ADD COLUMN IF NOT EXISTS ping_role_ids JSONB")
    op.execute("ALTER TABLE ticket_panels ADD COLUMN IF NOT EXISTS viewer_role_ids JSONB")
    op.execute("ALTER TABLE ticket_responses ADD COLUMN IF NOT EXISTS field_type VARCHAR(50)")
    op.execute("ALTER TABLE audit_logs ALTER COLUMN target_id TYPE BIGINT")

    op.execute("""
        CREATE TABLE IF NOT EXISTS foxhole_items (
            id SERIAL PRIMARY KEY, api_id VARCHAR(200) NOT NULL UNIQUE, api_name VARCHAR(200) NOT NULL,
            category VARCHAR(100), is_vehicle BOOLEAN NOT NULL DEFAULT false, crate_size INTEGER NOT NULL DEFAULT 1,
            vehicle_crate_size INTEGER NOT NULL DEFAULT 3, factory_site VARCHAR(100), factory_cost JSONB NOT NULL DEFAULT '{}'::jsonb,
            mpf_available BOOLEAN NOT NULL DEFAULT false, mpf_max_crates INTEGER NOT NULL DEFAULT 9,
            raw_data JSONB, synced_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_foxhole_items_api_name ON foxhole_items (api_name)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS foxhole_item_localizations (
            id SERIAL PRIMARY KEY, guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
            item_id INTEGER NOT NULL REFERENCES foxhole_items(id) ON DELETE CASCADE, ru_name VARCHAR(200) NOT NULL,
            is_vehicle_override BOOLEAN, overrides JSONB, updated_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_foxhole_localization UNIQUE (guild_id, item_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS foxhole_item_aliases (
            id SERIAL PRIMARY KEY, localization_id INTEGER NOT NULL REFERENCES foxhole_item_localizations(id) ON DELETE CASCADE,
            alias VARCHAR(200) NOT NULL, normalized_alias VARCHAR(200) NOT NULL, created_by BIGINT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_foxhole_alias UNIQUE (localization_id, normalized_alias)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_foxhole_alias_normalized ON foxhole_item_aliases (normalized_alias)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS ticket_order_items (
            id SERIAL PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            item_id INTEGER REFERENCES foxhole_items(id) ON DELETE SET NULL, position INTEGER NOT NULL DEFAULT 0,
            quantity INTEGER NOT NULL, unit VARCHAR(20) NOT NULL, query VARCHAR(300) NOT NULL,
            display_name VARCHAR(200) NOT NULL, confidence INTEGER NOT NULL, matched_by VARCHAR(50) NOT NULL,
            cost_snapshot JSONB
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ticket_order_items")
    op.execute("DROP TABLE IF EXISTS foxhole_item_aliases")
    op.execute("DROP TABLE IF EXISTS foxhole_item_localizations")
    op.execute("DROP TABLE IF EXISTS foxhole_items")
