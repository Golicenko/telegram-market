"""Persistence/rollback and HTTP coverage; SQLite does not emulate PG row locks."""
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI, HTTPException, BackgroundTasks
from sqlalchemy import select, func

from test_chat_lifecycle_db import db
from test_deal_lifecycle_control import control
from app.models import Deal, DealEvent, Wallet, WalletTransaction, Notification, ConversationMessage
from app.services import (purchase_listing, save_deal_delivery_details, set_deal_status,
    auto_cancel_undelivered_deal, send_conversation_message, send_admin_deal_message, create_deal_support_case)
from app.schemas import SupportReplyCreate
from app.deal_lifecycle import admin_nonfinancial_action
from app.message_notifications import claim_delivery
from app import routes
from app.auth import get_current_user
from app.database import get_session


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


@pytest.mark.asyncio
async def test_id_only_keeps_deadline_across_messages_and_restart(db):
    bridge, buyer, seller, listing = db
    before = datetime.now(UTC)
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    deadline = deal.seller_delivery_deadline
    assert before + timedelta(hours=24) <= deadline <= datetime.now(UTC) + timedelta(hours=24)
    await save_deal_delivery_details(bridge, buyer, deal.id, "AB123456")
    await send_conversation_message(bridge, seller, deal.conversation_id, "Скоро передам", uuid.uuid4(), deal.id)
    await save_deal_delivery_details(bridge, buyer, deal.id, "xy987654")
    assert deal.seller_delivery_deadline == deadline
    deal_id = deal.id
    bridge.session.expire_all()
    with bridge.session.begin():
        restored = bridge.session.get(Deal, deal_id)
        assert restored.buyer_game_id == "xy987654"
        assert restored.buyer_server is None and restored.preferred_delivery_time is None
        assert utc(restored.seller_delivery_deadline) == deadline
    assert not await auto_cancel_undelivered_deal(bridge, deal_id, now=deadline - timedelta(seconds=1))
    assert await auto_cancel_undelivered_deal(bridge, deal_id, now=deadline)
    assert not await auto_cancel_undelivered_deal(bridge, deal_id, now=deadline + timedelta(days=2))
    with bridge.session.begin():
        assert restored.status == "cancelled" and restored.cancellation_reason == "delivery_timeout"
        buyer_wallet = bridge.session.scalar(select(Wallet).where(Wallet.user_id == restored.buyer_id))
        seller_wallet = bridge.session.scalar(select(Wallet).where(Wallet.user_id == restored.seller_id))
        assert buyer_wallet.available_balance == 200 and buyer_wallet.frozen_balance == 0
        assert seller_wallet.available_balance == 200
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction).where(
            WalletTransaction.external_reference == f"delivery-timeout-refund:{deal_id}")) == 1
        notices = list(bridge.session.scalars(select(Notification).where(Notification.notification_type == "deal_delivery_timeout")))
        assert len(notices) == 2 and all(n.delivery_status == "pending" for n in notices)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["transfer_in_progress", "completed", "cancelled", "disputed", "pending_payment"])
async def test_delivery_timeout_never_refunds_transferred_or_protected_states(db, status):
    bridge, buyer, seller, listing = db
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    with bridge.session.begin():
        deal.status = status
    assert not await auto_cancel_undelivered_deal(bridge, deal.id, now=deal.seller_delivery_deadline + timedelta(days=1))


@pytest.mark.asyncio
async def test_transfer_after_deadline_rejected_but_id_only_before_deadline_works(db):
    bridge, buyer, seller, listing = db
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    await save_deal_delivery_details(bridge, buyer, deal.id, "XY987654")
    deal_id = deal.id
    with bridge.session.begin():
        deal.seller_delivery_deadline = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(HTTPException) as error:
        await set_deal_status(bridge, seller, deal_id, "transfer_in_progress")
    assert error.value.status_code == 409
    with bridge.session.begin():
        bridge.session.refresh(seller)
        deal.seller_delivery_deadline = datetime.now(UTC) + timedelta(hours=24)
        deal.seller_response_deadline = None
    await set_deal_status(bridge, seller, deal_id, "transfer_in_progress")
    assert deal.transfer_started_at
    assert not await auto_cancel_undelivered_deal(bridge, deal_id, now=datetime.now(UTC) + timedelta(days=2))


