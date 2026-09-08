"""CRM role mapping and credential expiration."""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = depends_on = None


def upgrade():
    op.add_column("api_credentials", sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.create_table("permission_bindings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("guild_id", sa.BigInteger, sa.ForeignKey("guilds.id"), nullable=False),
        sa.Column("discord_role_id", sa.BigInteger, nullable=False),
        sa.Column("app_role", sa.String(20), nullable=False),
        sa.UniqueConstraint("guild_id", "discord_role_id", name="uq_crm_role_binding"),
        sa.CheckConstraint("app_role IN ('ADMIN','MANAGER','LOGISTICIAN','PRODUCTION','DELIVERY','VIEWER')", name="ck_binding_role"),
    )
    op.create_index("ix_permission_bindings_guild_id", "permission_bindings", ["guild_id"])


def downgrade():
    op.drop_table("permission_bindings")
    op.drop_column("api_credentials", "expires_at")
