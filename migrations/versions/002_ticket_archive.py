"""add ticket archive categories

Revision ID: 002
Revises: 001
"""

from typing import Sequence, Union

from alembic import op


revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE guilds ADD COLUMN IF NOT EXISTS archive_category_id BIGINT")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS original_category_id BIGINT")


def downgrade() -> None:
    op.execute("ALTER TABLE tickets DROP COLUMN IF EXISTS original_category_id")
    op.execute("ALTER TABLE guilds DROP COLUMN IF EXISTS archive_category_id")
