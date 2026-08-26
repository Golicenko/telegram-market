import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORMModel):
    id: uuid.UUID
    telegram_id: int
    role: str
    first_name: str
    last_name: str | None
    username: str | None
    photo_url: str | None
    is_blocked: bool


class WalletOut(ORMModel):
    available_balance: Decimal
    frozen_balance: Decimal
    total_earned: Decimal
    purchased_balance: Decimal
    earned_balance: Decimal
    purchased_frozen_balance: Decimal
    earned_frozen_balance: Decimal


class MeOut(BaseModel):
    user: UserOut
    wallet: WalletOut


class ListingCreate(BaseModel):
    brand: str = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1)
    power_hp: int = Field(gt=0)
    max_speed_kph: int = Field(gt=0)
    description: str = Field(min_length=1)
    price_af_coins: Decimal = Field(ge=1, decimal_places=2)
    delivery_time_estimate: str = Field(
        default="up_to_1h",
        pattern="^(up_to_15m|up_to_30m|up_to_1h|up_to_3h|up_to_6h|up_to_12h|up_to_24h)$",
    )
    image_urls: list[str] = Field(min_length=1, max_length=10)

    @field_validator("brand")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("model")
    @classmethod
    def strip_legacy_model(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class UniqueListingCreate(ListingCreate):
    pinned: bool = False


class ListingUpdate(BaseModel):
    brand: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    power_hp: int | None = Field(default=None, gt=0)
    max_speed_kph: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, min_length=1)
    price_af_coins: Decimal | None = Field(default=None, ge=1, decimal_places=2)
    delivery_time_estimate: str | None = Field(
        default=None,
        pattern="^(up_to_15m|up_to_30m|up_to_1h|up_to_3h|up_to_6h|up_to_12h|up_to_24h)$",
    )
    image_urls: list[str] | None = Field(default=None, min_length=1, max_length=10)


class ListingOut(ORMModel):
    id: uuid.UUID
    seller_id: uuid.UUID
    listing_type: str
    status: str
    brand: str
    model: str
    power_hp: int
    max_speed_kph: int
    description: str
    price_af_coins: Decimal
    delivery_time_estimate: str
    views_count: int
    likes_count: int = 0
    liked_by_me: bool = False
    pinned: bool
    pinned_until: datetime | None
    effective_price_af_coins: Decimal | None = None
    created_at: datetime
    images: list[str] = Field(default_factory=list)


class ListingEngagementOut(BaseModel):
    views_count: int
    likes_count: int
    liked_by_me: bool
    view_recorded: bool = False


