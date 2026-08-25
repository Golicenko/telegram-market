"""Persist deal delivery details and seller notification delivery state."""

from alembic import op
import sqlalchemy as sa


revision = "0020_deal_delivery_flow"
down_revision = "0019_training_topup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("buyer_game_id", sa.String(128), nullable=True))
    op.add_column("deals", sa.Column("preferred_delivery_time", sa.String(64), nullable=True))
    # Old deals must never trigger a new seller notification during deployment.
    op.add_column(
        "deals",
        sa.Column(
            "seller_purchase_notification_status",
            sa.String(16),
            nullable=False,
            server_default="sent",
        ),
    )
    op.add_column("deals", sa.Column("seller_purchase_notification_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deals", sa.Column("seller_purchase_notification_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deals", sa.Column("seller_purchase_notification_error", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_deals_seller_purchase_notification_status",
        "deals",
        "seller_purchase_notification_status IN ('pending','sending','sent','failed')",
    )
    op.create_index(
        "ix_deals_seller_purchase_notification_status",
        "deals",
        ["seller_purchase_notification_status"],
    )
    op.alter_column("deals", "seller_purchase_notification_status", server_default="pending")


def downgrade() -> None:
    op.drop_index("ix_deals_seller_purchase_notification_status", table_name="deals")
    op.drop_constraint("ck_deals_seller_purchase_notification_status", "deals", type_="check")
    op.drop_column("deals", "seller_purchase_notification_error")
    op.drop_column("deals", "seller_purchase_notification_sent_at")
    op.drop_column("deals", "seller_purchase_notification_claimed_at")
    op.drop_column("deals", "seller_purchase_notification_status")
    op.drop_column("deals", "preferred_delivery_time")
    op.drop_column("deals", "buyer_game_id")
