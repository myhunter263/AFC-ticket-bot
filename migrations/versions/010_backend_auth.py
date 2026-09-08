"""Backend credentials scoped to a Discord guild."""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.BigInteger, sa.ForeignKey("guilds.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('ADMIN','MANAGER','LOGISTICIAN','PRODUCTION','DELIVERY','VIEWER','BOT')", name="ck_credential_role"),
    )
    op.create_index("ix_api_credentials_guild_id", "api_credentials", ["guild_id"])


def downgrade():
    op.drop_table("api_credentials")