class DealOut(ORMModel):
    id: uuid.UUID
    listing_id: uuid.UUID
    conversation_id: uuid.UUID | None
    buyer_id: uuid.UUID
    seller_id: uuid.UUID
    status: str
    price_af_coins: Decimal
    buyer_game_id: str | None
    preferred_delivery_time: str | None
    transfer_started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class DealDeliveryDetailsCreate(BaseModel):
    buyer_game_id: str = Field(min_length=1, max_length=128)
    delivery_window: str = Field(pattern="^(now|today|scheduled)$")
    preferred_time: str | None = Field(default=None, pattern="^([01]\\d|2[0-3]):[0-5]\\d$")

    @field_validator("buyer_game_id")
    @classmethod
    def normalize_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Укажите игровой ID")
        return value

    @field_validator("preferred_time")
    @classmethod
    def normalize_preferred_time(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class ConversationMessageCreate(MessageCreate):
    client_message_id: uuid.UUID


class MessageOut(ORMModel):
    id: uuid.UUID
    deal_id: uuid.UUID
    sender_id: uuid.UUID
    body: str
    created_at: datetime


class AccountListingCreate(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    level: int = Field(ge=0, le=100000)
    cars_count: int = Field(ge=0, le=100000)
    game_currency: str = Field(min_length=1, max_length=160)
    extra_currency: str | None = Field(default=None, max_length=160)
    game_assets: str | None = Field(default=None, max_length=3000)
    email_binding: str = Field(pattern="^(linked|unlinked|unknown)$")
    auto_delivery: bool = False
    description: str = Field(min_length=5, max_length=5000)
    price_af_coins: Decimal = Field(gt=0, decimal_places=2)
    image_url: str = Field(min_length=1, max_length=2000)


class AccountListingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=160)
    level: int | None = Field(default=None, ge=0, le=100000)
    cars_count: int | None = Field(default=None, ge=0, le=100000)
    game_currency: str | None = Field(default=None, min_length=1, max_length=160)
    extra_currency: str | None = Field(default=None, max_length=160)
    game_assets: str | None = Field(default=None, max_length=3000)
    email_binding: str | None = Field(default=None, pattern="^(linked|unlinked|unknown)$")
    auto_delivery: bool | None = None
    description: str | None = Field(default=None, min_length=5, max_length=5000)
    price_af_coins: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    image_url: str | None = None
    status: str | None = Field(default=None, pattern="^(active|paused|deleted)$")


class AccountListingOut(ORMModel):
    id: uuid.UUID
    seller_id: uuid.UUID
    status: str
    title: str
    level: int
    cars_count: int
    game_currency: str
    extra_currency: str | None
    game_assets: str | None
    email_binding: str
    auto_delivery: bool
    description: str
    price_af_coins: Decimal
    image_url: str | None
    created_at: datetime


class TrainingProductCreate(BaseModel):
    title: str = Field(min_length=1)
    short_description: str = Field(min_length=1)
    full_description: str = Field(min_length=1)
    cover_url: str = Field(min_length=1, max_length=2000)
    promo_video_url: str | None = Field(default=None, max_length=2000)
    product_type: str = Field(pattern="^(personal|automatic)$")
    price_af_coins: Decimal = Field(gt=0, decimal_places=2)
    availability: str = Field(default="available", pattern="^(available|unavailable|coming_soon)$")
    published: bool = False
    pinned: bool = False


class TrainingProductUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    short_description: str | None = Field(default=None, min_length=1)
    full_description: str | None = Field(default=None, min_length=1)
    cover_url: str | None = Field(default=None, min_length=1, max_length=2000)
    promo_video_url: str | None = Field(default=None, max_length=2000)
    product_type: str | None = Field(default=None, pattern="^(personal|automatic)$")
    price_af_coins: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    availability: str | None = Field(default=None, pattern="^(available|unavailable|coming_soon)$")
    published: bool | None = None
    pinned: bool | None = None


class TrainingProductOut(ORMModel):
    id: uuid.UUID
    admin_id: uuid.UUID
    title: str
    short_description: str
    full_description: str
    cover_url: str
    promo_video_url: str | None
    product_type: str
    price_af_coins: Decimal
    availability: str
    published: bool
    pinned: bool
    created_at: datetime
    updated_at: datetime


class TrainingMaterialCreate(BaseModel):
    title: str = Field(min_length=1)
    material_type: str = Field(pattern="^(text|link|photo|video|document)$")
    delivery_reference: str = Field(min_length=1, max_length=8000)
    mime_type: str | None = Field(default=None, max_length=160)
    file_size: int | None = Field(default=None, ge=0)
    metadata_json: dict = Field(default_factory=dict)
    position: int = Field(default=0, ge=0)


class TrainingMaterialUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    material_type: str | None = Field(default=None, pattern="^(text|link|photo|video|document)$")
    delivery_reference: str | None = Field(default=None, min_length=1, max_length=8000)
    mime_type: str | None = Field(default=None, max_length=160)
    file_size: int | None = Field(default=None, ge=0)
    metadata_json: dict | None = None
    position: int | None = Field(default=None, ge=0)


class TrainingMaterialPublicOut(ORMModel):
    id: uuid.UUID
    title: str
    material_type: str
    mime_type: str | None
    file_size: int | None
    metadata_json: dict
    position: int


class TrainingMaterialAdminOut(TrainingMaterialPublicOut):
    product_id: uuid.UUID
    delivery_reference: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TrainingPurchaseOut(ORMModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_type: str
    title_snapshot: str
    cover_url_snapshot: str
    price_af_coins: Decimal
    buyer_telegram_id: int
    buyer_display_name: str
    buyer_username: str | None
    payment_status: str
    status: str
    delivery_status: str
    delivery_attempts: int
    last_delivery_requested_at: datetime | None
    created_at: datetime
    completed_at: datetime | None
    materials: list[TrainingMaterialPublicOut] = Field(default_factory=list)


class TrainingBuyerOut(ORMModel):
    id: uuid.UUID
    telegram_id: int
    first_name: str
    last_name: str | None
    username: str | None
    photo_url: str | None


class TrainingPurchaseAdminOut(TrainingPurchaseOut):
    buyer: TrainingBuyerOut
    seller_payout: Decimal
    platform_commission: Decimal
    settled_at: datetime | None
    admin_notification_status: str
    admin_notification_attempts: int
    admin_notification_error: str | None
    admin_notification_last_attempt_at: datetime | None
    admin_notified_at: datetime | None


class TrainingAdminProductOut(TrainingProductOut):
    purchase_count: int = 0
    revenue_af_coins: Decimal = Decimal("0")
    archived: bool = False


class TrainingAdminStatsOut(BaseModel):
    total_sales: int
    total_revenue_af_coins: Decimal
    personal_sales: int
    automatic_sales: int


class TrainingPurchaseStatusUpdate(BaseModel):
    status: str = Field(pattern="^(in_progress|completed)$")


class ConversationMessageOut(ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    body: str
    message_type: str
    client_message_id: uuid.UUID | None

    is_read: bool
    read_at: datetime | None

    created_at: datetime


class PriceOfferCreate(BaseModel):
    amount_af_coins: Decimal = Field(ge=1, decimal_places=2)


class CounterOfferCreate(PriceOfferCreate):
    parent_offer_id: uuid.UUID


class PriceOfferOut(ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    offered_by_id: uuid.UUID
    amount_af_coins: Decimal
    status: str
    parent_offer_id: uuid.UUID | None
    responded_at: datetime | None
    created_at: datetime


class DealResolution(BaseModel):
    outcome: str = Field(pattern="^(complete|refund)$")
    reason: str = Field(min_length=5, max_length=2000)


class WithdrawalCreate(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2)
    payout_method: str = Field(min_length=2, max_length=64)
    details: str = Field(min_length=2, max_length=2000)


class WithdrawalDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class WithdrawalOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    amount: Decimal
    payout_method: str
    details: str
    status: str
    rejection_reason: str | None
    created_at: datetime


class AdminWithdrawalOut(WithdrawalOut):
    user_telegram_id: int
    user_name: str
    user_username: str | None = None


class BalanceAdjustmentCreate(BaseModel):
    user_id: uuid.UUID
    amount: Decimal
    reason: str = Field(min_length=5, max_length=2000)


class NotificationOut(ORMModel):
    id: uuid.UUID
    notification_type: str
    title: str
    body: str
    payload: dict
    read_at: datetime | None
    created_at: datetime


class StarPaymentIntentCreate(BaseModel):
    amount: int = Field(ge=1, le=1000)
    purpose: str = Field(default="topup", pattern="^(topup|cart_checkout|training_topup)$")
    training_product_id: uuid.UUID | None = None


class StarPaymentIntentOut(BaseModel):
    id: uuid.UUID
    invoice_url: str
    amount: int
    status: str
    purpose: str = "topup"
    listing_id: uuid.UUID | None = None
    training_product_id: uuid.UUID | None = None
    training_purchase_id: uuid.UUID | None = None
    missing_af_coins: Decimal | None = None
    checkout_status: str = "not_requested"


class StarPaymentStatusOut(BaseModel):
    id: uuid.UUID
    status: str
    amount: int
    wallet: WalletOut
    purpose: str = "topup"
    listing_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None
    training_product_id: uuid.UUID | None = None
    training_purchase_id: uuid.UUID | None = None
    checkout_status: str = "not_requested"
    message: str | None = None


class SupportTicketCreate(BaseModel):
    topic: str = Field(min_length=2, max_length=64)
    message: str = Field(min_length=2, max_length=4000)
    screenshot_url: str | None = None


class DealSupportCaseCreate(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    screenshot_url: str = Field(min_length=1, max_length=2000)
    client_request_id: uuid.UUID


class SupportCaseResolution(BaseModel):
    outcome: str = Field(pattern="^(complete|refund)$")
    reason: str = Field(min_length=5, max_length=2000)


class SupportReplyCreate(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    client_request_id: uuid.UUID | None = None


class SupportStatusUpdate(BaseModel):
    status: str = Field(pattern="^(new|open|in_progress|resolved|closed)$")


class SupportMessageOut(ORMModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    client_request_id: uuid.UUID | None
    body: str
    created_at: datetime


class SupportCaseEventOut(ORMModel):
    id: uuid.UUID
    actor_id: uuid.UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    details: dict
    created_at: datetime


class SupportTicketOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    author_id: uuid.UUID
    case_type: str
    deal_id: uuid.UUID | None
    listing_id: uuid.UUID | None
    buyer_id: uuid.UUID | None
    seller_id: uuid.UUID | None
    topic: str
    status: str
    screenshot_url: str | None
    resolved_at: datetime | None
    unread_by_admin: bool
    created_at: datetime
    updated_at: datetime
    messages: list[SupportMessageOut] = Field(default_factory=list)
    conversation_messages: list[ConversationMessageOut] = Field(default_factory=list)
    events: list[SupportCaseEventOut] = Field(default_factory=list)
    listing_title: str | None = None
    buyer: UserOut | None = None
    seller: UserOut | None = None
    author: UserOut | None = None


class AdvertisementUpsert(BaseModel):
    image_url: str = Field(min_length=1, max_length=2000)
    link_url: str | None = Field(default=None, max_length=2000)
    is_active: bool = True

    @field_validator("link_url")
    @classmethod
    def validate_link(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not value.startswith(("https://", "http://")):
            raise ValueError("Ссылка должна начинаться с https:// или http://")
        return value


class AdvertisementOut(ORMModel):
    id: uuid.UUID
    image_url: str
    link_url: str | None
    is_active: bool
    admin_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class AdminBroadcastCreate(BaseModel):
    client_request_id: uuid.UUID
    text: str = Field(default="", max_length=4096)
    photo_url: str | None = Field(default=None, max_length=2000)

    @field_validator("text")
    @classmethod
    def normalize_broadcast_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("photo_url")
    @classmethod
    def normalize_broadcast_photo(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class AdminBroadcastOut(ORMModel):
    id: uuid.UUID
    content_type: str
    text: str
    photo_file_id: str | None
    status: str
    total_recipients: int
    sent_count: int
    failed_count: int
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    created_at: datetime


class ProfileOut(BaseModel):
    user: UserOut
    wallet: WalletOut
    active_listings: list[ListingOut]
    sold_listings: list[ListingOut]
    purchases: list[ListingOut]
    active_deals: list[DealOut]
    conversations: list[dict]
    wallet_transactions: list[dict]
    withdrawals: list[WithdrawalOut]
