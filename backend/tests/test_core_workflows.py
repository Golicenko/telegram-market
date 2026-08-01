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

from app.auth import require_admin, validate_init_data
from app.models import Deal, Listing, StarPayment, StarPaymentIntent, User, Wallet, WalletTransaction
from app.schemas import ListingCreate
from app.services import (
    charge_listing_promotion,
    create_listing,
    process_successful_payment,
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


def test_listing_requires_exactly_one_image():
    values = {
        "brand": "BMW",
        "model": "M5",
        "power_hp": 600,
        "max_speed_kph": 300,
        "description": "Описание",
        "price_af_coins": 100,
    }
    assert len(ListingCreate(**values, image_urls=["/uploads/one.jpg"]).image_urls) == 1
    with pytest.raises(ValidationError):
        ListingCreate(**values, image_urls=[])
    with pytest.raises(ValidationError):
        ListingCreate(**values, image_urls=["one", "two"])


def test_server_commission_is_single_70_30_formula():
    payout, commission = settlement_amounts(Decimal("101.00"))
    assert payout == Decimal("70.70")
    assert commission == Decimal("30.30")
    assert payout + commission == Decimal("101.00")


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
        image_urls=["/uploads/car.jpg"],
    )
    session = FakeSession()
    first = await create_listing(session, seller, payload, listing_type="regular")
    second = await create_listing(session, seller, payload, listing_type="regular")
    assert first.status == second.status == "active"
    assert not any(isinstance(item, WalletTransaction) for item in session.added)


@pytest.mark.asyncio
async def test_promotion_costs_15_and_retry_does_not_charge_twice():
    user_id = uuid.uuid4()
    user = User(id=user_id, telegram_id=8, first_name="Seller", role="user")
    wallet = Wallet(user_id=user_id, available_balance=Decimal("100"), frozen_balance=0, total_earned=0, version=0)
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
    wallet = Wallet(user_id=user_id, available_balance=Decimal("5"), frozen_balance=0, total_earned=0, version=0)
    intent = StarPaymentIntent(
        id=uuid.uuid4(), user_id=user_id, invoice_payload="autoflow_topup:test",
        invoice_link="https://t.me/$test", xtr_amount=100, status="pending",
        expires_at=time_to_datetime(time.time() + 600),
    )
    payment = {
        "currency": "XTR",
        "invoice_payload": intent.invoice_payload,
        "telegram_payment_charge_id": "charge-unique",
        "total_amount": 100,
    }
    session = FakeSession([None, intent, user, wallet])
    assert await process_successful_payment(session, 99, payment) is True
    assert wallet.available_balance == Decimal("105.00")
    assert intent.status == "paid"
    assert len([item for item in session.added if isinstance(item, StarPayment)]) == 1

    duplicate_session = FakeSession([uuid.uuid4()])
    assert await process_successful_payment(duplicate_session, 99, payment) is False


def time_to_datetime(timestamp: float):
    from datetime import UTC, datetime

    return datetime.fromtimestamp(timestamp, tz=UTC)


def test_database_has_concurrent_purchase_guard():
    index = next(item for item in Deal.__table__.indexes if item.name == "uq_deals_open_listing")
    assert index.unique is True
    assert index.dialect_options["postgresql"]["where"] is not None
