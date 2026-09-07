"""Persist response cases without deleting listings, chats or financial history."""
from alembic import op
import sqlalchemy as sa

revision = "0036_inactivity_state"
down_revision = "0035_message_delivery"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deals", sa.Column("cancellation_reason", sa.String(48), nullable=True))
    for name in ("response_required_at", "inactivity_deadline", "inactivity_processed_at"):
        op.add_column("conversations", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.add_column("conversations", sa.Column("inactivity_status", sa.String(24), nullable=False, server_default="not_required"))
    op.create_index("ix_conversations_inactivity_deadline", "conversations", ["inactivity_deadline"])
    # Group retries could have delivered to some recipients already. Never replay them.
    op.execute("UPDATE deals SET seller_timeout_notification_status='not_required' WHERE seller_timeout_notification_status IN ('pending','sending','failed')")
    # Preserve already scheduled paid-deal deadlines. Do not punish old ordinary chats retroactively.
    op.execute("""UPDATE conversations c SET inactivity_status='waiting',
        response_required_at=d.delivery_details_submitted_at, inactivity_deadline=d.seller_response_deadline
        FROM deals d WHERE d.conversation_id=c.id AND d.status IN ('paid','seller_contacted')
        AND d.seller_response_deadline IS NOT NULL AND d.seller_responded_at IS NULL
        AND d.seller_timeout_processed_at IS NULL""")


def downgrade():
    op.drop_index("ix_conversations_inactivity_deadline", table_name="conversations")
    for name in ("inactivity_status", "inactivity_processed_at", "inactivity_deadline", "response_required_at"):
        op.drop_column("conversations", name)
    op.drop_column("deals", "cancellation_reason")
