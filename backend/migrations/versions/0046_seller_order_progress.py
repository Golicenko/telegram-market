"""Explicit seller acceptance and durable bounded reminders; no timer/money rewrite."""
from alembic import op
import sqlalchemy as sa

revision = "0046_seller_order_progress"
down_revision = "0045_withdrawal_public_numbers"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deals", sa.Column("seller_accepted_at", sa.DateTime(timezone=True)))
    op.add_column("deals", sa.Column("seller_reminder_stage", sa.Integer(), nullable=False, server_default="0"))
    op.drop_constraint("ck_deals_seller_purchase_notification_status", "deals", type_="check")
    op.create_check_constraint("ck_deals_seller_purchase_notification_status", "deals",
        "seller_purchase_notification_status IN ('pending','sending','sent','failed','outbox')")


def downgrade():
    raise RuntimeError("Keep durable notification ownership on code rollback; use a reviewed forward migration")
