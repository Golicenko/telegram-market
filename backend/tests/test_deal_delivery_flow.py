import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from app.bot import deal_purchase_notification_payload
from app.models import Conversation, ConversationMessage, Deal, Listing, User
from app.services import save_deal_delivery_details, set_deal_status
from app import routes


class Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class Session:
    def __init__(self, deal, listing, conversation):
        self.deal = deal
        self.values = {
            (Listing, listing.id): listing,
            (Conversation, conversation.id): conversation,
        }
        self.added = []

    def begin(self):
        return Transaction()

    async def scalar(self, _query):
        return self.deal

    async def get(self, model, key):
        return self.values.get((model, key))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def fixture():
    buyer = User(id=uuid.uuid4(), telegram_id=101, first_name="Buyer", role="user")
    seller = User(id=uuid.uuid4(), telegram_id=202, first_name="Seller", role="user")
    listing = Listing(
        id=uuid.uuid4(), seller_id=seller.id, listing_type="regular", status="reserved",
        brand="Any", model="Car", power_hp=1, max_speed_kph=1,
        description="Car", price_af_coins=Decimal("100"), views_count=0, pinned=False,
    )
    conversation = Conversation(
        id=uuid.uuid4(), listing_id=listing.id, buyer_id=buyer.id, seller_id=seller.id
    )
    deal = Deal(
        id=uuid.uuid4(), listing_id=listing.id, conversation_id=conversation.id,
        buyer_id=buyer.id, seller_id=seller.id, status="paid",
        price_af_coins=Decimal("100"), frozen_amount=Decimal("100"),
        purchased_frozen_amount=Decimal("100"), earned_frozen_amount=Decimal("0"),
        seller_payout=Decimal("70"), platform_commission=Decimal("30"),
    )
    return buyer, seller, listing, conversation, deal


@pytest.mark.asyncio
async def test_delivery_details_are_persisted_on_exact_deal_and_message_is_idempotent():
    buyer, _seller, listing, conversation, deal = fixture()
    session = Session(deal, listing, conversation)

    result = await save_deal_delivery_details(
        session, buyer, deal.id, " 12345678 ", "scheduled", "19:00"
    )

    assert result.buyer_game_id == "12345678"
    assert result.preferred_delivery_time == "Сегодня, 19:00"
    messages = [item for item in session.added if isinstance(item, ConversationMessage)]
    assert len(messages) == 1
    assert messages[0].message_type == "system"
    assert "ID покупателя: 12345678" in messages[0].body

    retry = Session(deal, listing, conversation)
    await save_deal_delivery_details(retry, buyer, deal.id, "12345678", "scheduled", "19:00")
    assert not [item for item in retry.added if isinstance(item, ConversationMessage)]


@pytest.mark.asyncio
async def test_only_exact_deal_buyer_can_store_delivery_details():
    _buyer, _seller, listing, conversation, deal = fixture()
    outsider = User(id=uuid.uuid4(), telegram_id=303, first_name="Other", role="user")
    with pytest.raises(HTTPException) as error:
        await save_deal_delivery_details(
            Session(deal, listing, conversation), outsider, deal.id, "123", "now", None
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_seller_cannot_mark_transfer_before_buyer_sends_delivery_details():
    _buyer, seller, listing, conversation, deal = fixture()
    with pytest.raises(HTTPException) as error:
        await set_deal_status(
            Session(deal, listing, conversation), seller, deal.id, "transfer_in_progress"
        )
    assert error.value.status_code == 409
    assert deal.status == "paid"
    assert "игровой ID" in error.value.detail


def test_seller_notification_opens_the_exact_deal():
    deal_id = str(uuid.uuid4())
    payload = deal_purchase_notification_payload(
        202, deal_id=deal_id, public_url="https://market.example/app"
    )
    button_url = payload["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"]
    assert parse_qs(urlparse(button_url).query)["deal_id"] == [deal_id]
    assert payload["text"].count("Вашу машину купили") == 1


@pytest.mark.asyncio
async def test_repeated_notification_dispatch_sends_only_once_per_deal(monkeypatch):
    _buyer, seller, listing, conversation, deal = fixture()
    seller.bot_started = True
    deal.seller_purchase_notification_status = "pending"

    class NotificationSession(Session):
        async def get(self, model, key):
            if model is User and key == seller.id:
                return seller
            return await super().get(model, key)

    monkeypatch.setattr(routes, "SessionLocal", lambda: NotificationSession(deal, listing, conversation))
    sent = []

    async def fake_send(telegram_id, *, deal_id):
        sent.append((telegram_id, deal_id))
        return True

    monkeypatch.setattr(routes, "send_deal_purchase_notification", fake_send)
    await routes.notify_deal_purchase_seller(deal.id)
    await routes.notify_deal_purchase_seller(deal.id)

    assert sent == [(seller.telegram_id, str(deal.id))]
    assert deal.seller_purchase_notification_status == "sent"


def test_migration_preserves_old_deals_and_enables_pending_for_new_deals():
    source = (Path(__file__).parents[1] / "migrations" / "versions" / "0020_deal_delivery_flow.py").read_text(encoding="utf-8")
    assert 'server_default="sent"' in source
    assert 'server_default="pending"' in source
    assert "drop_table" not in source
