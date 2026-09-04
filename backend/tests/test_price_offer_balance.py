import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models import Conversation, ConversationMessage, Listing, Notification, PriceOffer, User, Wallet
from app.services import create_price_offer


class Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class OfferSession:
    def __init__(self, conversation, wallet, recipient):
        self.conversation = conversation
        self.wallet = wallet
        self.recipient = recipient
        self.added = []
        self.statements = []

    def begin(self):
        return Transaction()

    async def scalar(self, statement):
        self.statements.append(statement)
        entity = statement.column_descriptions[0].get("entity")
        if entity is Conversation:
            return self.conversation
        if entity is Wallet:
            return self.wallet
        if entity is PriceOffer:
            return None
        raise AssertionError(f"Unexpected scalar query: {statement}")

    async def get(self, model, key):
        if model is User and key == self.recipient.id:
            return self.recipient
        return None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid.uuid4()


def offer_fixture(balance: Decimal):
    buyer = User(id=uuid.uuid4(), telegram_id=101, first_name="Buyer", role="user")
    seller = User(id=uuid.uuid4(), telegram_id=202, first_name="Seller", role="user")
    listing = Listing(
        id=uuid.uuid4(), seller_id=seller.id, listing_type="regular", status="active",
        brand="Car", model="", power_hp=1, max_speed_kph=1, description="Description",
        price_af_coins=Decimal("100"), delivery_time_estimate="up_to_30m", views_count=0, pinned=False,
    )
    conversation = Conversation(
        id=uuid.uuid4(), listing_id=listing.id, buyer_id=buyer.id, seller_id=seller.id,
    )
    wallet = Wallet(
        id=uuid.uuid4(), user_id=buyer.id, purchased_balance=balance, earned_balance=Decimal("0"),
        purchased_frozen_balance=Decimal("0"), earned_frozen_balance=Decimal("0"),
        total_earned=Decimal("0"), version=0,
    )
    return buyer, seller, conversation, wallet


@pytest.mark.asyncio
@pytest.mark.parametrize("balance", [Decimal("0"), Decimal("50")])
async def test_price_offer_above_available_balance_is_rejected_without_side_effects(balance):
    buyer, seller, conversation, wallet = offer_fixture(balance)
    session = OfferSession(conversation, wallet, seller)

    with pytest.raises(HTTPException) as captured:
        await create_price_offer(session, buyer, conversation.id, Decimal("75"))

    assert captured.value.status_code == 402
    assert captured.value.detail == {
        "code": "insufficient_af_coins",
        "message": "Недостаточно AF Coins",
        "available_af_coins": f"{balance:.2f}",
        "required_af_coins": "75.00",
        "missing_af_coins": f"{Decimal('75') - balance:.2f}",
    }
    assert wallet.available_balance == balance
    assert not [item for item in session.added if isinstance(item, (PriceOffer, ConversationMessage, Notification))]


@pytest.mark.asyncio
@pytest.mark.parametrize("balance", [Decimal("75"), Decimal("100")])
async def test_affordable_price_offer_is_structured_and_does_not_debit_wallet(balance):
    buyer, seller, conversation, wallet = offer_fixture(balance)
    session = OfferSession(conversation, wallet, seller)

    offer, recipient = await create_price_offer(session, buyer, conversation.id, Decimal("75"))

    assert recipient is seller
    assert offer.amount_af_coins == Decimal("75.00")
    assert wallet.available_balance == balance
    assert wallet.frozen_balance == Decimal("0")
    wallet_query = next(statement for statement in session.statements if statement.column_descriptions[0].get("entity") is Wallet)
    assert "FOR UPDATE" in str(wallet_query)
    messages = [item for item in session.added if isinstance(item, ConversationMessage)]
    assert len(messages) == 1
    assert messages[0].message_type == "offer"
    assert messages[0].price_offer_id == offer.id


@pytest.mark.asyncio
async def test_missing_wallet_is_treated_as_zero_balance():
    buyer, seller, conversation, _wallet = offer_fixture(Decimal("0"))
    session = OfferSession(conversation, None, seller)

    with pytest.raises(HTTPException) as captured:
        await create_price_offer(session, buyer, conversation.id, Decimal("1"))

    assert captured.value.status_code == 402
    assert captured.value.detail["available_af_coins"] == "0.00"
    assert captured.value.detail["missing_af_coins"] == "1.00"
