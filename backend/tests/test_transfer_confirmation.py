"""Transfer/receipt use the real purchase, reservation and settlement services."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from test_chat_lifecycle_db import db as database_fixture
from app.models import DealEvent, Notification, User, Wallet, WalletTransaction
from app.services import complete_deal, purchase_listing, set_deal_status

db = database_fixture


async def paid(db):
    bridge, buyer, seller, listing = db
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    with bridge.session.begin():
        deal.buyer_game_id = "AB123456"
    return bridge, buyer, seller, listing, deal


def count(bridge, model, *conditions):
    return bridge.session.scalar(select(func.count()).select_from(model).where(*conditions))


@pytest.mark.asyncio
async def test_transfer_keeps_escrow_schedules_once_and_receipt_settles_once(db):
    bridge, buyer, seller, listing, deal = await paid(db)
    with bridge.session.begin():
        bw = bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        sw = bridge.session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
        before = count(bridge, WalletTransaction)
    for _ in range(3):
        await set_deal_status(bridge, seller, deal.id, "transfer_in_progress")
    with bridge.session.begin():
        assert deal.status == "transfer_in_progress"
        assert deal.buyer_transfer_reminder_status == "pending"
        assert deal.buyer_transfer_reminder_scheduled_at == deal.transfer_started_at
        assert (bw.available_balance, bw.frozen_balance, sw.available_balance) == (100, 100, 200)
        assert count(bridge, WalletTransaction) == before
        assert count(bridge, DealEvent, DealEvent.event_type == "seller_marked_transferred") == 1
        assert count(bridge, Notification, Notification.notification_type == "deal_status") == 1
    # Keep the existing 60-second safeguard; it cannot be bypassed by direct API.
    with pytest.raises(HTTPException) as error:
        await complete_deal(bridge, buyer, deal.id)
    assert error.value.status_code == 409
    with bridge.session.begin():
        bridge.session.refresh(deal)
        deal.transfer_started_at = datetime.now(UTC) - timedelta(seconds=61)
    for _ in range(3):
        await complete_deal(bridge, buyer, deal.id)
    with bridge.session.begin():
        assert deal.status == "completed"
        assert bw.frozen_balance == 0
        assert sw.available_balance == 200 + deal.seller_payout
        assert listing.status == "sold"
        assert count(bridge, WalletTransaction, WalletTransaction.transaction_type == "sale_income") == 1
        assert count(bridge, DealEvent, DealEvent.event_type == "buyer_confirmed") == 1
        assert count(bridge, DealEvent, DealEvent.event_type == "order_completed") == 1
        notices = list(bridge.session.scalars(select(Notification).where(Notification.notification_type == "deal_completed")))
        assert len(notices) == 1 and notices[0].delivery_status == "pending"
        assert str(deal.id) == notices[0].payload["deal_id"]
        assert "Покупатель подтвердил" in notices[0].body
    with pytest.raises(HTTPException) as error:
        await set_deal_status(bridge, seller, deal.id, "transfer_in_progress")
    assert error.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["paid", "seller_contacted", "transfer_in_progress"])
async def test_receipt_requires_persisted_seller_confirmation(db, status):
    bridge, buyer, _, _, deal = await paid(db)
    with bridge.session.begin():
        deal.status = status
        deal.transfer_started_at = None
    with pytest.raises(HTTPException) as error:
        await complete_deal(bridge, buyer, deal.id)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_http_success_and_replay_use_existing_endpoints(db):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.auth import get_current_user
    from app.database import get_session
    from app.routes import router

    bridge, buyer, seller, _, deal = await paid(db)
    deal_id = deal.id
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: bridge
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        app.dependency_overrides[get_current_user] = lambda: seller
        for _ in range(2):
            response = await client.post(f"/api/deals/{deal_id}/transfer")
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "transfer_in_progress"
        with bridge.session.begin():
            deal.transfer_started_at = datetime.now(UTC) - timedelta(seconds=61)
        app.dependency_overrides[get_current_user] = lambda: buyer
        for _ in range(2):
            response = await client.post(f"/api/deals/{deal_id}/confirm")
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "completed"
    with bridge.session.begin():
        assert count(bridge, WalletTransaction, WalletTransaction.transaction_type == "sale_income") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending_payment", "cancelled", "completed", "disputed"])
@pytest.mark.parametrize("action", ["transfer", "confirm"])
async def test_invalid_status_never_changes_money_or_notifies(db, status, action):
    bridge, buyer, seller, _, deal = await paid(db)
    with bridge.session.begin():
        deal.status = status
        before = count(bridge, WalletTransaction), count(bridge, Notification), count(bridge, DealEvent)
    with pytest.raises(HTTPException) as error:
        if action == "transfer":
            await set_deal_status(bridge, seller, deal.id, "transfer_in_progress")
        else:
            await complete_deal(bridge, buyer, deal.id)
    assert error.value.status_code == 409
    with bridge.session.begin():
        assert (count(bridge, WalletTransaction), count(bridge, Notification), count(bridge, DealEvent)) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["funding", "reservation", "wallet", "missing_id"])
async def test_unfunded_or_inconsistent_paid_deal_cannot_mark_transfer(db, invalid):
    bridge, _, seller, listing, deal = await paid(db)
    with bridge.session.begin():
        if invalid == "funding":
            deal.purchased_frozen_amount = 0
        elif invalid == "reservation":
            listing.reserved_by_deal_id = None
        elif invalid == "wallet":
            wallet = bridge.session.scalar(select(Wallet).where(Wallet.user_id == deal.buyer_id))
            wallet.purchased_frozen_balance = 0
        else:
            deal.buyer_game_id = None
    with pytest.raises(HTTPException) as error:
        await set_deal_status(bridge, seller, deal.id, "transfer_in_progress")
    assert error.value.status_code == 409
    with bridge.session.begin():
        assert count(bridge, DealEvent, DealEvent.event_type == "seller_marked_transferred") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_name,action", [
    ("buyer", "transfer"), ("outsider", "transfer"),
    ("seller", "confirm"), ("outsider", "confirm"),
])
async def test_http_role_check_cannot_be_bypassed(db, actor_name, action):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.auth import get_current_user
    from app.database import get_session
    from app.routes import router

    bridge, buyer, seller, _, deal = await paid(db)
    deal_id = deal.id
    actors = {"buyer": buyer, "seller": seller, "outsider": User(id=uuid.uuid4(), telegram_id=333)}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: actors[actor_name]
    app.dependency_overrides[get_session] = lambda: bridge
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/deals/{deal_id}/{action}")
    assert response.status_code == 403, response.text
