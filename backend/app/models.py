import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint, func, text as sql_text
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
    brand: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    power_hp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_speed_kph: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price_af_coins: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    delivery_time_estimate: Mapped[str] = mapped_column(String(24), nullable=False, default="up_to_1h")
    views_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pinned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reserved_by_deal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("listing_type IN ('regular','unique')", name="ck_listings_type"),
        CheckConstraint("status IN ('active','paused','reserved','sold','deleted')", name="ck_listings_status"),
        CheckConstraint("price_af_coins >= 1", name="ck_listings_min_price"),
        CheckConstraint("power_hp > 0 AND max_speed_kph > 0", name="ck_listings_positive_stats"),
        CheckConstraint(
            "delivery_time_estimate IN ('up_to_15m','up_to_30m','up_to_1h','up_to_3h','up_to_6h','up_to_12h','up_to_24h')",
            name="ck_listings_delivery_time",
        ),
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


class UploadedImage(Base):
    """A normalized image kept in PostgreSQL so Railway restarts cannot lose it."""

    __tablename__ = "uploaded_images"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("size_bytes > 0", name="ck_uploaded_images_size_positive"),)


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


class TrainingProduct(Base, TimestampMixin):
    __tablename__ = "training_products"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    short_description: Mapped[str] = mapped_column(Text, nullable=False)
    full_description: Mapped[str] = mapped_column(Text, nullable=False)
    cover_url: Mapped[str] = mapped_column(Text, nullable=False)
    promo_video_url: Mapped[str | None] = mapped_column(Text)
    product_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    price_af_coins: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    availability: Mapped[str] = mapped_column(String(24), nullable=False, default="available")
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (
        CheckConstraint("product_type IN ('personal','automatic')", name="ck_training_products_type"),
        CheckConstraint("availability IN ('available','unavailable','coming_soon')", name="ck_training_products_availability"),
        CheckConstraint("price_af_coins >= 0", name="ck_training_products_price"),
        Index("ix_training_products_public_order", "published", "pinned", "created_at"),
    )


class TrainingMaterial(Base, TimestampMixin):
    __tablename__ = "training_materials"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("training_products.id", ondelete="RESTRICT"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    material_type: Mapped[str] = mapped_column(String(24), nullable=False)
    delivery_reference: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(160))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    __table_args__ = (
        CheckConstraint("material_type IN ('text','link','photo','video','document')", name="ck_training_materials_type"),
        CheckConstraint("position >= 0", name="ck_training_materials_position"),
        CheckConstraint("file_size IS NULL OR file_size >= 0", name="ck_training_materials_file_size"),
        Index("ix_training_materials_product_order", "product_id", "is_active", "position"),
    )


