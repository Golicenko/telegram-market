"""Durable message delivery and expiring chat presence; do not replay old notices."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0035_message_delivery"
down_revision = "0034_chat_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("viewing_conversation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("users", sa.Column("chat_presence_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notifications", sa.Column("delivery_status", sa.String(24), nullable=False, server_default="not_required"))
    op.add_column("notifications", sa.Column("delivery_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notifications", sa.Column("delivery_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notifications", sa.Column("delivery_error", sa.String(128), nullable=True))
    op.add_column("notifications", sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("notifications", sa.Column("delivery_next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_notifications_delivery_status", "notifications", ["delivery_status"])


def downgrade():
    op.drop_index("ix_notifications_delivery_status", table_name="notifications")
    for field in ("delivery_next_attempt_at", "delivery_attempts", "delivery_error", "delivery_sent_at", "delivery_claimed_at", "delivery_status"):
        op.drop_column("notifications", field)
    op.drop_column("users", "chat_presence_at")
    op.drop_column("users", "viewing_conversation_id")
