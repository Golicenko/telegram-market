import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.bot import HOW_IT_WORKS_TEXT, START_MENU_TEXT, bot_menu_payload
from app.models import Conversation, Deal, Listing, StarPayment, StarPaymentIntent, User, Wallet, WalletTransaction
from app.services import (
    complete_listing_payment_intent,
    create_listing_payment_intent,
    process_successful_payment,
    purchase_listing,
)


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeScalarResult:
    def __init__(self, values=()):
        self.values = list(values)

    def all(self):
        return self.values


class FakeSession:
    def __init__(self, scalar_values=(), get_values=None):
        self.scalar_values = list(scalar_values)
        self.get_values = dict(get_values or {})
        self.added = []

    def begin(self):
        return FakeTransaction()

    async def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _query):
        return FakeScalarResult()

    async def get(self, model, key):
        return self.get_values.get((model, key))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if hasattr(value, "id") and value.id is None:
                value.id = uuid.uuid4()


def make_user(telegram_id=1, role="user"):
    return User(id=uuid.uuid4(), telegram_id=telegram_id, first_name="User", role=role, bot_started=True)


def make_wallet(user_id, amount):
    return Wallet(
        user_id=user_id,
        purchased_balance=Decimal(str(amount)),
        earned_balance=Decimal("0"),
        purchased_frozen_balance=Decimal("0"),
        earned_frozen_balance=Decimal("0"),
        total_earned=Decimal("0"),
        version=0,
    )


def make_listing(seller_id, price="100", status="active"):
    return Listing(
        id=uuid.uuid4(), seller_id=seller_id, listing_type="regular", status=status,
        brand="BMW", model="M5", power_hp=600, max_speed_kph=300,
        description="Описание", price_af_coins=Decimal(price), views_count=0, pinned=False,
    )


@pytest.mark.asyncio
async def test_buyer_with_enough_af_coins_creates_one_protected_deal():
    buyer, seller = make_user(1), make_user(2)
    listing, wallet = make_listing(seller.id), make_wallet(buyer.id, 100)
    session = FakeSession([listing, None, wallet], {(User, seller.id): seller})

    deal, seller_telegram_id, created = await purchase_listing(session, buyer, listing.id)

    assert created is True
    assert deal.status == "paid"
    assert listing.status == "reserved"
    assert listing.reserved_by_deal_id == deal.id
    assert wallet.available_balance == Decimal("0.00")
    assert wallet.frozen_balance == Decimal("100.00")
    assert seller_telegram_id == seller.telegram_id
    conversation = next(item for item in session.added if isinstance(item, Conversation))
    assert deal.conversation_id == conversation.id
    assert {conversation.buyer_id, conversation.seller_id} == {buyer.id, seller.id}
    holds = [item for item in session.added if isinstance(item, WalletTransaction)]
    assert len(holds) == 1
    assert holds[0].external_reference == f"deal:{deal.id}:protection_hold"


@pytest.mark.asyncio
async def test_missing_thirty_af_coins_is_reported_by_backend():
    buyer, seller = make_user(1), make_user(2)
    listing, wallet = make_listing(seller.id), make_wallet(buyer.id, 70)
    session = FakeSession([listing, None, wallet])

    with pytest.raises(HTTPException) as error:
        await purchase_listing(session, buyer, listing.id)

    assert error.value.status_code == 402
    assert error.value.detail["missing_af_coins"] == "30.00"
    assert wallet.available_balance == Decimal("70")


@pytest.mark.asyncio
async def test_listing_invoice_can_be_exactly_three_xtr_below_normal_minimum():
    buyer, seller = make_user(1), make_user(2)
    listing, wallet = make_listing(seller.id), make_wallet(buyer.id, 97)
    created_amounts = []

    async def invoice_factory(amount, payload):
        created_amounts.append((amount, payload))
        return "https://t.me/$invoice"

    intent = StarPaymentIntent(id=uuid.uuid4(), user_id=buyer.id, invoice_payload="placeholder", xtr_amount=3, purpose="listing_checkout", context={}, listing_id=listing.id, seller_id=seller.id, listing_price_af_coins=Decimal("100"), available_balance_at_creation=Decimal("97"), missing_af_coins=Decimal("3"), checkout_status="pending", status="pending")
    session = FakeSession([listing, None, None, wallet, intent])

    result = await create_listing_payment_intent(session, buyer, listing.id, invoice_factory)

    assert result.xtr_amount == 3
    assert created_amounts[0][0] == 3
    assert result.missing_af_coins == Decimal("3.00")
    assert result.invoice_link == "https://t.me/$invoice"


@pytest.mark.asyncio
async def test_cancelled_invoice_does_not_change_balance_without_successful_payment():
    buyer, seller = make_user(1), make_user(2)
    listing, wallet = make_listing(seller.id), make_wallet(buyer.id, 97)

    async def invoice_factory(_amount, _payload):
        return "https://t.me/$cancelled-in-client"

    intent = StarPaymentIntent(
        id=uuid.uuid4(), user_id=buyer.id, invoice_payload="autoflow_topup:cancelled", xtr_amount=3,
        purpose="listing_checkout", context={}, listing_id=listing.id, seller_id=seller.id,
        listing_price_af_coins=Decimal("100"), available_balance_at_creation=Decimal("97"),
        missing_af_coins=Decimal("3"), checkout_status="pending", status="pending",
    )
    session = FakeSession([listing, None, None, wallet, intent])
    before = wallet.available_balance

    created = await create_listing_payment_intent(session, buyer, listing.id, invoice_factory)

    assert created.status == "pending"
    assert wallet.available_balance == before
    assert not any(isinstance(item, (StarPayment, WalletTransaction)) for item in session.added)


