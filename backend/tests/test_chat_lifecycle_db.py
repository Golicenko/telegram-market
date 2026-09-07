"""Database-backed service tests. SQLite checks persistence/rollback, not PG locking."""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, func
from sqlalchemy.schema import CreateTable
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.models import User, Listing, Conversation, ConversationMessage, Deal, DealEvent, PriceOffer, Wallet, WalletTransaction, Notification
from app.chat_access import active_thread_clause, require_active_chat
from app.services import create_listing_price_offer, respond_price_offer, get_or_create_conversation, send_conversation_message, purchase_listing, complete_deal, get_or_create_deal_conversation


@compiles(JSONB, "sqlite")
def sqlite_json(type_, compiler, **kw):
    return "JSON"


class DB:
    def __init__(self, session):
        self.session = session

    @asynccontextmanager
    async def begin(self):
        with self.session.begin():
            yield

    async def scalar(self, query):
        return self.session.scalar(query)

    async def scalars(self, query):
        return self.session.scalars(query)

    async def execute(self, query):
        return self.session.execute(query)

    async def get(self, model, key):
        return self.session.get(model, key)

    async def flush(self):
        self.session.flush()

    def add(self, value):
        self.session.add(value)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    # Table constraints are real; PostgreSQL expression indexes are checked separately.
    models = (User, Listing, Conversation, ConversationMessage, Deal, DealEvent, PriceOffer, Wallet, WalletTransaction, Notification)
    with engine.begin() as connection:
        for model in models:
            connection.execute(CreateTable(model.__table__))
    session = Session(engine, expire_on_commit=False)
    buyer = User(id=uuid.uuid4(), telegram_id=1, first_name="Buyer", role="user")
    seller = User(id=uuid.uuid4(), telegram_id=2, first_name="Seller", role="user")
    listing = Listing(id=uuid.uuid4(), seller_id=seller.id, listing_type="regular", status="active",
                      brand="Car", model="", power_hp=1, max_speed_kph=1, description="Car", price_af_coins=100)
    with session.begin():
        session.add_all([buyer, seller, listing])
        for user in (buyer, seller):
            session.add(Wallet(user_id=user.id, purchased_balance=200, earned_balance=0,
                               purchased_frozen_balance=0, earned_frozen_balance=0, total_earned=0, version=0))
    yield DB(session), buyer, seller, listing
    session.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_rejected_offer_closes_thread_and_next_offer_gets_new_thread(db):
    bridge, buyer, seller, listing = db
    offer, _ = await create_listing_price_offer(bridge, buyer, listing.id, Decimal(80))
    first_thread = offer.conversation_id
    await respond_price_offer(bridge, seller, offer.id, False)
    with bridge.session.begin():
        assert offer.status == "rejected"
        assert bridge.session.scalar(select(func.count()).select_from(Conversation).where(active_thread_clause())) == 0
        assert bridge.session.get(Conversation, first_thread).archived_at is not None
    second, _ = await create_listing_price_offer(bridge, buyer, listing.id, Decimal(75))
    assert second.conversation_id != first_thread


@pytest.mark.asyncio
async def test_failed_offer_rolls_back_entire_thread(db):
    bridge, buyer, seller, listing = db
    with pytest.raises(HTTPException) as error:
        await create_listing_price_offer(bridge, buyer, listing.id, Decimal(500))
    assert error.value.status_code == 402
    with bridge.session.begin():
        for model in (Conversation, PriceOffer, ConversationMessage, Notification):
            assert bridge.session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.asyncio
