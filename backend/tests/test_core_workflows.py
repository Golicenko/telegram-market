import hashlib
import hmac
import json
import time
import uuid
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.auth import get_current_user, require_admin, validate_init_data
from app.config import Settings
from app.models import Deal, Listing, ListingImage, StarPayment, StarPaymentIntent, User, Wallet, WalletTransaction
from app.schemas import ListingCreate
from app.services import (
    charge_listing_promotion,
    create_withdrawal,
    create_listing,
    hold_for_purchase,
    process_successful_payment,
    release_purchase_hold,
    settlement_amounts,
)


def signed_init_data(bot_token: str, user: dict) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "AAE-test",
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_telegram_init_data_signature_and_tampering():
    token = "123456:TEST_TOKEN"
    payload = signed_init_data(token, {"id": 123, "first_name": "Иван"})
    assert validate_init_data(payload, token)["id"] == 123
    with pytest.raises(ValueError, match="signature"):
        validate_init_data(payload.replace("123", "124", 1), token)


def test_listing_accepts_multiple_images_and_unbounded_positive_stats():
    values = {
        "brand": "Произвольное название автомобиля " + ("X" * 5000),
        "model": None,
        "power_hp": 1_000_000_000_000,
        "max_speed_kph": 1_000_000_000_000,
        "description": "Описание " + ("Y" * 10000),
        "price_af_coins": 100,
    }
    assert len(ListingCreate(**values, image_urls=["/uploads/one.jpg"]).image_urls) == 1
    assert len(ListingCreate(**values, image_urls=["one", "two", "three"]).image_urls) == 3
    assert ListingCreate(**{**values, "price_af_coins": 1}, image_urls=["one"]).price_af_coins == 1
    with pytest.raises(ValidationError):
        ListingCreate(**values, image_urls=[])
    with pytest.raises(ValidationError):
        ListingCreate(**values, image_urls=[str(index) for index in range(11)])
    with pytest.raises(ValidationError):
        ListingCreate(**{**values, "power_hp": 0}, image_urls=["one"])
    with pytest.raises(ValidationError):
        ListingCreate(**{**values, "price_af_coins": 0}, image_urls=["one"])


def test_server_commission_is_single_70_30_formula():
    payout, commission = settlement_amounts(Decimal("101.00"))
    assert payout == Decimal("70.70")
    assert commission == Decimal("30.30")
    assert payout + commission == Decimal("101.00")


def test_minimum_topup_is_ten_stars():
    assert Settings(bot_token="123456:TEST_TOKEN").star_topup_min == 10


def test_purchase_hold_preserves_fund_origin_and_refund():
    wallet = Wallet(
        user_id=uuid.uuid4(), purchased_balance=Decimal("70"), earned_balance=Decimal("50"),
        purchased_frozen_balance=0, earned_frozen_balance=0, total_earned=Decimal("50"), version=0,
    )
    purchased, earned = hold_for_purchase(wallet, Decimal("100"))
    assert (purchased, earned) == (Decimal("70.00"), Decimal("30.00"))
    assert wallet.available_balance == Decimal("20.00")
    assert wallet.frozen_balance == Decimal("100.00")
    release_purchase_hold(wallet, purchased, earned)
    assert wallet.purchased_balance == Decimal("70.00")
    assert wallet.earned_balance == Decimal("50.00")


@pytest.mark.asyncio
async def test_non_admin_is_rejected_by_backend_dependency():
    user = User(id=uuid.uuid4(), telegram_id=1, first_name="User", role="user")
    with pytest.raises(HTTPException) as error:
        await require_admin(user)
    assert error.value.status_code == 403


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def __init__(self, scalars=()):
        self.scalars = list(scalars)
        self.added = []

    def begin(self):
        return FakeTransaction()

    async def scalar(self, _query):
        return self.scalars.pop(0) if self.scalars else None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def refresh(self, _value):
        return None


@pytest.mark.asyncio
async def test_creating_multiple_regular_listings_is_free():
    seller = User(id=uuid.uuid4(), telegram_id=7, first_name="Seller", role="user")
    payload = ListingCreate(
        brand="BMW",
        model="M5",
        power_hp=600,
        max_speed_kph=300,
        description="Описание",
        price_af_coins=100,
        image_urls=["/api/media/one", "/api/media/two"],
    )
    session = FakeSession()
    first = await create_listing(session, seller, payload, listing_type="regular")
    second = await create_listing(session, seller, payload, listing_type="regular")
    assert first.status == second.status == "active"
    assert not any(isinstance(item, WalletTransaction) for item in session.added)
    assert len([item for item in session.added if isinstance(item, ListingImage)]) == 4


@pytest.mark.asyncio
async def test_promotion_costs_15_and_retry_does_not_charge_twice():
    user_id = uuid.uuid4()
    user = User(id=user_id, telegram_id=8, first_name="Seller", role="user")
    wallet = Wallet(user_id=user_id, purchased_balance=Decimal("100"), earned_balance=0, purchased_frozen_balance=0, earned_frozen_balance=0, total_earned=0, version=0)
    listing = Listing(
        id=uuid.uuid4(), seller_id=user_id, listing_type="regular", status="active",
        brand="BMW", model="M5", power_hp=600, max_speed_kph=300,
        description="Описание", price_af_coins=100, pinned=False, views_count=0,
    )
    session = FakeSession([wallet])
    await charge_listing_promotion(session, user, listing)
    await charge_listing_promotion(session, user, listing)
    assert wallet.available_balance == Decimal("85.00")
    charges = [item for item in session.added if isinstance(item, WalletTransaction)]
    assert len(charges) == 1
    assert charges[0].amount == Decimal("-15.00")


