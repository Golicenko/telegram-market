"""Make administrator broadcasts idempotent by Telegram update id."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_admin_broadcasts"
down_revision = "0012_deal_chat_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_broadcasts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_update_id", sa.BigInteger(), nullable=False),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("photo_file_id", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("content_type IN ('text','photo')", name="ck_admin_broadcast_content_type"),
        sa.CheckConstraint("status IN ('pending','running','completed','failed')", name="ck_admin_broadcast_status"),
        sa.CheckConstraint("sent_count >= 0 AND failed_count >= 0", name="ck_admin_broadcast_counts"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_update_id", name="uq_admin_broadcast_telegram_update"),
    )
    op.create_index("ix_admin_broadcasts_admin_telegram_id", "admin_broadcasts", ["admin_telegram_id"])
    op.create_index("ix_admin_broadcasts_status", "admin_broadcasts", ["status"])
    op.create_index("ix_admin_broadcasts_created_at", "admin_broadcasts", ["created_at"])
    op.create_index(
        "uq_admin_broadcast_active_admin",
        "admin_broadcasts",
        ["admin_telegram_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending','running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_admin_broadcast_active_admin", table_name="admin_broadcasts")
    op.drop_index("ix_admin_broadcasts_created_at", table_name="admin_broadcasts")
    op.drop_index("ix_admin_broadcasts_status", table_name="admin_broadcasts")
    op.drop_index("ix_admin_broadcasts_admin_telegram_id", table_name="admin_broadcasts")
    op.drop_table("admin_broadcasts")
