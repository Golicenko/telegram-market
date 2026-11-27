"""Add seller VIP plans, subscription history and durable consumable privileges."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0057_seller_vip"
down_revision = "0056_account_video_processing"
branch_labels = None
depends_on = None


def upgrade():
    plans = op.create_table(
        "seller_vip_plans",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("price_af", sa.Numeric(18, 2), nullable=False),
        sa.Column("pins_72h", sa.Integer(), nullable=False),
        sa.Column("pins_24h", sa.Integer(), nullable=False),
        sa.Column("car_limit", sa.Integer(), nullable=False),
        sa.Column("account_limit", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.CheckConstraint("duration_days > 0 AND price_af > 0 AND pins_72h >= 0 AND pins_24h >= 0 AND car_limit > 0 AND account_limit >= 0", name="ck_seller_vip_plan_values"),
    )
    op.bulk_insert(plans, [
        {"code": "month", "title": "VIP на 30 дней", "duration_days": 30, "price_af": 79,
         "pins_72h": 10, "pins_24h": 0, "car_limit": 15, "account_limit": 10, "enabled": True},
        {"code": "quarter", "title": "VIP на 3 месяца", "duration_days": 90, "price_af": 249,
         "pins_72h": 45, "pins_24h": 23, "car_limit": 68, "account_limit": 45, "enabled": True},
    ])
    op.create_table(
        "seller_vip_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", UUID(as_uuid=True), nullable=False),
        sa.Column("plan_code", sa.String(32), sa.ForeignKey("seller_vip_plans.code", ondelete="RESTRICT"), nullable=False),
        sa.Column("quote_fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("price_paid", sa.Numeric(18, 2), nullable=False),
        sa.Column("purchased_af", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("earned_af", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("bonus_af", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("transaction_id", UUID(as_uuid=True), sa.ForeignKey("wallet_transactions.id", ondelete="RESTRICT"), unique=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pins_72h_total", sa.Integer(), nullable=False),
        sa.Column("pins_72h_remaining", sa.Integer(), nullable=False),
        sa.Column("pins_24h_total", sa.Integer(), nullable=False),
        sa.Column("pins_24h_remaining", sa.Integer(), nullable=False),
        sa.Column("car_limit", sa.Integer(), nullable=False),
        sa.Column("account_limit", sa.Integer(), nullable=False),
        sa.Column("warning_notification_id", UUID(as_uuid=True), sa.ForeignKey("notifications.id", ondelete="RESTRICT")),
        sa.Column("expiry_notification_id", UUID(as_uuid=True), sa.ForeignKey("notifications.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "request_id", name="uq_seller_vip_purchase_request"),
        sa.CheckConstraint("status IN ('active','expired','disabled') AND source IN ('purchase','admin')", name="ck_seller_vip_subscription_status"),
        sa.CheckConstraint("expires_at > starts_at AND price_paid >= 0 AND purchased_af >= 0 AND earned_af >= 0 AND bonus_af >= 0 AND price_paid = purchased_af + earned_af + bonus_af", name="ck_seller_vip_subscription_funding"),
        sa.CheckConstraint("pins_72h_remaining BETWEEN 0 AND pins_72h_total AND pins_24h_remaining BETWEEN 0 AND pins_24h_total AND car_limit > 0 AND account_limit >= 0", name="ck_seller_vip_subscription_allowance"),
    )
    op.create_index("ix_seller_vip_subscriptions_user_id", "seller_vip_subscriptions", ["user_id"])
    op.create_index("ix_seller_vip_subscriptions_expires_at", "seller_vip_subscriptions", ["expires_at"])
    op.create_index("uq_seller_vip_active_user", "seller_vip_subscriptions", ["user_id"], unique=True,
                    postgresql_where=sa.text("status = 'active'"))
    op.create_table(
        "seller_vip_pin_usages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subscription_id", UUID(as_uuid=True), sa.ForeignKey("seller_vip_subscriptions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("listing_id", UUID(as_uuid=True), sa.ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", UUID(as_uuid=True), nullable=False),
        sa.Column("duration_hours", sa.Integer(), nullable=False),
        sa.Column("pinned_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "request_id", name="uq_seller_vip_pin_request"),
        sa.CheckConstraint("duration_hours IN (24,72)", name="ck_seller_vip_pin_hours"),
    )
    op.create_index("ix_seller_vip_pin_usages_subscription_id", "seller_vip_pin_usages", ["subscription_id"])
    op.create_table(
        "seller_vip_admin_commands",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("admin_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", UUID(as_uuid=True), nullable=False),
        sa.Column("parameters", JSONB(), nullable=False),
        sa.Column("subscription_id", UUID(as_uuid=True), sa.ForeignKey("seller_vip_subscriptions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("admin_id", "request_id", name="uq_seller_vip_admin_request"),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM seller_vip_subscriptions LIMIT 1")).first():
        raise RuntimeError("Keep additive VIP schema: paid subscriptions/history must not be dropped. Roll back application code only.")
    op.drop_table("seller_vip_admin_commands")
    op.drop_table("seller_vip_pin_usages")
    op.drop_table("seller_vip_subscriptions")
    op.drop_table("seller_vip_plans")
