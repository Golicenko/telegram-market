import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import routes
from app import bot
from app.models import Conversation, ConversationMessage, Deal, Listing, PriceOffer, User
from app.schemas import ConversationMessageCreate, ListingCreate, PriceOfferCreate
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


def test_only_permanent_dialog_is_unique_per_participant_pair():
    index = next(item for item in Conversation.__table__.indexes if item.name == "uq_conversations_dialog_participant_pair")
    assert index.unique is True
    expressions = " ".join(str(item) for item in index.expressions)
    assert "LEAST" in expressions and "GREATEST" in expressions
    assert "conversation_type = 'dialog'" in str(index.dialect_options["postgresql"]["where"])
    assert "conversation_type" in Conversation.__table__.columns
    assert "archived_at" in Conversation.__table__.columns


def test_message_idempotency_is_enforced_by_database():
    constraint = next(
        item for item in ConversationMessage.__table__.constraints
        if item.name == "uq_conversation_message_client_id"
    )
    assert [column.name for column in constraint.columns] == [
        "conversation_id", "sender_id", "client_message_id"
    ]
    assert "deal_id" in ConversationMessage.__table__.columns
    assert "price_offer_id" in ConversationMessage.__table__.columns


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
    conversation = Conversation(
        id=uuid.uuid4(), listing_id=listing.id, buyer_id=buyer.id, seller_id=seller.id,
        conversation_type="deal",
    )
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
    assert 'chat.dataset.openDealThread = thread.id' in script
    assert "renderDeals(profile.deal_threads || [])" in script
    assert 'details.conversation_type === "deal"' in script
    assert '/deals/${dealId}/conversation' in script
    assert 'id="priceMinFilter"' in html and 'id="priceMaxFilter"' in html
    assert 'id="modelFilter"' not in html and 'name="model"' not in html
    assert "overflow-x: hidden" in styles
    assert "--chat-viewport-height" in styles
    assert "visualViewport" in script
    assert "deal_id: dealId" in script
    assert "openDealConversation(message.deal_id)" in script
    assert ".promotion-choice-modal .publish-button,.promotion-choice-modal .ghost-button" in styles


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


def test_ordinary_dialogs_and_each_deal_use_separate_message_scopes():
    root = Path(__file__).parents[1]
    routes_source = (root / "app" / "routes.py").read_text(encoding="utf-8")
    services_source = (root / "app" / "services.py").read_text(encoding="utf-8")
    assert 'message_scope="deal"' in routes_source
    assert "ConversationMessage.deal_id.is_(None)" in routes_source
    assert "ConversationMessage.deal_id == deal.id" in routes_source
    assert 'deal.status not in {"completed", "cancelled"}' in services_source
    assert "delete(ConversationMessage)" not in routes_source + services_source
    assert 'Conversation.conversation_type == "dialog"' in routes_source
    assert 'Conversation.conversation_type == "deal"' in services_source
    migration = (root / "migrations" / "versions" / "0033_separate_dialog_deal_threads.py").read_text(encoding="utf-8")
    assert "UPDATE conversation_messages SET conversation_id" in migration
    assert "DELETE FROM" not in migration.upper()


def test_profile_keeps_completed_deals_and_platform_commission_is_presented_positive():
    root = Path(__file__).parents[1]
    routes_source = (root / "app" / "routes.py").read_text(encoding="utf-8")
    schemas_source = (root / "app" / "schemas.py").read_text(encoding="utf-8")
    assert "deals: list[DealOut]" in schemas_source
    assert 'Deal.status == "completed"' in routes_source
    assert "func.sum(Deal.platform_commission)" in routes_source
    assert '"platform_commission_af_coins": Decimal(commission or 0)' in routes_source


class FinancialSummaryResult:
    def one(self):
        return 3, Decimal("90")


class FinancialSummarySession:
    async def execute(self, statement):
        self.statement = statement
        return FinancialSummaryResult()


@pytest.mark.asyncio
async def test_admin_platform_summary_reports_commission_as_positive_platform_income():
    session = FinancialSummarySession()
    result = await routes.admin_platform_financial_summary(
        admin=User(id=uuid.uuid4(), telegram_id=1, first_name="Admin", role="admin"),
        session=session,
    )
    assert result == {
        "completed_deals": 3,
        "platform_commission_af_coins": Decimal("90"),
    }
    assert "deals.status" in str(session.statement)


def test_price_offer_accepts_one_af_and_is_database_backed():
    assert PriceOfferCreate(amount_af_coins=Decimal("1")).amount_af_coins == Decimal("1")
    check = next(item for item in PriceOffer.__table__.constraints if item.name == "ck_price_offers_min_price")
    assert "amount_af_coins >= 1" in str(check.sqltext)
    assert "listing_id" in PriceOffer.__table__.columns


def test_offer_listing_migration_is_additive_and_backfills_existing_rows():
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0026_price_offer_listing.py"
    source = migration.read_text(encoding="utf-8")
    assert "SET listing_id = conversation.listing_id" in source
    assert 'op.alter_column("price_offers", "listing_id", nullable=False)' in source
    assert "drop_table" not in source
    assert "DELETE FROM" not in source.upper()


def test_offer_notification_uses_exact_ids_and_actions():
    listing_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    offer_id = str(uuid.uuid4())
    payload = bot.price_offer_notification_payload(
        123,
        listing_id=listing_id,
        conversation_id=conversation_id,
        offer_id=offer_id,
        amount_af_coins="1.00",
        public_url="https://market.example",
    )
    keyboard = payload["reply_markup"]["inline_keyboard"]
    assert keyboard[0][0]["callback_data"] == f"offer:accept:{offer_id}"
    assert keyboard[0][1]["callback_data"] == f"offer:reject:{offer_id}"
    assert conversation_id in keyboard[1][0]["web_app"]["url"]
    assert listing_id in keyboard[1][0]["web_app"]["url"]
    assert "1.00 AF Coins" in payload["text"]


def test_listing_details_is_a_real_view_and_draft_offer_has_listing_endpoint():
    root = Path(__file__).parents[2]
    html = (root / "webapp" / "index.html").read_text(encoding="utf-8")
    script = (root / "webapp" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'data-view="listing-detail"' in html
    assert "listingDetailsModal" not in script
    assert "`/conversations/listing/${sourceListingId}/offers`" in script
    assert "conversationId ? `/conversations/${conversationId}/offers`" in script


def test_price_offer_is_rendered_as_a_structured_chat_card_with_topup_recovery():
    root = Path(__file__).parents[2]
    script = (root / "webapp" / "js" / "app.js").read_text(encoding="utf-8")
    styles = (root / "webapp" / "css" / "style.css").read_text(encoding="utf-8")
    migration = (
        root / "backend" / "migrations" / "versions" / "0031_price_offer_message_link.py"
    ).read_text(encoding="utf-8")
    assert 'message.message_type === "offer"' in script
    assert 'item.id) === String(message.price_offer_id' in script
    assert 'heading.textContent = "💰 Предложение цены"' in script
    assert 'status.textContent = "❌ Предложение отклонено"' in script
    assert 'status.textContent = `✅ Предложение принято — ${formatNumber(amount)} AF`' in script
    assert 'flow.kind === "offer-topup"' in script
    assert 'elements.purchaseModalAction.textContent = `Пополнить ${topupAmount} AF`' in script
    assert ".message.is-offer" in styles
    assert "price_offer_id" in migration
    assert "drop_table" not in migration