@pytest.mark.asyncio
async def test_successful_listing_topup_is_credited_once_even_below_ten_xtr():
    buyer = make_user(77)
    wallet = make_wallet(buyer.id, 97)
    intent = StarPaymentIntent(
        id=uuid.uuid4(), user_id=buyer.id, invoice_payload="autoflow_topup:listing", xtr_amount=3,
        purpose="listing_checkout", context={}, listing_id=uuid.uuid4(), seller_id=uuid.uuid4(),
        listing_price_af_coins=Decimal("100"), available_balance_at_creation=Decimal("97"),
        missing_af_coins=Decimal("3"), checkout_status="pending", status="pending",
    )
    payment = {"currency": "XTR", "invoice_payload": intent.invoice_payload, "telegram_payment_charge_id": "listing-charge", "total_amount": 3}
    session = FakeSession([None, intent, buyer, wallet])

    assert await process_successful_payment(session, buyer.telegram_id, payment) is True
    assert wallet.available_balance == Decimal("100.00")
    assert len([item for item in session.added if isinstance(item, StarPayment)]) == 1

    duplicate = FakeSession([uuid.uuid4()])
    assert await process_successful_payment(duplicate, buyer.telegram_id, payment) is False
    assert wallet.available_balance == Decimal("100.00")


@pytest.mark.asyncio
async def test_paid_intent_automatically_continues_purchase():
    buyer, seller = make_user(1), make_user(2)
    listing, wallet = make_listing(seller.id), make_wallet(buyer.id, 100)
    intent = StarPaymentIntent(
        id=uuid.uuid4(), user_id=buyer.id, invoice_payload="autoflow_topup:auto", xtr_amount=30,
        purpose="listing_checkout", context={}, listing_id=listing.id, seller_id=seller.id,
        listing_price_af_coins=Decimal("100"), available_balance_at_creation=Decimal("70"),
        missing_af_coins=Decimal("30"), checkout_status="pending", status="paid",
    )
    session = FakeSession([intent, listing, None, None, wallet], {(User, seller.id): seller})

    completed, deal, _seller_id = await complete_listing_payment_intent(session, buyer, intent.id)

    assert deal is not None
    assert completed.checkout_status == "completed"
    assert completed.deal_id == deal.id
    assert listing.status == "reserved"


@pytest.mark.asyncio
async def test_listing_bought_while_invoice_open_keeps_topped_up_coins():
    buyer, seller = make_user(1), make_user(2)
    listing, wallet = make_listing(seller.id, status="reserved"), make_wallet(buyer.id, 100)
    intent = StarPaymentIntent(
        id=uuid.uuid4(), user_id=buyer.id, invoice_payload="autoflow_topup:race", xtr_amount=30,
        purpose="listing_checkout", context={}, listing_id=listing.id, seller_id=seller.id,
        listing_price_af_coins=Decimal("100"), available_balance_at_creation=Decimal("70"),
        missing_af_coins=Decimal("30"), checkout_status="pending", status="paid",
    )
    session = FakeSession([intent, listing])

    completed, deal, _seller_id = await complete_listing_payment_intent(session, buyer, intent.id)

    assert deal is None
    assert completed.checkout_status == "listing_unavailable"
    assert wallet.available_balance == Decimal("100")


@pytest.mark.asyncio
async def test_owner_and_sold_listing_cannot_be_purchased():
    owner = make_user(1)
    own_listing = make_listing(owner.id)
    with pytest.raises(HTTPException) as own_error:
        await purchase_listing(FakeSession([own_listing]), owner, own_listing.id)
    assert own_error.value.status_code == 400

    buyer, seller = make_user(2), make_user(3)
    sold = make_listing(seller.id, status="sold")
    with pytest.raises(HTTPException) as sold_error:
        await purchase_listing(FakeSession([sold]), buyer, sold.id)
    assert sold_error.value.status_code == 409


@pytest.mark.asyncio
async def test_second_buyer_cannot_buy_listing_locked_by_first_buyer():
    first, second, seller = make_user(1), make_user(2), make_user(3)
    listing = make_listing(seller.id, status="reserved")
    existing = Deal(id=uuid.uuid4(), listing_id=listing.id, buyer_id=first.id, seller_id=seller.id, status="paid", price_af_coins=Decimal("100"), frozen_amount=Decimal("100"), purchased_frozen_amount=Decimal("100"), earned_frozen_amount=Decimal("0"), seller_payout=Decimal("70"), platform_commission=Decimal("30"))
    listing.reserved_by_deal_id = existing.id

    with pytest.raises(HTTPException) as error:
        await purchase_listing(FakeSession([listing, existing]), second, listing.id)
    assert error.value.status_code == 409


def test_start_and_how_it_works_menus_have_web_app_and_back_buttons():
    method, start = bot_menu_payload(False, "https://market.example", chat_id=1)
    assert method == "sendMessage"
    assert "Добро пожаловать" in START_MENU_TEXT
    assert start["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == "https://market.example"
    assert start["reply_markup"]["inline_keyboard"][1][0]["callback_data"] == "autoflow:how"

    method, details = bot_menu_payload(True, "https://market.example", chat_id=1, message_id=5)
    assert method == "editMessageText"
    assert "Как работает AutoFlow Market" in HOW_IT_WORKS_TEXT
    assert details["reply_markup"]["inline_keyboard"][1][0]["callback_data"] == "autoflow:start"


def test_start_payload_is_preserved_for_mini_app_deep_links():
    source = open("app/routes.py", encoding="utf-8").read()
    assert 'start_text.split(maxsplit=1)' in source
    assert 'start_payload=start_payload' in source
    _, payload = bot_menu_payload(False, "https://market.example", chat_id=1, start_payload="deal_123")
    assert payload["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == "https://market.example?start=deal_123"
