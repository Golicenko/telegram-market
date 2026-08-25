"""Add durable recipients and observable status to administrator broadcasts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021_reliable_broadcasts"
down_revision = "0020_deal_delivery_flow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_admin_broadcast_active_admin", table_name="admin_broadcasts")
    op.drop_constraint("ck_admin_broadcast_status", "admin_broadcasts", type_="check")
    op.drop_constraint("ck_admin_broadcast_counts", "admin_broadcasts", type_="check")
    op.alter_column("admin_broadcasts", "telegram_update_id", existing_type=sa.BigInteger(), nullable=True)
    op.add_column("admin_broadcasts", sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("admin_broadcasts", sa.Column("total_recipients", sa.Integer(), nullable=False, server_default="0"))
    op.create_unique_constraint("uq_admin_broadcast_client_request", "admin_broadcasts", ["client_request_id"])
    # Jobs from the old non-durable worker are not safe to replay after deployment.
    op.execute("""
        UPDATE admin_broadcasts
        SET status = 'failed', completed_at = COALESCE(completed_at, now()),
            error = COALESCE(error, 'legacy_worker_interrupted')
        WHERE status IN ('pending', 'running')
    """)
    op.create_check_constraint(
        "ck_admin_broadcast_status", "admin_broadcasts",
        "status IN ('draft','queued','running','completed','failed')",
    )
    op.create_check_constraint(
        "ck_admin_broadcast_counts", "admin_broadcasts",
        "total_recipients >= 0 AND sent_count >= 0 AND failed_count >= 0",
    )
    op.create_index(
        "uq_admin_broadcast_active_admin", "admin_broadcasts", ["admin_telegram_id"],
        unique=True, postgresql_where=sa.text("status IN ('queued','running')"),
    )
    op.create_table(
        "admin_broadcast_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("broadcast_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_type", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending','sending','sent','failed')", name="ck_broadcast_recipient_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_broadcast_recipient_attempts"),
        sa.ForeignKeyConstraint(["broadcast_id"], ["admin_broadcasts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broadcast_id", "user_id", name="uq_broadcast_recipient_user"),
    )
    op.create_index("ix_admin_broadcast_recipients_broadcast_id", "admin_broadcast_recipients", ["broadcast_id"])
    op.create_index("ix_admin_broadcast_recipients_user_id", "admin_broadcast_recipients", ["user_id"])
    op.create_index("ix_admin_broadcast_recipients_status", "admin_broadcast_recipients", ["status"])


def downgrade() -> None:
    op.drop_index("ix_admin_broadcast_recipients_status", table_name="admin_broadcast_recipients")
    op.drop_index("ix_admin_broadcast_recipients_user_id", table_name="admin_broadcast_recipients")
    op.drop_index("ix_admin_broadcast_recipients_broadcast_id", table_name="admin_broadcast_recipients")
    op.drop_table("admin_broadcast_recipients")
    op.drop_index("uq_admin_broadcast_active_admin", table_name="admin_broadcasts")
    op.drop_constraint("ck_admin_broadcast_counts", "admin_broadcasts", type_="check")
    op.drop_constraint("ck_admin_broadcast_status", "admin_broadcasts", type_="check")
    op.drop_constraint("uq_admin_broadcast_client_request", "admin_broadcasts", type_="unique")
    op.drop_column("admin_broadcasts", "total_recipients")
    op.drop_column("admin_broadcasts", "client_request_id")
    op.execute("UPDATE admin_broadcasts SET status = 'failed' WHERE status IN ('draft','queued')")
    op.execute("""
        WITH missing AS (
            SELECT id, row_number() OVER (ORDER BY created_at, id) AS number
            FROM admin_broadcasts WHERE telegram_update_id IS NULL
        )
        UPDATE admin_broadcasts AS broadcast
        SET telegram_update_id = -1000000000000 - missing.number
        FROM missing WHERE broadcast.id = missing.id
    """)
    op.alter_column("admin_broadcasts", "telegram_update_id", existing_type=sa.BigInteger(), nullable=False)
    op.create_check_constraint("ck_admin_broadcast_status", "admin_broadcasts", "status IN ('pending','running','completed','failed')")
    op.create_check_constraint("ck_admin_broadcast_counts", "admin_broadcasts", "sent_count >= 0 AND failed_count >= 0")
    op.create_index(
        "uq_admin_broadcast_active_admin", "admin_broadcasts", ["admin_telegram_id"],
        unique=True, postgresql_where=sa.text("status IN ('pending','running')"),
    )