class TrainingPurchase(Base, TimestampMixin):
    __tablename__ = "training_purchases"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("training_products.id", ondelete="RESTRICT"), nullable=False, index=True)
    buyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    buyer_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    buyer_display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    buyer_username: Mapped[str | None] = mapped_column(String(64))
    telegram_payment_charge_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    payment_status: Mapped[str] = mapped_column(String(16), nullable=False, default="paid", index=True)
    admin_notification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    admin_notification_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    admin_notification_error: Mapped[str | None] = mapped_column(Text)
    admin_notification_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    product_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    cover_url_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    price_af_coins: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    seller_payout: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    platform_commission: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    delivery_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_applicable", index=True)
    purchased_frozen_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    earned_frozen_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_delivery_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_lock_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("product_id", "buyer_id", name="uq_training_purchase_product_buyer"),
        CheckConstraint("product_type IN ('personal','automatic')", name="ck_training_purchases_type"),
        CheckConstraint("payment_status = 'paid'", name="ck_training_purchases_payment_status"),
        CheckConstraint("admin_notification_status IN ('pending','sending','sent','failed','not_required')", name="ck_training_purchases_admin_notification_status"),
        CheckConstraint("admin_notification_attempts >= 0", name="ck_training_purchases_admin_notification_attempts"),
        CheckConstraint("status IN ('awaiting_start','in_progress','completed')", name="ck_training_purchases_status"),
        CheckConstraint("delivery_status IN ('not_applicable','pending','sending','delivered','failed')", name="ck_training_purchases_delivery_status"),
        CheckConstraint("price_af_coins >= 0 AND seller_payout >= 0 AND platform_commission >= 0", name="ck_training_purchases_amounts"),
        CheckConstraint("purchased_frozen_amount >= 0 AND earned_frozen_amount >= 0", name="ck_training_purchases_frozen"),
        CheckConstraint("delivery_attempts >= 0", name="ck_training_purchases_delivery_attempts"),
        Index("ix_training_purchases_buyer_created", "buyer_id", "created_at"),
        Index("ix_training_purchases_product_status", "product_id", "status"),
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
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), index=True)
    buyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_payment", index=True)
    price_af_coins: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    frozen_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    purchased_frozen_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    earned_frozen_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    seller_payout: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    platform_commission: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    buyer_game_id: Mapped[str | None] = mapped_column(String(128))
    preferred_delivery_time: Mapped[str | None] = mapped_column(String(64))
    seller_purchase_notification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending", index=True
    )
    seller_purchase_notification_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seller_purchase_notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seller_purchase_notification_error: Mapped[str | None] = mapped_column(Text)
    transfer_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    buyer_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('pending_payment','paid','seller_contacted','transfer_in_progress','buyer_confirmed','completed','disputed','cancelled')", name="ck_deals_status"),
        CheckConstraint(
            "seller_purchase_notification_status IN ('pending','sending','sent','failed')",
            name="ck_deals_seller_purchase_notification_status",
        ),
        Index(
            "uq_deals_open_listing",
            "listing_id",
            unique=True,
            postgresql_where=sql_text("status NOT IN ('completed','cancelled')"),
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
    buyer_hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seller_hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index(
            "uq_conversations_participant_pair",
            sql_text("LEAST(buyer_id, seller_id)"),
            sql_text("GREATEST(buyer_id, seller_id)"),
            unique=True,
        ),
        CheckConstraint("buyer_id <> seller_id", name="ck_conversation_distinct_participants"),
        CheckConstraint("accepted_price_af_coins IS NULL OR accepted_price_af_coins >= 1", name="ck_conversation_accepted_price"),
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
        server_default=sql_text("false"),
        index=True,
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    client_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

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
        UniqueConstraint("conversation_id", "sender_id", "client_message_id", name="uq_conversation_message_client_id"),
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
        CheckConstraint("amount_af_coins >= 1", name="ck_price_offers_min_price"),
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
    purchased_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    earned_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    purchased_frozen_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    earned_frozen_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_earned: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        CheckConstraint(
            "purchased_balance >= 0 AND earned_balance >= 0 "
            "AND purchased_frozen_balance >= 0 AND earned_frozen_balance >= 0 "
            "AND total_earned >= 0",
            name="ck_wallet_nonnegative",
        ),
    )

    @property
    def available_balance(self) -> Decimal:
        return Decimal(self.purchased_balance or 0) + Decimal(self.earned_balance or 0)

    @property
    def frozen_balance(self) -> Decimal:
        return Decimal(self.purchased_frozen_balance or 0) + Decimal(self.earned_frozen_balance or 0)


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
    related_training_purchase_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("training_purchases.id", ondelete="SET NULL"), index=True)
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
    purpose: Mapped[str] = mapped_column(String(24), nullable=False, default="topup")
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    listing_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"), index=True)
    seller_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"), index=True)
    training_product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("training_products.id", ondelete="RESTRICT"), index=True)
    training_purchase_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("training_purchases.id", ondelete="SET NULL"), index=True)
    listing_price_af_coins: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    available_balance_at_creation: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    missing_af_coins: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    checkout_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_requested", index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("(purpose IN ('listing_checkout','training_checkout','training_topup') AND xtr_amount >= 1) OR (purpose NOT IN ('listing_checkout','training_checkout','training_topup') AND xtr_amount BETWEEN 10 AND 1000)", name="ck_star_payment_intent_amount"),
        CheckConstraint("purpose IN ('topup','cart_checkout','listing_checkout','training_checkout','training_topup')", name="ck_star_payment_intent_purpose"),
        CheckConstraint("status IN ('pending','paid','cancelled','expired')", name="ck_star_payment_intent_status"),
        CheckConstraint("checkout_status IN ('not_requested','pending','completed','listing_unavailable','failed')", name="ck_star_payment_intent_checkout_status"),
        CheckConstraint("missing_af_coins IS NULL OR missing_af_coins > 0", name="ck_star_payment_intent_missing"),
        Index(
            "uq_star_payment_intents_pending_listing",
            "user_id",
            "listing_id",
            unique=True,
            postgresql_where=sql_text("purpose = 'listing_checkout' AND status = 'pending'"),
        ),
        Index(
            "uq_star_payment_intents_pending_training",
            "user_id",
            "training_product_id",
            unique=True,
            postgresql_where=sql_text("purpose = 'training_checkout' AND status = 'pending'"),
        ),
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


