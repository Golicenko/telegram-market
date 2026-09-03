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
    op.add_column("conversation_messages", sa.Column("deal_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_conversation_messages_deal_id_deals", "conversation_messages", "deals",
        ["deal_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_conversation_messages_deal_id", "conversation_messages", ["deal_id"])

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
    op.add_column("deals", sa.Column("seller_timeout_notification_next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deals", sa.Column("seller_timeout_notification_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("deals", sa.Column("seller_timeout_notification_error", sa.Text(), nullable=True))
    op.add_column("deals", sa.Column("seller_purchase_notification_next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deals", sa.Column("seller_purchase_notification_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint(
        "ck_deals_seller_timeout_notification_status", "deals",
        "seller_timeout_notification_status IN ('not_required','pending','sending','sent','failed')",
    )
    op.create_check_constraint(
        "ck_deals_notification_attempts_nonnegative", "deals",
        "seller_timeout_notification_attempts >= 0 AND seller_purchase_notification_attempts >= 0",
    )
    op.create_index("ix_deals_seller_response_deadline", "deals", ["seller_response_deadline"])
    op.create_index("ix_deals_seller_timeout_notification_status", "deals", ["seller_timeout_notification_status"])
    op.create_index(
        "ix_deals_seller_timeout_notification_next_attempt_at", "deals",
        ["seller_timeout_notification_next_attempt_at"],
    )
    op.create_index(
        "ix_deals_seller_purchase_notification_next_attempt_at", "deals",
        ["seller_purchase_notification_next_attempt_at"],
    )
    # Existing deals deliberately keep NULL deadlines. Only a new authenticated
    # delivery-details submission starts this financial timeout.


def downgrade() -> None:
    op.drop_index("ix_deals_seller_purchase_notification_next_attempt_at", table_name="deals")
    op.drop_index("ix_deals_seller_timeout_notification_next_attempt_at", table_name="deals")
    op.drop_index("ix_deals_seller_timeout_notification_status", table_name="deals")
    op.drop_index("ix_deals_seller_response_deadline", table_name="deals")
    op.drop_constraint("ck_deals_notification_attempts_nonnegative", "deals", type_="check")
    op.drop_constraint("ck_deals_seller_timeout_notification_status", "deals", type_="check")
    op.drop_column("deals", "seller_purchase_notification_attempts")
    op.drop_column("deals", "seller_purchase_notification_next_attempt_at")
    op.drop_column("deals", "seller_timeout_notification_error")
    op.drop_column("deals", "seller_timeout_notification_attempts")
    op.drop_column("deals", "seller_timeout_notification_next_attempt_at")
    op.drop_column("deals", "seller_timeout_notification_sent_at")
    op.drop_column("deals", "seller_timeout_notification_claimed_at")
    op.drop_column("deals", "seller_timeout_notification_status")
    op.drop_column("deals", "seller_timeout_processed_at")
    op.drop_column("deals", "seller_responded_at")
    op.drop_column("deals", "seller_response_deadline")
    op.drop_column("deals", "delivery_details_submitted_at")
    op.drop_index("ix_conversation_messages_deal_id", table_name="conversation_messages")
    op.drop_constraint("fk_conversation_messages_deal_id_deals", "conversation_messages", type_="foreignkey")
    op.drop_column("conversation_messages", "deal_id")
