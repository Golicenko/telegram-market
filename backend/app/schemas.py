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


class MeOut(BaseModel):
    user: UserOut
    wallet: WalletOut


class ListingCreate(BaseModel):
    brand: str = Field(min_length=1, max_length=96)
    model: str = Field(min_length=1, max_length=96)
    power_hp: int = Field(gt=0, le=5000)
    max_speed_kph: int = Field(gt=0, le=2000)
    description: str = Field(min_length=1, max_length=3000)
    price_af_coins: Decimal = Field(gt=0, decimal_places=2)
    image_urls: list[str] = Field(min_length=1, max_length=1)

    @field_validator("brand", "model")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class UniqueListingCreate(ListingCreate):
    pinned: bool = False


class ListingUpdate(BaseModel):
    brand: str | None = Field(default=None, min_length=1, max_length=96)
    model: str | None = Field(default=None, min_length=1, max_length=96)
    power_hp: int | None = Field(default=None, gt=0, le=5000)
    max_speed_kph: int | None = Field(default=None, gt=0, le=2000)
    description: str | None = Field(default=None, min_length=1, max_length=3000)
    price_af_coins: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    image_urls: list[str] | None = Field(default=None, min_length=1, max_length=1)


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
    views_count: int
    pinned: bool
    pinned_until: datetime | None
    effective_price_af_coins: Decimal | None = None
    created_at: datetime
    images: list[str] = Field(default_factory=list)


class DealOut(ORMModel):
    id: uuid.UUID
    listing_id: uuid.UUID
    buyer_id: uuid.UUID
    seller_id: uuid.UUID
    status: str
    price_af_coins: Decimal
    transfer_started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


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


class ConversationMessageOut(ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    body: str
    message_type: str

    is_read: bool
    read_at: datetime | None

    created_at: datetime


class PriceOfferCreate(BaseModel):
    amount_af_coins: Decimal = Field(gt=0, decimal_places=2)


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
    amount: int = Field(gt=0, le=1000)


class StarPaymentIntentOut(BaseModel):
    id: uuid.UUID
    invoice_url: str
    amount: int
    status: str


class StarPaymentStatusOut(BaseModel):
    id: uuid.UUID
    status: str
    amount: int
    wallet: WalletOut


class SupportTicketCreate(BaseModel):
    topic: str = Field(min_length=2, max_length=64)
    message: str = Field(min_length=2, max_length=4000)
    screenshot_url: str | None = None


class SupportReplyCreate(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class SupportStatusUpdate(BaseModel):
    status: str = Field(pattern="^(open|in_progress|resolved|closed)$")


class SupportMessageOut(ORMModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    body: str
    created_at: datetime


class SupportTicketOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    topic: str
    status: str
    screenshot_url: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[SupportMessageOut] = Field(default_factory=list)


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
