import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select, func

from test_chat_lifecycle_db import db, DB
from app.models import ConversationMessage, Conversation, Notification, Listing, Wallet, WalletTransaction
from app.services import get_or_create_conversation, send_conversation_message, purchase_listing, auto_cancel_unanswered_deal
from app.inactivity import process_unanswered_dialog, record_buyer_request, record_seller_response
from app.message_notifications import claim_delivery, send_delivery, unread_query, notification_text
from app import message_notifications


@pytest.mark.asyncio
async def test_worker_recovers_pending_but_never_replays_ambiguous_delivery(db, monkeypatch):
    bridge, buyer, seller, listing = db
    seller_id = seller.id
    dialog, _, _ = await get_or_create_conversation(bridge, buyer, listing.id)
    await send_conversation_message(bridge, buyer, dialog.id, "recover me", uuid.uuid4())
    with bridge.session.begin():
        seller.bot_started = True
    class SessionContext:
        async def __aenter__(self):
            return bridge
        async def __aexit__(self, *args):
            bridge.session.rollback()
    monkeypatch.setattr(message_notifications, "SessionLocal", SessionContext)
    deliveries = []
    async def fake_send(job):
        deliveries.append(job)
        return "sent", None
    monkeypatch.setattr(message_notifications, "send_delivery", fake_send)
    await message_notifications.recover_message_notifications()
    await message_notifications.recover_message_notifications()
    assert len(deliveries) == 1
    with bridge.session.begin():
        notice = bridge.session.scalar(select(Notification).where(Notification.user_id == seller_id))
        notice.delivery_status = "sending"
        notice.delivery_claimed_at = datetime.now(UTC) - timedelta(minutes=3)
    await message_notifications.recover_message_notifications()
    assert len(deliveries) == 1
    with bridge.session.begin():
        bridge.session.expire_all()
        assert bridge.session.scalar(select(Notification.delivery_status).where(Notification.user_id == seller_id)) == "unknown"
        notice = bridge.session.scalar(select(Notification).where(Notification.user_id == seller_id))
        notice.delivery_status = "pending"
        notice.delivery_attempts = 0
    failed_attempts = []
    async def explicit_failure(job):
        failed_attempts.append(job)
        return "failed", "telegram_http_429"
    monkeypatch.setattr(message_notifications, "send_delivery", explicit_failure)
    for _ in range(4):
        with bridge.session.begin():
            notice = bridge.session.scalar(select(Notification).where(Notification.user_id == seller_id))
            notice.delivery_next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await message_notifications.recover_message_notifications()
    assert len(failed_attempts) == 3
    with bridge.session.begin():
        assert bridge.session.scalar(select(Notification.delivery_status).where(Notification.user_id == seller_id)) == "failed"


@pytest.mark.asyncio
async def test_read_http_receipt_cannot_read_other_chat_or_unseen_new_message(db):
    from fastapi import FastAPI
    from app.routes import router
    from app.auth import get_current_user
    from app.database import get_session
    bridge, buyer, seller, listing = db
    dialog, _, _ = await get_or_create_conversation(bridge, buyer, listing.id)
    first, _, _ = await send_conversation_message(bridge, buyer, dialog.id, "first", uuid.uuid4())
    second, _, _ = await send_conversation_message(bridge, buyer, dialog.id, "second", uuid.uuid4())
    dialog_id, first_id, second_id = dialog.id, first.id, second.id
    with bridge.session.begin():
        first.created_at = datetime.now(UTC) - timedelta(seconds=2)
        second.created_at = datetime.now(UTC)
    async def commit():
        bridge.session.commit()
    bridge.commit = commit
    async def session_dependency():
        try:
            yield bridge
        finally:
            bridge.session.rollback()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: seller
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        receipt = await client.post(f"/api/conversations/{dialog_id}/read?through_message_id={first_id}")
        assert receipt.status_code == 204
        summary = (await client.get("/api/conversations/unread-summary")).json()
        assert summary["total_unread"] == 1
        assert summary["conversations"][0]["conversation_type"] == "dialog"
        assert (await client.post(f"/api/conversations/{dialog_id}/read?through_message_id={uuid.uuid4()}")).status_code == 404
        assert (await client.post(f"/api/conversations/{dialog_id}/read?through_message_id={second_id}")).status_code == 204
        assert (await client.get("/api/conversations/unread-summary")).json()["total_unread"] == 0
        from app.models import User
        outsider = User(id=uuid.uuid4(), telegram_id=3, first_name="Other")
        app.dependency_overrides[get_current_user] = lambda: outsider
        assert (await client.post(f"/api/conversations/{dialog_id}/presence")).status_code == 404
        assert (await client.get(f"/api/conversations/{dialog_id}")).status_code == 404


@pytest.mark.asyncio
async def test_unread_outbox_exact_chat_duplicate_send_and_read(db):
    bridge, buyer, seller, listing = db
    with bridge.session.begin():
        seller.bot_started = True
    dialog, _, _ = await get_or_create_conversation(bridge, buyer, listing.id)
    request_id = uuid.uuid4()
    first, _, _ = await send_conversation_message(bridge, buyer, dialog.id, "hello", request_id)
    repeated, _, created = await send_conversation_message(bridge, buyer, dialog.id, "hello", request_id)
    assert repeated.id == first.id and not created
    second, _, _ = await send_conversation_message(bridge, buyer, dialog.id, "second", uuid.uuid4())
    with bridge.session.begin():
        assert len(list(bridge.session.scalars(unread_query(seller.id)))) == 2
        assert bridge.session.scalar(select(func.count()).select_from(Notification)) == 2
    job = await claim_delivery(bridge, seller.id, datetime.now(UTC))
    assert job["params"] == {"conversation_id": str(dialog.id)}
    assert job["text"] == "🔔 У вас 2 непрочитанных уведомления"
    assert len(job["ids"]) == 2
    # A concurrent worker cannot claim the same batch, even before HTTP completes.
    assert await claim_delivery(bridge, seller.id, datetime.now(UTC)) is None
    with bridge.session.begin():
        first.is_read = second.is_read = True
        for notice in bridge.session.scalars(select(Notification)):
            notice.delivery_status = "sent"
        assert not list(bridge.session.scalars(unread_query(seller.id)))
    assert await claim_delivery(bridge, seller.id, datetime.now(UTC)) is None