@pytest.mark.asyncio
async def test_successful_star_payment_is_credited_once():
    user_id = uuid.uuid4()
    user = User(id=user_id, telegram_id=99, first_name="Buyer", role="user")
    wallet = Wallet(user_id=user_id, purchased_balance=Decimal("5"), earned_balance=0, purchased_frozen_balance=0, earned_frozen_balance=0, total_earned=0, version=0)
    intent = StarPaymentIntent(
        id=uuid.uuid4(), user_id=user_id, invoice_payload="autoflow_topup:test",
        invoice_link="https://t.me/$test", xtr_amount=10, status="pending",
        expires_at=time_to_datetime(time.time() + 600),
    )
    payment = {
        "currency": "XTR",
        "invoice_payload": intent.invoice_payload,
        "telegram_payment_charge_id": "charge-unique",
        "total_amount": 10,
    }
    session = FakeSession([None, intent, user, wallet])
    assert await process_successful_payment(session, 99, payment) is True
    assert wallet.available_balance == Decimal("15.00")
    assert intent.status == "paid"
    assert len([item for item in session.added if isinstance(item, StarPayment)]) == 1

    duplicate_session = FakeSession([uuid.uuid4()])
    assert await process_successful_payment(duplicate_session, 99, payment) is False


@pytest.mark.asyncio
async def test_purchased_af_coins_cannot_be_withdrawn():
    from types import SimpleNamespace

    user_id = uuid.uuid4()
    user = User(id=user_id, telegram_id=100, first_name="Buyer", role="user")
    wallet = Wallet(
        user_id=user_id, purchased_balance=Decimal("500"), earned_balance=Decimal("0"),
        purchased_frozen_balance=0, earned_frozen_balance=0, total_earned=0, version=0,
    )
    with pytest.raises(HTTPException) as error:
        await create_withdrawal(
            FakeSession([wallet]), user,
            SimpleNamespace(amount=Decimal("15"), payout_method="manual", details="test"),
        )
    assert error.value.status_code == 402
    assert "продаж" in error.value.detail


def time_to_datetime(timestamp: float):
    from datetime import UTC, datetime

    return datetime.fromtimestamp(timestamp, tz=UTC)


def test_database_has_concurrent_purchase_guard():
    index = next(item for item in Deal.__table__.indexes if item.name == "uq_deals_open_listing")
    assert index.unique is True
    assert index.dialect_options["postgresql"]["where"] is not None


def auth_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/me",
            "headers": [],
            "query_string": b"",
            "scheme": "https",
            "server": ("autoflow.example", 443),
            "client": ("127.0.0.1", 12345),
        }
    )


class FakeAuthSession:
    def __init__(self, existing_user=None):
        self.existing_user = existing_user
        self.added = []
        self.commits = 0

    async def scalar(self, _query):
        return self.existing_user

    def begin_nested(self):
        return FakeTransaction()

    def add(self, value):
        if isinstance(value, User) and value.id is None:
            value.id = uuid.uuid4()
            self.existing_user = value
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_new_telegram_user_without_username_or_photo_is_created_with_wallet():
    token = "123456:TEST_TOKEN"
    init_data = signed_init_data(token, {"id": 501, "first_name": "Новый"})
    session = FakeAuthSession()
    request = auth_request()
    user = await get_current_user(
        request=request,
        x_telegram_init_data=init_data,
        x_dev_telegram_id=None,
        session=session,
        settings=Settings(bot_token=token, debug=False),
    )
    assert user.telegram_id == 501
    assert user.username is None
    assert user.photo_url is None
    assert user.role == "user"
    assert user.mini_app_last_active_at is not None
    assert request.state.telegram_user_id == 501
    assert any(isinstance(item, Wallet) and item.user_id == user.id for item in session.added)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_existing_admin_profile_is_refreshed_from_verified_init_data():
    token = "123456:TEST_TOKEN"
    existing = User(id=uuid.uuid4(), telegram_id=777, first_name="Старое", username="old", role="user")
    session = FakeAuthSession(existing)
    user = await get_current_user(
        request=auth_request(),
        x_telegram_init_data=signed_init_data(token, {"id": 777, "first_name": "Админ", "photo_url": "https://example.test/avatar.jpg"}),
        x_dev_telegram_id=None,
        session=session,
        settings=Settings(bot_token=token, debug=False, admin_id=777),
    )
    assert user is existing
    assert user.role == "admin"
    assert user.first_name == "Админ"
    assert user.username is None
    assert user.photo_url == "https://example.test/avatar.jpg"
    assert not any(isinstance(item, Wallet) for item in session.added)


@pytest.mark.asyncio
async def test_browser_without_init_data_is_rejected_in_production():
    with pytest.raises(HTTPException) as error:
        await get_current_user(
            request=auth_request(),
            x_telegram_init_data=None,
            x_dev_telegram_id=None,
            session=FakeAuthSession(),
            settings=Settings(bot_token="123456:TEST_TOKEN", debug=False, dev_telegram_id=999),
        )
    assert error.value.status_code == 401
    assert "Telegram" in error.value.detail