@pytest.mark.asyncio
async def test_timeout_transaction_rolls_back_on_notification_failure(db, monkeypatch):
    from app import services
    bridge, buyer, seller, listing = db
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    deal_id = deal.id
    deadline = deal.seller_delivery_deadline
    async def fail(*args, **kwargs):
        raise RuntimeError("database insert failure")
    monkeypatch.setattr(services, "create_notification", fail)
    with pytest.raises(RuntimeError):
        await auto_cancel_undelivered_deal(bridge, deal_id, now=deadline)
    with bridge.session.begin():
        assert bridge.session.get(Deal, deal_id).status == "paid"
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "refund")) == 0
        assert bridge.session.scalar(select(Wallet).where(Wallet.user_id == deal.buyer_id)).frozen_balance == 100


@pytest.mark.asyncio
async def test_worker_recovers_database_deadline_and_does_not_repeat(db, monkeypatch):
    bridge, buyer, seller, listing = db
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    deal_id = deal.id
    with bridge.session.begin():
        deal.seller_delivery_deadline = datetime.now(UTC) - timedelta(seconds=1)
    class Context:
        async def __aenter__(self):
            return bridge
        async def __aexit__(self, *args):
            bridge.session.rollback()
    monkeypatch.setattr(routes, "SessionLocal", Context)
    bridge.session.expire_all()
    await routes.recover_seller_response_timeouts()
    await routes.recover_seller_response_timeouts()
    with bridge.session.begin():
        assert bridge.session.get(Deal, deal_id).status == "cancelled"
        assert bridge.session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "deal_delivery_timeout")) == 2


@pytest.mark.asyncio
async def test_admin_message_notifies_both_exact_deal_once_even_after_read(control):
    bridge, buyer, seller, listing, admin = control
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    with bridge.session.begin():
        buyer.bot_started = seller.bot_started = True
    request = uuid.uuid4()
    first = await send_admin_deal_message(bridge, admin, deal.id, "Пожалуйста, ответьте", request)
    again = await send_admin_deal_message(bridge, admin, deal.id, "Пожалуйста, ответьте", request)
    assert first.id == again.id
    with bridge.session.begin():
        first.is_read = True  # One participant reading must not suppress the other's explicit notice.
    for participant in (buyer, seller):
        job = await claim_delivery(bridge, participant.id, datetime.now(UTC))
        assert job["params"] == {"deal_id": str(deal.id)}
        assert job["telegram_id"] == participant.telegram_id
        assert "Администратор присоединился" in job["text"]
    await send_admin_deal_message(bridge, admin, deal.id, "Второе сообщение", uuid.uuid4())
    with bridge.session.begin():
        assert bridge.session.scalar(select(func.count()).select_from(DealEvent).where(DealEvent.event_type == "admin_joined")) == 1
        notices = list(bridge.session.scalars(select(Notification).where(Notification.notification_type == "deal_admin_message")))
        assert len(notices) == 4
        assert sum("присоединился" in n.body for n in notices) == 2


