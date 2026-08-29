"""Schedule one durable buyer reminder after a seller transfers a car."""

from alembic import op
import sqlalchemy as sa


revision = "0024_deal_transfer_reminder"
down_revision = "0023_listing_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deals",
        sa.Column(
            "buyer_transfer_reminder_status",
            sa.String(length=16),
            nullable=False,
            server_default="not_scheduled",
        ),
    )
    op.add_column("deals", sa.Column("buyer_transfer_reminder_scheduled_at", sa.DateTime(timezone=True)))
    op.add_column("deals", sa.Column("buyer_transfer_reminder_claimed_at", sa.DateTime(timezone=True)))
    op.add_column("deals", sa.Column("buyer_transfer_reminder_sent_at", sa.DateTime(timezone=True)))
    op.add_column(
        "deals",
        sa.Column("buyer_transfer_reminder_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("deals", sa.Column("buyer_transfer_reminder_error", sa.Text()))
    op.create_check_constraint(
        "ck_deals_buyer_transfer_reminder_status",
        "deals",
        "buyer_transfer_reminder_status IN ('not_scheduled','pending','sending','sent','skipped','failed')",
    )
    op.create_check_constraint(
        "ck_deals_buyer_transfer_reminder_attempts",
        "deals",
        "buyer_transfer_reminder_attempts >= 0",
    )
    op.create_index(
        "ix_deals_buyer_transfer_reminder_status",
        "deals",
        ["buyer_transfer_reminder_status"],
    )
    op.create_index(
        "ix_deals_buyer_transfer_reminder_scheduled_at",
        "deals",
        ["buyer_transfer_reminder_scheduled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_deals_buyer_transfer_reminder_scheduled_at", table_name="deals")
    op.drop_index("ix_deals_buyer_transfer_reminder_status", table_name="deals")
    op.drop_constraint("ck_deals_buyer_transfer_reminder_attempts", "deals", type_="check")
    op.drop_constraint("ck_deals_buyer_transfer_reminder_status", "deals", type_="check")
    op.drop_column("deals", "buyer_transfer_reminder_error")
    op.drop_column("deals", "buyer_transfer_reminder_attempts")
    op.drop_column("deals", "buyer_transfer_reminder_sent_at")
    op.drop_column("deals", "buyer_transfer_reminder_claimed_at")
    op.drop_column("deals", "buyer_transfer_reminder_scheduled_at")
    op.drop_column("deals", "buyer_transfer_reminder_status")
