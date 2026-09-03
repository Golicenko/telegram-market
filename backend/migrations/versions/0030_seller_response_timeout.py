"""Add durable seller response deadline and timeout processing state.

Revision ID: 0030_seller_response_timeout
Revises: 0029_deal_server_timezone
"""

from alembic import op
import sqlalchemy as sa


revision = "0030_seller_response_timeout"
down_revision = "0029_deal_server_timezone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("delivery_details_submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deals", sa.Column("seller_response_deadline", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deals", sa.Column("seller_responded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deals", sa.Column("seller_timeout_processed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "deals",
        sa.Column("seller_timeout_notification_status", sa.String(length=16), nullable=False, server_default="not_required"),
    )
    op.add_column("deals", sa.Column("seller_timeout_notification_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deals", sa.Column("seller_timeout_notification_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deals", sa.Column("seller_timeout_notification_error", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_deals_seller_timeout_notification_status",
        "deals",
        "seller_timeout_notification_status IN ('not_required','pending','sending','sent','failed')",
    )
    op.create_index("ix_deals_seller_response_deadline", "deals", ["seller_response_deadline"])
    op.create_index("ix_deals_seller_timeout_notification_status", "deals", ["seller_timeout_notification_status"])
    # Preserve open deals created before this migration. The notification timestamp
    # is the closest durable equivalent of the original details submission time.
    op.execute(
        """
        UPDATE deals
        SET delivery_details_submitted_at = COALESCE(seller_purchase_notification_sent_at, updated_at, created_at)
        WHERE seller_purchase_notification_status = 'sent'
          AND buyer_game_id IS NOT NULL
          AND buyer_server IS NOT NULL
          AND preferred_delivery_time IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE deals AS deal
        SET seller_responded_at = (
            SELECT MIN(message.created_at)
            FROM conversation_messages AS message
            WHERE message.conversation_id = deal.conversation_id
              AND message.sender_id = deal.seller_id
              AND message.message_type = 'text'
              AND message.created_at >= deal.delivery_details_submitted_at
        )
        WHERE deal.delivery_details_submitted_at IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM conversation_messages AS message
              WHERE message.conversation_id = deal.conversation_id
                AND message.sender_id = deal.seller_id
                AND message.message_type = 'text'
                AND message.created_at >= deal.delivery_details_submitted_at
          )
        """
    )
    op.execute(
        """
        UPDATE deals
        SET seller_responded_at = COALESCE(seller_responded_at, transfer_started_at, updated_at)
        WHERE delivery_details_submitted_at IS NOT NULL
          AND status IN ('seller_contacted','transfer_in_progress','buyer_confirmed','completed')
        """
    )
    op.execute(
        """
        UPDATE deals AS deal
        SET seller_responded_at = COALESCE(
            deal.seller_responded_at,
            (
                SELECT MIN(message.created_at)
                FROM deal_messages AS message
                WHERE message.deal_id = deal.id
                  AND message.sender_id = deal.seller_id
                  AND message.created_at >= deal.delivery_details_submitted_at
            )
        )
        WHERE deal.delivery_details_submitted_at IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM deal_messages AS message
              WHERE message.deal_id = deal.id
                AND message.sender_id = deal.seller_id
                AND message.created_at >= deal.delivery_details_submitted_at
          )
        """
    )
    op.execute(
        """
        UPDATE deals
        SET seller_response_deadline = delivery_details_submitted_at + INTERVAL '24 hours'
        WHERE delivery_details_submitted_at IS NOT NULL
          AND seller_purchase_notification_status = 'sent'
          AND status IN ('paid','seller_contacted')
        """
    )


def downgrade() -> None:
    op.drop_index("ix_deals_seller_timeout_notification_status", table_name="deals")
    op.drop_index("ix_deals_seller_response_deadline", table_name="deals")
    op.drop_constraint("ck_deals_seller_timeout_notification_status", "deals", type_="check")
    op.drop_column("deals", "seller_timeout_notification_error")
    op.drop_column("deals", "seller_timeout_notification_sent_at")
    op.drop_column("deals", "seller_timeout_notification_claimed_at")
    op.drop_column("deals", "seller_timeout_notification_status")
    op.drop_column("deals", "seller_timeout_processed_at")
    op.drop_column("deals", "seller_responded_at")
    op.drop_column("deals", "seller_response_deadline")
    op.drop_column("deals", "delivery_details_submitted_at")