@pytest.mark.asyncio
async def test_http_admin_authorization_id_only_and_message_replay(control, monkeypatch):
    bridge, buyer, seller, listing, admin = control
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    deal_id = deal.id
    async def notification_fixture(*args):
        pass  # Telegram dispatch is separately covered; never use production transport.
    monkeypatch.setattr(routes, "notify_deal_purchase_seller", notification_fixture)
    app = FastAPI()
    app.include_router(routes.router)
    async def session_dependency():
        try:
            yield bridge
        finally:
            bridge.session.rollback()
    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: buyer
    payload = {"body": "Проверим передачу", "client_message_id": str(uuid.uuid4())}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/admin/deals/{deal_id}/messages", json=payload)
        assert response.status_code == 403
        # Avoid starting a transaction via expired fixture attributes.
        with bridge.session.begin():
            bridge.session.refresh(buyer)
        response = await client.put(f"/api/deals/{deal_id}/delivery-details", json={"buyer_game_id":"AB123456"})
        assert response.status_code == 200, response.text
        assert response.json()["buyer_game_id"] == "AB123456"
        assert response.json()["seller_delivery_deadline"]
        with bridge.session.begin():
            bridge.session.refresh(admin)
        app.dependency_overrides[get_current_user] = lambda: admin
        first = await client.post(f"/api/admin/deals/{deal_id}/messages", json=payload)
        assert first.status_code == 201, first.text
        repeat = await client.post(f"/api/admin/deals/{deal_id}/messages", json=payload)
        assert repeat.status_code == 201 and repeat.json()["id"] == first.json()["id"]
        # Reload fixture timestamps consistently: SQLite strips tzinfo on SELECT.
        bridge.session.expire_all()
        page = await client.get(f"/api/admin/deals/{deal_id}/control")
        assert page.status_code == 200
        assert any("Проверим передачу" in m["body"] for m in page.json()["messages"])


@pytest.mark.asyncio
async def test_support_admin_reply_uses_same_deal_chat_and_two_notices(control):
    bridge, buyer, seller, listing, admin = control
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    ticket, *_ = await create_deal_support_case(bridge, buyer, deal.id, "Нужна помощь", "/screenshot", uuid.uuid4())
    async def commit():
        bridge.session.commit()
    async def refresh(row):
        bridge.session.refresh(row)
    bridge.commit = commit
    bridge.refresh = refresh
    tasks = BackgroundTasks()
    payload = SupportReplyCreate(message="Пожалуйста, выйдите на связь", client_request_id=uuid.uuid4())
    first = await routes.admin_reply_to_support_ticket(ticket.id, payload, tasks, admin, bridge)
    first_id = first.id
    again = await routes.admin_reply_to_support_ticket(ticket.id, payload, tasks, admin, bridge)
    assert again.id == first_id
    assert not tasks.tasks  # No second, weak Telegram notification through background_tasks.
    assert bridge.session.scalar(select(func.count()).select_from(ConversationMessage).where(ConversationMessage.sender_id == admin.id)) == 1
    notices = list(bridge.session.scalars(select(Notification).where(Notification.notification_type == "deal_admin_message")))
    assert len(notices) == 2 and {n.user_id for n in notices} == {buyer.id, seller.id}
    assert all("присоединился" in n.body for n in notices)


@pytest.mark.asyncio
async def test_explicit_admin_resume_grants_new_deadline_without_moving_money(control):
    bridge, buyer, seller, listing, admin = control
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    with bridge.session.begin():
        deal.status = "disputed"
        deal.seller_delivery_deadline = datetime.now(UTC) - timedelta(days=1)
    before = datetime.now(UTC)
    await admin_nonfinancial_action(bridge, admin, deal.id, "resume", "Проверено, продолжить", uuid.uuid4())
    assert deal.seller_delivery_deadline >= before + timedelta(hours=24)
    assert not await auto_cancel_undelivered_deal(bridge, deal.id, now=datetime.now(UTC))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "cancelled", "pending_payment"])
async def test_admin_cannot_send_new_message_to_closed_deal(control, status):
    bridge, buyer, seller, listing, admin = control
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    with bridge.session.begin():
        deal.status = status
    with pytest.raises(HTTPException) as error:
        await send_admin_deal_message(bridge, admin, deal.id, "Нельзя отправить", uuid.uuid4())
    assert error.value.status_code == 409
