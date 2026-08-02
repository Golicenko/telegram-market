import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64))
    photo_url: Mapped[str | None] = mapped_column(Text)
    mini_app_last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bot_started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (CheckConstraint("role IN ('user','admin')", name="ck_users_role"),)


class Listing(Base, TimestampMixin):
    __tablename__ = "listings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    brand: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    power_hp: Mapped[int] = mapped_column(Integer, nullable=False)
    max_speed_kph: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price_af_coins: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    views_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pinned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reserved_by_deal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("listing_type IN ('regular','unique')", name="ck_listings_type"),
        CheckConstraint("status IN ('active','paused','reserved','sold','deleted')", name="ck_listings_status"),
        CheckConstraint("price_af_coins >= 100", name="ck_listings_min_price"),
        CheckConstraint("power_hp > 0 AND max_speed_kph > 0", name="ck_listings_positive_stats"),
        CheckConstraint("views_count >= 0", name="ck_listings_views_nonnegative"),
        Index("ix_listings_type_status_created", "listing_type", "status", "created_at"),
    )


class ListingImage(Base):
    __tablename__ = "listing_images"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("listing_id", "position", name="uq_listing_image_position"),)


class AccountListing(Base, TimestampMixin):
    __tablename__ = "account_listings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cars_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    game_currency: Mapped[str] = mapped_column(String(160), nullable=False)
    extra_currency: Mapped[str | None] = mapped_column(String(160))
    game_assets: Mapped[str | None] = mapped_column(Text)
    email_binding: Mapped[str] = mapped_column(String(32), nullable=False)
    auto_delivery: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price_af_coins: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("status IN ('active','paused','deleted')", name="ck_account_listings_status"),
        CheckConstraint("price_af_coins >= 100", name="ck_account_listings_min_price"),
        CheckConstraint("cars_count >= 0", name="ck_account_listings_cars_count"),
        CheckConstraint("level >= 0", name="ck_account_listings_level"),
    )


class Favorite(Base):
    __tablename__ = "favorites"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("user_id", "listing_id", name="uq_favorite_user_listing"),)


class CartItem(Base):
    __tablename__ = "cart_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("user_id", "listing_id", name="uq_cart_user_listing"),)


class Deal(Base, TimestampMixin):
    __tablename__ = "deals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False)
    buyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_payment", index=True)
    price_af_coins: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    frozen_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    seller_payout: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    platform_commission: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    transfer_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    buyer_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('pending_payment','paid','seller_contacted','transfer_in_progress','buyer_confirmed','completed','disputed','cancelled')", name="ck_deals_status"),
        Index(
            "uq_deals_open_listing",
            "listing_id",
            unique=True,
            postgresql_where=text("status NOT IN ('completed','cancelled')"),
        ),
    )


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    buyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"), unique=True)
    accepted_price_af_coins: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (
        UniqueConstraint("listing_id", "buyer_id", name="uq_conversation_listing_buyer"),
        CheckConstraint("buyer_id <> seller_id", name="ck_conversation_distinct_participants"),
        CheckConstraint("accepted_price_af_coins IS NULL OR accepted_price_af_coins >= 100", name="ck_conversation_accepted_price"),
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    sender_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    message_type: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="text",
    )

    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        index=True,
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "message_type IN ('text','system','offer')",
            name="ck_conversation_message_type",
        ),
    )

class PriceOffer(Base, TimestampMixin):
    __tablename__ = "price_offers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    offered_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    amount_af_coins: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    parent_offer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("price_offers.id", ondelete="SET NULL"))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("amount_af_coins >= 100", name="ck_price_offers_min_price"),
        CheckConstraint("status IN ('pending','accepted','rejected','countered')", name="ck_price_offers_status"),
    )


class DealMessage(Base):
    __tablename__ = "deal_messages"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Wallet(Base):
    __tablename__ = "wallets"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True)
    available_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    frozen_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_earned: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (CheckConstraint("available_balance >= 0 AND frozen_balance >= 0 AND total_earned >= 0", name="ck_wallet_nonnegative"),)


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    available_before: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    available_after: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    frozen_before: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    frozen_after: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    related_deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"))
    related_withdrawal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("withdrawal_requests.id", ondelete="SET NULL"))
    external_reference: Mapped[str | None] = mapped_column(String(255), unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class StarPayment(Base):
    __tablename__ = "star_payments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    telegram_payment_charge_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    provider_payment_charge_id: Mapped[str | None] = mapped_column(String(255))
    xtr_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    af_coin_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StarPaymentIntent(Base):
    __tablename__ = "star_payment_intents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    invoice_payload: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    invoice_link: Mapped[str | None] = mapped_column(Text)
    xtr_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("xtr_amount BETWEEN 100 AND 1000", name="ck_star_payment_intent_amount"),
        CheckConstraint("status IN ('pending','paid','cancelled','expired')", name="ck_star_payment_intent_status"),
    )


class WithdrawalRequest(Base, TimestampMixin):
    __tablename__ = "withdrawal_requests"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    payout_method: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status IN ('pending','approved','paid','rejected','cancelled')", name="ck_withdrawal_status"),)


class AdminBalanceAdjustment(Base):
    __tablename__ = "admin_balance_adjustments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    wallet_transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wallet_transactions.id", ondelete="RESTRICT"), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdminAction(Base):
    __tablename__ = "admin_actions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(96), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SupportTicket(Base, TimestampMixin):
    __tablename__ = "support_tickets"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    screenshot_url: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("status IN ('open','in_progress','resolved','closed')", name="ck_support_ticket_status"),)


class SupportMessage(Base):
    __tablename__ = "support_messages"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Advertisement(Base, TimestampMixin):
    __tablename__ = "advertisements"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    link_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
