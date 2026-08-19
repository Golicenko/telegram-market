import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import routes
from app.models import Conversation, ConversationMessage, Deal, Listing, User
from app.schemas import ConversationMessageCreate, ListingCreate
from app.services import get_or_create_deal_conversation


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def __init__(self, deal, listing, conversation):
        self.deal = deal
        self.values = {
            (Listing, listing.id): listing,
            (Conversation, conversation.id): conversation,
        }
        self.added = []

    def begin(self):
        return FakeTransaction()

    async def scalar(self, _query):
        return self.deal

    async def get(self, model, key):
        return self.values.get((model, key))

    def add(self, value):
        self.added.append(value)


def test_one_conversation_index_is_unique_per_participant_pair():
    index = next(item for item in Conversation.__table__.indexes if item.name == "uq_conversations_participant_pair")
    assert index.unique is True
    expressions = " ".join(str(item) for item in index.expressions)
    assert "LEAST" in expressions and "GREATEST" in expressions


def test_message_idempotency_is_enforced_by_database():
    constraint = next(
        item for item in ConversationMessage.__table__.constraints
        if item.name == "uq_conversation_message_client_id"
    )
    assert [column.name for column in constraint.columns] == [
        "conversation_id", "sender_id", "client_message_id"
    ]


def test_client_message_id_is_required_and_long_messages_are_supported():
    message_id = uuid.uuid4()
    assert ConversationMessageCreate(body="x" * 4000, client_message_id=message_id).client_message_id == message_id
    with pytest.raises(ValidationError):
        ConversationMessageCreate(body="test")
    with pytest.raises(ValidationError):
        ConversationMessageCreate(body="x" * 4001, client_message_id=message_id)


def test_read_receipt_fields_are_server_backed():
    assert "is_read" in ConversationMessage.__table__.columns
    assert "read_at" in ConversationMessage.__table__.columns


def test_mobile_migration_drops_legacy_uniqueness_before_context_merge():
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0007_mobile_conversations.py"
    source = migration.read_text(encoding="utf-8")
    drop_position = source.index('op.drop_constraint("uq_conversation_listing_buyer"')
    context_move_position = source.index("UPDATE conversations c\n        SET listing_id")
    assert drop_position < context_move_position


@pytest.mark.asyncio
async def test_buyer_and_seller_reopen_the_same_deal_conversation_without_duplicate():
    buyer = User(id=uuid.uuid4(), telegram_id=10, first_name="Buyer", role="user")
    seller = User(id=uuid.uuid4(), telegram_id=11, first_name="Seller", role="user")
    listing = Listing(
        id=uuid.uuid4(), seller_id=seller.id, listing_type="regular", status="reserved",
        brand="BMW M5", model="", power_hp=600, max_speed_kph=300, description="Описание",
        price_af_coins=Decimal("100"), delivery_time_estimate="up_to_30m", views_count=0, pinned=False,
    )
    conversation = Conversation(id=uuid.uuid4(), listing_id=listing.id, buyer_id=buyer.id, seller_id=seller.id)
    deal = Deal(
        id=uuid.uuid4(), listing_id=listing.id, conversation_id=conversation.id,
        buyer_id=buyer.id, seller_id=seller.id, status="paid", price_af_coins=Decimal("100"),
        frozen_amount=Decimal("100"), purchased_frozen_amount=Decimal("100"),
        earned_frozen_amount=Decimal("0"), seller_payout=Decimal("70"), platform_commission=Decimal("30"),
    )
    session = FakeSession(deal, listing, conversation)

    assert await get_or_create_deal_conversation(session, buyer, deal.id) is conversation
    assert await get_or_create_deal_conversation(session, seller, deal.id) is conversation
    assert not session.added


def test_listing_create_accepts_new_vehicle_title_without_model_and_validates_delivery():
    payload = ListingCreate(
        brand="BMW M5", power_hp=600, max_speed_kph=300, description="Описание",
        price_af_coins=100, delivery_time_estimate="up_to_30m", image_urls=["/uploads/car.jpg"],
    )
    assert payload.model is None
    assert payload.delivery_time_estimate == "up_to_30m"
    with pytest.raises(ValidationError):
        ListingCreate(
            brand="BMW M5", power_hp=600, max_speed_kph=300, description="Описание",
            price_af_coins=99, delivery_time_estimate="tomorrow", image_urls=["/uploads/car.jpg"],
        )


def test_deal_chat_delivery_migration_is_non_destructive_and_backfills_links():
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0012_deal_conversation_delivery_time.py"
    source = migration.read_text(encoding="utf-8")
    assert "SET conversation_id = conversation.id" in source
    assert "delivery_time_estimate" in source
    assert "drop_table" not in source
    assert "DELETE FROM" not in source.upper()


def test_frontend_exposes_deal_chat_and_removes_model_filter():
    root = Path(__file__).parents[2]
    html = (root / "webapp" / "index.html").read_text(encoding="utf-8")
    script = (root / "webapp" / "js" / "app.js").read_text(encoding="utf-8")
    styles = (root / "webapp" / "css" / "style.css").read_text(encoding="utf-8")
    assert 'chat.dataset.openDealChat = deal.id' in script
    assert '/deals/${dealId}/conversation' in script
    assert 'id="priceMinFilter"' in html and 'id="priceMaxFilter"' in html
    assert 'id="modelFilter"' not in html and 'name="model"' not in html
    assert "overflow-x: hidden" in styles
    assert "--chat-viewport-height" in styles
    assert "visualViewport" in script


class EmptyScalarResult:
    def all(self):
        return []


class ListingQuerySession:
    def __init__(self):
        self.statement = None

    async def execute(self, _statement):
        return type("Result", (), {"rowcount": 0})()

    async def scalars(self, statement):
        self.statement = statement
        return EmptyScalarResult()


@pytest.mark.asyncio
async def test_listing_api_combines_automobile_and_decimal_price_range():
    session = ListingQuerySession()
    result = await routes.list_listings(
        listing_type="regular",
        brand="BMW M5",
        min_price=Decimal("50.25"),
        max_price=Decimal("200.75"),
        min_power=None,
        min_speed=None,
        session=session,
    )
    compiled = str(session.statement)
    assert result == []
    assert "listings.brand" in compiled
    assert "listings.price_af_coins >=" in compiled
    assert "listings.price_af_coins <=" in compiled


@pytest.mark.asyncio
async def test_listing_api_rejects_reversed_price_range():
    with pytest.raises(HTTPException) as error:
        await routes.list_listings(
            listing_type="regular", brand=None, min_price=Decimal("201"), max_price=Decimal("200"),
            min_power=None, min_speed=None, session=ListingQuerySession(),
        )
    assert getattr(error.value, "status_code", None) == 422


def test_read_state_and_completed_chat_are_kept_on_backend():
    root = Path(__file__).parents[1]
    routes_source = (root / "app" / "routes.py").read_text(encoding="utf-8")
    services_source = (root / "app" / "services.py").read_text(encoding="utf-8")
    assert "ConversationMessage.is_read.is_(False)" in routes_source
    assert "is_read=True," in routes_source and "read_at=datetime.now(UTC)" in routes_source
    assert "conversation.buyer_hidden_at = None" in services_source
    assert "conversation.seller_hidden_at = None" in services_source
    assert "delete(Conversation)" not in routes_source + services_source