class AdminBroadcast(Base):
    __tablename__ = "admin_broadcasts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_update_id: Mapped[int | None] = mapped_column(BigInteger)
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    admin_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    photo_file_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    total_recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    __table_args__ = (
        UniqueConstraint("telegram_update_id", name="uq_admin_broadcast_telegram_update"),
        UniqueConstraint("client_request_id", name="uq_admin_broadcast_client_request"),
        CheckConstraint("content_type IN ('text','photo')", name="ck_admin_broadcast_content_type"),
        CheckConstraint("status IN ('draft','queued','running','completed','failed')", name="ck_admin_broadcast_status"),
        CheckConstraint("total_recipients >= 0 AND sent_count >= 0 AND failed_count >= 0", name="ck_admin_broadcast_counts"),
        Index(
            "uq_admin_broadcast_active_admin",
            "admin_telegram_id",
            unique=True,
            postgresql_where=sql_text("status IN ('queued','running')"),
        ),
    )


class AdminBroadcastRecipient(Base):
    __tablename__ = "admin_broadcast_recipients"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broadcast_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("admin_broadcasts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("broadcast_id", "user_id", name="uq_broadcast_recipient_user"),
        CheckConstraint("status IN ('pending','sending','sent','failed')", name="ck_broadcast_recipient_status"),
        CheckConstraint("attempts >= 0", name="ck_broadcast_recipient_attempts"),
    )


class SupportTicket(Base, TimestampMixin):
    __tablename__ = "support_tickets"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    case_type: Mapped[str] = mapped_column(String(16), nullable=False, default="general", index=True)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id", ondelete="RESTRICT"), index=True)
    listing_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"), index=True)
    buyer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    seller_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    screenshot_url: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unread_by_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    __table_args__ = (
        CheckConstraint("case_type IN ('general','deal')", name="ck_support_ticket_case_type"),
        CheckConstraint("status IN ('new','open','in_progress','resolved','closed')", name="ck_support_ticket_status"),
        CheckConstraint(
            "case_type = 'general' OR (deal_id IS NOT NULL AND listing_id IS NOT NULL AND buyer_id IS NOT NULL AND seller_id IS NOT NULL)",
            name="ck_support_ticket_deal_context",
        ),
        Index(
            "uq_support_active_deal",
            "deal_id",
            unique=True,
            postgresql_where=sql_text("case_type = 'deal' AND status IN ('new','open','in_progress')"),
        ),
    )


class SupportMessage(Base):
    __tablename__ = "support_messages"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    __table_args__ = (
        UniqueConstraint("ticket_id", "sender_id", "client_request_id", name="uq_support_message_client_request"),
    )


class SupportCaseEvent(Base):
    __tablename__ = "support_case_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("support_tickets.id", ondelete="RESTRICT"), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str | None] = mapped_column(String(24))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Advertisement(Base, TimestampMixin):
    __tablename__ = "advertisements"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    link_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
