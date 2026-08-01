"""Initial AUTOFLOW MARKET PostgreSQL schema."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    json_type = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "users",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="user"),
        sa.Column("first_name", sa.String(128), nullable=False),
        sa.Column("last_name", sa.String(128)),
        sa.Column("username", sa.String(64)),
        sa.Column("photo_url", sa.Text()),
        sa.Column("mini_app_last_active_at", sa.DateTime(timezone=True)),
        sa.Column("bot_started", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user','admin')", name="ck_users_role"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])

    op.create_table(
        "listings",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("seller_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("listing_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("brand", sa.String(96), nullable=False),
        sa.Column("model", sa.String(96), nullable=False),
        sa.Column("power_hp", sa.Integer(), nullable=False),
        sa.Column("max_speed_kph", sa.Integer(), nullable=False),
        sa.Column("price_af_coins", sa.Numeric(18, 2), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reserved_by_deal_id", uuid_type),
        sa.Column("sold_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("listing_type IN ('regular','unique')", name="ck_listings_type"),
        sa.CheckConstraint("status IN ('active','reserved','sold','deleted')", name="ck_listings_status"),
        sa.CheckConstraint("price_af_coins >= 0", name="ck_listings_min_price"),
        sa.CheckConstraint("power_hp > 0 AND max_speed_kph > 0", name="ck_listings_positive_stats"),
    )
    op.create_index("ix_listings_seller_id", "listings", ["seller_id"])
    op.create_index("ix_listings_status", "listings", ["status"])
    op.create_index("ix_listings_brand", "listings", ["brand"])
    op.create_index("ix_listings_model", "listings", ["model"])
    op.create_index("ix_listings_type_status_created", "listings", ["listing_type", "status", "created_at"])

    op.create_table(
        "listing_images",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("listing_id", uuid_type, sa.ForeignKey("listings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("listing_id", "position", name="uq_listing_image_position"),
    )
    op.create_index("ix_listing_images_listing_id", "listing_images", ["listing_id"])

    op.create_table(
        "favorites",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("listing_id", uuid_type, sa.ForeignKey("listings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "listing_id", name="uq_favorite_user_listing"),
    )

    op.create_table(
        "cart_items",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("listing_id", uuid_type, sa.ForeignKey("listings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "listing_id", name="uq_cart_user_listing"),
    )
    op.create_index("ix_cart_items_user_id", "cart_items", ["user_id"])

    op.create_table(
        "deals",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("listing_id", uuid_type, sa.ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("buyer_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("seller_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_payment"),
        sa.Column("price_af_coins", sa.Numeric(18, 2), nullable=False),
        sa.Column("frozen_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("seller_payout", sa.Numeric(18, 2), nullable=False),
        sa.Column("platform_commission", sa.Numeric(18, 2), nullable=False),
        sa.Column("transfer_started_at", sa.DateTime(timezone=True)),
        sa.Column("buyer_confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending_payment','paid','seller_contacted','transfer_in_progress','buyer_confirmed','completed','disputed','cancelled')", name="ck_deals_status"),
    )
    op.create_index("ix_deals_buyer_id", "deals", ["buyer_id"])
    op.create_index("ix_deals_seller_id", "deals", ["seller_id"])
    op.create_index("ix_deals_status", "deals", ["status"])
    op.create_index(
        "uq_deals_open_listing",
        "deals",
        ["listing_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('completed','cancelled')"),
    )

    op.create_table(
        "deal_messages",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("deal_id", uuid_type, sa.ForeignKey("deals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_deal_messages_deal_id", "deal_messages", ["deal_id"])
    op.create_index("ix_deal_messages_created_at", "deal_messages", ["created_at"])

    op.create_table(
        "wallets",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("available_balance", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("frozen_balance", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_earned", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("available_balance >= 0 AND frozen_balance >= 0 AND total_earned >= 0", name="ck_wallet_nonnegative"),
    )

    op.create_table(
        "wallet_transactions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("transaction_type", sa.String(48), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("available_before", sa.Numeric(18, 2), nullable=False),
        sa.Column("available_after", sa.Numeric(18, 2), nullable=False),
        sa.Column("frozen_before", sa.Numeric(18, 2), nullable=False),
        sa.Column("frozen_after", sa.Numeric(18, 2), nullable=False),
        sa.Column("related_deal_id", uuid_type, sa.ForeignKey("deals.id", ondelete="SET NULL")),
        sa.Column("related_withdrawal_id", uuid_type),
        sa.Column("external_reference", sa.String(255), unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_wallet_transactions_user_id", "wallet_transactions", ["user_id"])
    op.create_index("ix_wallet_transactions_type", "wallet_transactions", ["transaction_type"])
    op.create_index("ix_wallet_transactions_created_at", "wallet_transactions", ["created_at"])
    op.execute(
        """CREATE FUNCTION prevent_wallet_transaction_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'wallet_transactions is append-only';
        END;
        $$ LANGUAGE plpgsql"""
    )
    op.execute(
        """CREATE TRIGGER wallet_transactions_append_only
        BEFORE UPDATE OR DELETE ON wallet_transactions
        FOR EACH ROW EXECUTE FUNCTION prevent_wallet_transaction_mutation()
        """
    )

    op.create_table(
        "notifications",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notification_type", sa.String(48), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    op.create_table(
        "star_payments",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("telegram_payment_charge_id", sa.String(255), nullable=False, unique=True),
        sa.Column("provider_payment_charge_id", sa.String(255)),
        sa.Column("xtr_amount", sa.Integer(), nullable=False),
        sa.Column("af_coin_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("raw_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_star_payments_user_id", "star_payments", ["user_id"])

    op.create_table(
        "withdrawal_requests",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("payout_method", sa.String(64), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("reviewed_by_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending','approved','paid','rejected','cancelled')", name="ck_withdrawal_status"),
    )
    op.create_index("ix_withdrawal_requests_user_id", "withdrawal_requests", ["user_id"])
    op.create_index("ix_withdrawal_requests_status", "withdrawal_requests", ["status"])
    op.create_foreign_key(
        "fk_wallet_transactions_withdrawal",
        "wallet_transactions",
        "withdrawal_requests",
        ["related_withdrawal_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "admin_balance_adjustments",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("admin_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("wallet_transaction_id", uuid_type, sa.ForeignKey("wallet_transactions.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_admin_balance_adjustments_user_id", "admin_balance_adjustments", ["user_id"])

    op.create_table(
        "admin_actions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("admin_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(96), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", uuid_type),
        sa.Column("reason", sa.Text()),
        sa.Column("metadata", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_admin_actions_admin_id", "admin_actions", ["admin_id"])
    op.create_index("ix_admin_actions_created_at", "admin_actions", ["created_at"])


def downgrade() -> None:
    op.drop_constraint("fk_wallet_transactions_withdrawal", "wallet_transactions", type_="foreignkey")
    op.execute("DROP TRIGGER IF EXISTS wallet_transactions_append_only ON wallet_transactions")
    op.execute("DROP FUNCTION IF EXISTS prevent_wallet_transaction_mutation")
    for table in [
        "admin_actions",
        "admin_balance_adjustments",
        "star_payments",
        "notifications",
        "wallet_transactions",
        "withdrawal_requests",
        "wallets",
        "deal_messages",
        "deals",
        "cart_items",
        "favorites",
        "listing_images",
        "listings",
        "users",
    ]:
        op.drop_table(table)
