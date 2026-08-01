"""Permanent conversations, account listings and timed promotion."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_market_features"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.add_column("listings", sa.Column("pinned_until", sa.DateTime(timezone=True)))
    op.create_index("ix_listings_pinned_until", "listings", ["pinned_until"])
    op.drop_constraint("ck_listings_status", "listings", type_="check")
    op.create_check_constraint("ck_listings_status", "listings", "status IN ('active','paused','reserved','sold','deleted')")

    op.create_table(
        "account_listings",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("seller_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("cars_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("game_currency", sa.String(160), nullable=False),
        sa.Column("extra_currency", sa.String(160)),
        sa.Column("email_binding", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price_af_coins", sa.Numeric(18, 2), nullable=False),
        sa.Column("image_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active','paused','deleted')", name="ck_account_listings_status"),
        sa.CheckConstraint("price_af_coins >= 100", name="ck_account_listings_min_price"),
        sa.CheckConstraint("cars_count >= 0", name="ck_account_listings_cars_count"),
    )
    op.create_index("ix_account_listings_seller_id", "account_listings", ["seller_id"])
    op.create_index("ix_account_listings_status", "account_listings", ["status"])

    op.create_table(
        "conversations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("listing_id", uuid_type, sa.ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("buyer_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("seller_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deal_id", uuid_type, sa.ForeignKey("deals.id", ondelete="SET NULL"), unique=True),
        sa.Column("accepted_price_af_coins", sa.Numeric(18, 2)),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("listing_id", "buyer_id", name="uq_conversation_listing_buyer"),
        sa.CheckConstraint("buyer_id <> seller_id", name="ck_conversation_distinct_participants"),
        sa.CheckConstraint("accepted_price_af_coins IS NULL OR accepted_price_af_coins >= 100", name="ck_conversation_accepted_price"),
    )
    op.create_index("ix_conversations_listing_id", "conversations", ["listing_id"])
    op.create_index("ix_conversations_buyer_id", "conversations", ["buyer_id"])
    op.create_index("ix_conversations_seller_id", "conversations", ["seller_id"])
    op.create_index("ix_conversations_last_message_at", "conversations", ["last_message_at"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("conversation_id", uuid_type, sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("message_type", sa.String(24), nullable=False, server_default="text"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("message_type IN ('text','system','offer')", name="ck_conversation_message_type"),
    )
    op.create_index("ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"])
    op.create_index("ix_conversation_messages_created_at", "conversation_messages", ["created_at"])

    op.create_table(
        "price_offers",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("conversation_id", uuid_type, sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("offered_by_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount_af_coins", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("parent_offer_id", uuid_type, sa.ForeignKey("price_offers.id", ondelete="SET NULL")),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("amount_af_coins >= 100", name="ck_price_offers_min_price"),
        sa.CheckConstraint("status IN ('pending','accepted','rejected','countered')", name="ck_price_offers_status"),
    )
    op.create_index("ix_price_offers_conversation_id", "price_offers", ["conversation_id"])
    op.create_index("ix_price_offers_status", "price_offers", ["status"])


def downgrade() -> None:
    op.drop_table("price_offers")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
    op.drop_table("account_listings")
    op.drop_constraint("ck_listings_status", "listings", type_="check")
    op.create_check_constraint("ck_listings_status", "listings", "status IN ('active','reserved','sold','deleted')")
    op.drop_index("ix_listings_pinned_until", table_name="listings")
    op.drop_column("listings", "pinned_until")