@pytest.mark.asyncio
async def test_presence_defers_notice_until_lease_expires(db):
    bridge, buyer, seller, listing = db
    dialog, _, _ = await get_or_create_conversation(bridge, buyer, listing.id)
    await send_conversation_message(bridge, buyer, dialog.id, "hello", uuid.uuid4())
    now = datetime.now(UTC)
    with bridge.session.begin():
        seller.bot_started = True
        seller.viewing_conversation_id = dialog.id
        seller.chat_presence_at = now
    assert await claim_delivery(bridge, seller.id, now) is None
    assert await claim_delivery(bridge, seller.id, now + timedelta(seconds=46)) is not None


@pytest.mark.asyncio
async def test_bot_payload_uses_one_exact_chat_button_and_handles_unknown(monkeypatch):
    config = type("Settings", (), {"bot_token": "test-only", "externally_reachable_url": "https://example.test"})()
    monkeypatch.setattr(message_notifications, "get_settings", lambda: config)
    requests = []
    def handler(request):
        import json
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(message_notifications.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    conversation_id = str(uuid.uuid4())
    status, error = await send_delivery({"telegram_id": 2, "text": notification_text(1), "params": {"conversation_id": conversation_id}})
    assert status == "sent" and error is None
    buttons = requests[0]["reply_markup"]["inline_keyboard"]
    assert len(buttons) == len(buttons[0]) == 1
    assert buttons[0][0]["text"] == "Открыть"
    assert f"conversation_id={conversation_id}" in buttons[0][0]["web_app"]["url"]
    def timeout(request):
        raise httpx.ReadTimeout("test timeout", request=request)
    monkeypatch.setattr(message_notifications.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(timeout), **kw))
    assert (await send_delivery({"telegram_id": 2, "text": "test", "params": {}}))[0] == "unknown"


@pytest.mark.asyncio
async def test_ordinary_inactivity_hides_once_without_any_refund(db):
    bridge, buyer, seller, listing = db
    dialog, _, _ = await get_or_create_conversation(bridge, buyer, listing.id)
    await send_conversation_message(bridge, buyer, dialog.id, "question", uuid.uuid4())
    # SQLite timestamps are timezone-naive; production columns are PostgreSQL timestamptz.
    due = (datetime.now(UTC) + timedelta(hours=25)).replace(tzinfo=None)
    assert await process_unanswered_dialog(bridge, dialog.id, due)
    assert not await process_unanswered_dialog(bridge, dialog.id, due)
    with bridge.session.begin():
        assert bridge.session.get(Listing, listing.id).status == "paused"
        assert bridge.session.get(Conversation, dialog.id).inactivity_status == "processed"
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction)) == 0
        assert bridge.session.scalar(select(func.count()).select_from(Notification).where(
            Notification.notification_type == "seller_inactive_hidden")) == 1


@pytest.mark.asyncio
async def test_seller_response_stops_case_then_new_buyer_request_rearms(db):
    bridge, buyer, seller, listing = db
    dialog, _, _ = await get_or_create_conversation(bridge, buyer, listing.id)
    start = datetime.now(UTC)
    with bridge.session.begin():
        record_buyer_request(dialog, start)
        record_seller_response(dialog, start + timedelta(hours=23))
    assert not await process_unanswered_dialog(bridge, dialog.id, (start + timedelta(hours=25)).replace(tzinfo=None))
    with bridge.session.begin():
        record_buyer_request(dialog, start + timedelta(hours=26))
    assert not await process_unanswered_dialog(bridge, dialog.id, (start + timedelta(hours=49)).replace(tzinfo=None))
    assert await process_unanswered_dialog(bridge, dialog.id, (start + timedelta(hours=51)).replace(tzinfo=None))


@pytest.mark.asyncio
async def test_deal_refund_and_hidden_listing_history_survive_repeated_worker(db):
    bridge, buyer, seller, listing = db
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    with bridge.session.begin():
        deal.seller_response_deadline = datetime.now(UTC) - timedelta(hours=1)
        other = Listing(id=uuid.uuid4(), seller_id=seller.id, listing_type="regular", status="active",
            brand="Other", model="", power_hp=1, max_speed_kph=1, description="", price_af_coins=100)
        bridge.session.add(other)
    assert await auto_cancel_unanswered_deal(bridge, deal.id)
    assert await auto_cancel_unanswered_deal(bridge, deal.id) is None
    with bridge.session.begin():
        assert deal.cancellation_reason == "seller_inactive"
        assert deal.status == "cancelled"
        assert listing.status == other.status == "paused"
        assert bridge.session.get(Conversation, deal.conversation_id).archived_at
        buyer_wallet = bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        assert buyer_wallet.available_balance == Decimal(200)
        assert buyer_wallet.frozen_balance == 0
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction).where(
            WalletTransaction.transaction_type == "seller_timeout_refund")) == 1
        notices = list(bridge.session.scalars(select(Notification).where(Notification.notification_type.in_(
            ("seller_timeout_refund", "seller_timeout_cancelled")))))
        assert len(notices) == 2
        assert all(notice.delivery_status == "pending" for notice in notices)