async def test_dialog_offer_purchase_completion_and_independent_second_car(db):
    bridge, buyer, seller, listing = db
    with bridge.session.begin():
        assert bridge.session.get(Listing, listing.id)
        assert bridge.session.scalar(select(func.count()).select_from(Conversation)) == 0
    dialog, _, _ = await get_or_create_conversation(bridge, buyer, listing.id)
    await send_conversation_message(bridge, buyer, dialog.id, "Hello", uuid.uuid4())
    assert dialog.conversation_type == "dialog"
    offer, _ = await create_listing_price_offer(bridge, buyer, listing.id, Decimal(80))
    await respond_price_offer(bridge, seller, offer.id, True)
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    assert deal.conversation_id == offer.conversation_id != dialog.id
    assert deal.price_af_coins == Decimal(80)
    with bridge.session.begin():
        deal.status = "transfer_in_progress"
        deal.transfer_started_at = datetime.now(UTC) - timedelta(minutes=2)
    await complete_deal(bridge, buyer, deal.id)
    with bridge.session.begin():
        thread = bridge.session.get(Conversation, deal.conversation_id)
        assert thread.archived_at is not None
        assert bridge.session.get(Conversation, dialog.id).archived_at is None
        assert bridge.session.scalar(select(func.count()).select_from(Conversation).where(active_thread_clause())) == 0
    await send_conversation_message(bridge, buyer, dialog.id, "Still here", uuid.uuid4())
    with bridge.session.begin():
        second = Listing(id=uuid.uuid4(), seller_id=seller.id, listing_type="regular", status="active",
                         brand="Second", model="", power_hp=1, max_speed_kph=1, description="Car", price_af_coins=50)
        bridge.session.add(second)
    second_deal, _, _ = await purchase_listing(bridge, buyer, second.id)
    assert second_deal.conversation_id not in {dialog.id, deal.conversation_id}
    with pytest.raises(HTTPException):
        await send_conversation_message(bridge, buyer, deal.conversation_id, "closed", uuid.uuid4(), deal.id)


@pytest.mark.asyncio
async def test_empty_thread_and_outsider_cannot_read_or_send(db):
    bridge, buyer, seller, listing = db
    with bridge.session.begin():
        empty = Conversation(id=uuid.uuid4(), listing_id=listing.id, buyer_id=buyer.id,
                             seller_id=seller.id, conversation_type="deal")
        bridge.session.add(empty)
    with pytest.raises(HTTPException) as error:
        await send_conversation_message(bridge, buyer, empty.id, "invalid", uuid.uuid4())
    assert error.value.status_code == 409
    stranger = User(id=uuid.uuid4(), telegram_id=3, first_name="Other")
    with pytest.raises(HTTPException) as error:
        async with bridge.begin():
            await require_active_chat(bridge, empty, stranger)
    assert error.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["rejected", "expired", "cancelled", "countered"])
async def test_terminal_offer_denies_access_even_without_archival(db, status):
    bridge, buyer, seller, listing = db
    offer, _ = await create_listing_price_offer(bridge, buyer, listing.id, Decimal(80))
    with bridge.session.begin():
        offer.status = status
        thread = bridge.session.get(Conversation, offer.conversation_id)
    with pytest.raises(HTTPException) as error:
        async with bridge.begin():
            await require_active_chat(bridge, thread, buyer)
    assert error.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending_payment", "completed", "cancelled"])
async def test_direct_http_cannot_reopen_or_send_to_ineligible_deal(db, status):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.routes import router
    from app.auth import get_current_user
    from app.database import get_session

    bridge, buyer, seller, listing = db
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    deal_id, conversation_id = deal.id, deal.conversation_id
    with bridge.session.begin():
        deal.status = status
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: buyer

    async def test_session():
        try:
            yield bridge
        finally:
            bridge.session.rollback()

    app.dependency_overrides[get_session] = test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/deals/{deal_id}/conversation")
        assert response.status_code == 409
        response = await client.get(f"/api/conversations/{conversation_id}/messages")
        assert response.status_code == 409
        response = await client.post(f"/api/conversations/{conversation_id}/messages", json={
            "body": "Cannot send", "client_message_id": str(uuid.uuid4()), "deal_id": str(deal_id),
        })
        assert response.status_code == 409
