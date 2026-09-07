"""Persistent service/HTTP regression checks. SQLite is NOT a PostgreSQL lock test."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.schema import CreateTable

from test_chat_lifecycle_db import db  # shared database bridge
from app.models import (User, Deal, DealEvent, Wallet, WalletTransaction, Conversation,
    Notification, SupportTicket, SupportMessage, SupportCaseEvent, AdminAction,
    StarPaymentIntent, StarPayment)
from app.services import (purchase_listing, resolve_dispute, cancel_deal,
    create_deal_support_case, process_successful_payment)
from app.deal_lifecycle import recover_lifecycle_state, schedule_next_reminder, admin_nonfinancial_action


def wallet(bridge, user):
    return bridge.session.scalar(select(Wallet).where(Wallet.user_id == user.id))


@pytest.fixture
def control(db):
    bridge, buyer, seller, listing = db
    with bridge.session.bind.begin() as connection:
        for model in (SupportTicket, SupportMessage, SupportCaseEvent, AdminAction, StarPaymentIntent, StarPayment):
            connection.execute(CreateTable(model.__table__))
    admin = User(id=uuid.uuid4(), telegram_id=3, first_name="Admin", role="admin")
    with bridge.session.begin():
        bridge.session.add(admin)
    return bridge, buyer, seller, listing, admin


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "refund"])
async def test_admin_finance_is_persisted_once_and_terminal_cannot_reopen(control, outcome):
    bridge, buyer, seller, listing, admin = control
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    deal_id = deal.id
    request = uuid.uuid4()
    await resolve_dispute(bridge, admin, deal.id, outcome, "Проверено администратором", allow_active=True, request_id=request)
    await resolve_dispute(bridge, admin, deal.id, outcome, "Проверено администратором", allow_active=True, request_id=request)
    with bridge.session.begin():
        bw = wallet(bridge, buyer)
        sw = wallet(bridge, seller)
        assert bw.frozen_balance == 0
        assert bw.available_balance == (200 if outcome == "refund" else 100)
        assert sw.available_balance == 200 + (deal.seller_payout if outcome == "complete" else 0)
        assert bridge.session.scalar(select(func.count()).select_from(DealEvent).where(DealEvent.request_id == request)) == 1
        assert bridge.session.get(Conversation, deal.conversation_id).archived_at
        count = bridge.session.scalar(select(func.count()).select_from(WalletTransaction))
    # A restarted session still sees the completed operation and the same request ID.
    bridge.session.expire_all()
    with bridge.session.begin():
        bridge.session.refresh(admin)
    await resolve_dispute(bridge, admin, deal_id, outcome, "Проверено администратором", allow_active=True, request_id=request)
    with pytest.raises(HTTPException):
        await resolve_dispute(bridge, admin, deal.id, outcome, "Другой запрос", allow_active=True, request_id=uuid.uuid4())
    bridge.session.rollback()
    with bridge.session.begin():
        bridge.session.refresh(admin)
    with pytest.raises(HTTPException):
        await admin_nonfinancial_action(bridge, admin, deal_id, "resume", "Попытка открыть снова", uuid.uuid4())
    with bridge.session.begin():
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction)) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("by_seller", [False, True])
async def test_participant_cancellation_refunds_and_notifies_both(control, by_seller):
    bridge, buyer, seller, listing, _ = control
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    await cancel_deal(bridge, seller if by_seller else buyer, deal.id)
    with bridge.session.begin():
        assert wallet(bridge, buyer).available_balance == 200
        notices = list(bridge.session.scalars(select(Notification).where(Notification.notification_type == "deal_cancelled")))
        assert {n.user_id for n in notices} == {buyer.id, seller.id}
        assert all(n.delivery_status == "pending" for n in notices)
        assert listing.status == "active"
    with pytest.raises(HTTPException):
        await cancel_deal(bridge, buyer, deal.id)


@pytest.mark.asyncio
async def test_support_only_stops_reminders_after_commit_and_admin_refund_hides_transferred_item(control):
    bridge, buyer, seller, listing, admin = control
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    deal_id = deal.id
    with bridge.session.begin():
        deal.status = "transfer_in_progress"
        deal.transfer_started_at = datetime.now(UTC)
        deal.buyer_transfer_reminder_status = "pending"
    with pytest.raises(HTTPException):
        await cancel_deal(bridge, seller, deal_id)
    with pytest.raises(HTTPException):
        await create_deal_support_case(bridge, buyer, deal_id, "Проблема", "", uuid.uuid4())
    with bridge.session.begin():
        assert deal.status == "transfer_in_progress"
        assert deal.buyer_transfer_reminder_status == "pending"
    ticket, *_ = await create_deal_support_case(bridge, buyer, deal.id, "Машина не получена", "/screenshot", uuid.uuid4())
    assert deal.status == "disputed"
    assert deal.buyer_transfer_reminder_status == "skipped"
    assert (ticket.deal_id, ticket.buyer_id, ticket.seller_id) == (deal.id, buyer.id, seller.id)
    await recover_lifecycle_state(bridge, deal.id, datetime.now(UTC) + timedelta(days=5))
    assert deal.buyer_transfer_reminder_status == "skipped"
    with pytest.raises(HTTPException):
        await admin_nonfinancial_action(bridge, admin, deal_id, "resume", "Не закрыт спор", uuid.uuid4())
    with bridge.session.begin():
        bridge.session.refresh(admin)
    await resolve_dispute(bridge, admin, deal_id, "refund", "Товар не был получен", allow_active=True, request_id=uuid.uuid4())
    assert listing.status == "paused"
    assert ticket.status == "resolved"


@pytest.mark.asyncio
async def test_reminder_rounds_restart_and_escalation_do_not_move_money(control):
    bridge, buyer, seller, listing, admin = control
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    now = datetime.now(UTC)
    with bridge.session.begin():
        deal.status = "transfer_in_progress"
        deal.transfer_started_at = now - timedelta(hours=49)
        deal.buyer_transfer_reminder_status = "sending"
        deal.buyer_transfer_reminder_claimed_at = now - timedelta(minutes=3)
        for event in bridge.session.scalars(select(DealEvent).where(DealEvent.deal_id == deal.id)):
            event.created_at = now - timedelta(hours=49)
    await recover_lifecycle_state(bridge, deal.id, now)
    first_schedule = deal.buyer_transfer_reminder_scheduled_at
    assert first_schedule == now + timedelta(hours=2)
    await recover_lifecycle_state(bridge, deal.id, now)
    assert deal.buyer_transfer_reminder_scheduled_at == first_schedule
    with bridge.session.begin():
        assert wallet(bridge, buyer).frozen_balance == 100
        assert wallet(bridge, seller).available_balance == 200
        assert bridge.session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "deal_admin_review")) == 1
        schedule_next_reminder(deal, first_schedule)
        assert deal.buyer_transfer_reminder_scheduled_at == now + timedelta(hours=6)
        schedule_next_reminder(deal, deal.buyer_transfer_reminder_scheduled_at)
        assert deal.buyer_transfer_reminder_scheduled_at == now + timedelta(hours=18)
    deal_id = deal.id
    bridge.session.expire_all()
    with bridge.session.begin():
        restored = bridge.session.get(Deal, deal_id)
        assert restored.buyer_reminder_round == 3
        assert restored.needs_admin_review_at is not None


@pytest.mark.asyncio
async def test_admin_comment_retries_and_user_denial(control):
    bridge, buyer, _, listing, admin = control
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    for action in ("comment", "review", "resume"):
        with pytest.raises(HTTPException) as error:
            await admin_nonfinancial_action(bridge, buyer, deal.id, action, "Нет полномочий", uuid.uuid4())
        assert error.value.status_code == 403
    request = uuid.uuid4()
    for _ in range(2):
        await admin_nonfinancial_action(bridge, admin, deal.id, "comment", "Внутренняя заметка", request)
    with bridge.session.begin():
        assert bridge.session.scalar(select(func.count()).select_from(AdminAction)) == 1
        assert deal.status == "paid"


@pytest.mark.asyncio
async def test_expired_stars_intent_valid_payment_credits_once(control):
    bridge, buyer, _, _, _ = control
    with bridge.session.begin():
        intent = StarPaymentIntent(id=uuid.uuid4(), user_id=buyer.id, invoice_payload="autoflow_topup:late-payment",
            xtr_amount=100, status="expired", expires_at=datetime.now(UTC) - timedelta(days=1))
        bridge.session.add(intent)
    payment = {"currency":"XTR", "invoice_payload":"autoflow_topup:late-payment", "telegram_payment_charge_id":"unique-late-charge", "total_amount":100}
    assert await process_successful_payment(bridge, buyer.telegram_id, payment)
    assert not await process_successful_payment(bridge, buyer.telegram_id, payment)
    with bridge.session.begin():
        assert wallet(bridge, buyer).available_balance == 300
        assert intent.status == "paid"
        assert bridge.session.scalar(select(func.count()).select_from(StarPayment)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"currency":"USD"}, {"total_amount":99}])
async def test_expired_intent_still_checks_currency_and_amount(control, change):
    bridge, buyer, _, _, _ = control
    with bridge.session.begin():
        bridge.session.add(StarPaymentIntent(id=uuid.uuid4(), user_id=buyer.id, invoice_payload="autoflow_topup:invalid-payment",
            xtr_amount=100, status="expired", expires_at=datetime.now(UTC) - timedelta(days=1)))
    payment = {"currency":"XTR", "invoice_payload":"autoflow_topup:invalid-payment", "telegram_payment_charge_id":"wrong-charge", "total_amount":100, **change}
    try:
        assert not await process_successful_payment(bridge, buyer.telegram_id, payment)
    except HTTPException:
        pass  # The existing service rejects mismatched Telegram payloads with 4xx.
    with bridge.session.begin():
        assert wallet(bridge, buyer).available_balance == 200
        assert bridge.session.scalar(select(func.count()).select_from(StarPayment)) == 0


@pytest.mark.asyncio
async def test_admin_control_http_authorization_detail_and_repeat(control):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.routes import router
    from app.auth import get_current_user
    from app.database import get_session
    bridge, buyer, seller, listing, admin = control
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    deal_id = deal.id
    app = FastAPI()
    app.include_router(router)
    async def test_session():
        try:
            yield bridge
        finally:
            bridge.session.rollback()
    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_current_user] = lambda: buyer
    payload = {"action":"refund", "reason":"Проверен возврат", "request_id":str(uuid.uuid4())}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for method in ("get", "post"):
            response = await getattr(client, method)(f"/api/admin/deals/{deal_id}/control", **({"json":payload} if method == "post" else {}))
            assert response.status_code == 403
        # Auth normally returns a committed user. Reload in a completed transaction.
        with bridge.session.begin():
            bridge.session.refresh(admin)
        app.dependency_overrides[get_current_user] = lambda: admin
        response = await client.get(f"/api/admin/deals/{deal_id}/control")
        assert response.status_code == 200, response.text
        assert response.json()["reserved_af_coins"] == 100
        assert response.json()["events"][0]["type"] == "funds_reserved"
        for _ in range(2):
            with bridge.session.begin():
                bridge.session.refresh(admin)
            response = await client.post(f"/api/admin/deals/{deal_id}/control", json=payload)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "cancelled"
