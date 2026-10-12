import re
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from sqlalchemy import func, select

from app import admin_access
from app.admin_operations import date_window, overview_data, router as operations_router
from app.analytics import router as analytics_router
from app.auth import get_current_user
from app.config import Settings
from app.database import get_session
from app.models import AdminAction, StarPayment, StarPaymentIntent, SupportTicket, User, Wallet, Notification, ConversationMessage
from app.routes import router, admin_reply_to_support_ticket
from app.schemas import SupportReplyCreate
from test_referral_bonus_postgres import isolated_pg, signed_login
from test_seller_orders_postgres import paid_order


def configured(monkeypatch):
    monkeypatch.setattr(admin_access, "get_settings", lambda: Settings(_env_file=None, admin_id=1, support_telegram_ids={3}))


def test_staff_capabilities_and_blocked_user(monkeypatch):
    configured(monkeypatch)
    for telegram_id, role, expected in [(1, "admin", "owner"), (2, "admin", "admin"), (3, "user", "support"), (4, "user", "user")]:
        user = SimpleNamespace(telegram_id=telegram_id, role=role, is_blocked=False)
        access = admin_access.staff_access(user)
        assert access["role"] == expected
        assert ("withdrawals" in access["tabs"]) == (role == "admin")
        user.is_blocked = True
        assert admin_access.staff_access(user)["tabs"] == []


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)])
def test_calendar_window_handles_dst(day, hours):
    lower, upper = date_window(day, day, "Europe/Bratislava", datetime(2027, 1, 1, tzinfo=UTC))
    assert (upper - lower).total_seconds() == hours * 3600


@pytest.mark.parametrize("start,end,zone", [(date(2026, 2, 1), date(2026, 1, 1), "UTC"), (date(2020, 1, 1), date(2026, 1, 1), "UTC"), (None, None, "Unknown/Zone")])
def test_invalid_report_period(start, end, zone):
    with pytest.raises(HTTPException) as error:
        date_window(start, end, zone)
    assert error.value.status_code == 422


SUPPORT_ALLOWED = {
    ("GET", "/api/admin/support/tickets"),
    ("GET", "/api/admin/support/tickets/{ticket_id}"),
    ("POST", "/api/admin/support/tickets/{ticket_id}/messages"),
    ("PATCH", "/api/admin/support/tickets/{ticket_id}"),
}
ADMIN_ROUTES = [(method, route.path) for source in (router, operations_router, analytics_router)
                for route in source.routes if route.path.startswith("/api/admin/") for method in route.methods]


@pytest.mark.asyncio
@pytest.mark.parametrize("telegram_id", [3, 4])
async def test_every_admin_endpoint_denies_unauthorized_role_before_database(monkeypatch, telegram_id):
    configured(monkeypatch)
    app = FastAPI()
    app.include_router(router)
    app.include_router(operations_router)
    app.include_router(analytics_router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4(), telegram_id=telegram_id, role="user", is_blocked=False)

    async def no_database():
        raise AssertionError("Unauthorized command reached the database")

    app.dependency_overrides[get_session] = no_database
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for method, path in ADMIN_ROUTES:
            if telegram_id == 3 and (method, path) in SUPPORT_ALLOWED:
                continue
            url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
            response = await client.request(method, url, json={})
            assert response.status_code == 403, (method, path, response.status_code, response.text)


@pytest.mark.asyncio
async def test_pg_overview_audit_and_support_access(monkeypatch):
    configured(monkeypatch)
    async with isolated_pg() as (_, sessions):
        admin = await signed_login(sessions, 1)
        admin.role = "admin"
        support = await signed_login(sessions, 3)
        async with sessions() as session, session.begin():
            now = datetime.now(UTC)
            session.add(StarPayment(user_id=admin.id, telegram_payment_charge_id="test-credit", xtr_amount=25, af_coin_amount=25, status="credited", raw_payload={}, processed_at=now))
            session.add(StarPayment(user_id=admin.id, telegram_payment_charge_id="test-not-credit", xtr_amount=99, af_coin_amount=99, status="pending", raw_payload={}, processed_at=now))
            session.add(StarPaymentIntent(user_id=admin.id, invoice_payload="test-pending", xtr_amount=25, status="pending", expires_at=now))
            session.add(AdminAction(admin_id=admin.id, action="test", target_type="user", target_id=support.id, metadata_json={"available_before": "0", "secret": "DO_NOT_EXPOSE"}))
            session.add(SupportTicket(user_id=admin.id, author_id=admin.id, topic="Test", status="open", case_type="general"))
        async with sessions() as session:
            result = await overview_data(session, None, None, "Europe/Bratislava")
            assert result["metrics"]["new_users"] == 2
            assert result["metrics"]["credited_payments"] == 1
            assert result["metrics"]["credited_stars"] == 25
            assert result["metrics"]["topup_intents"] == 1
            assert result["pending_now"]["support"] == 1
            assert result["unavailable"]["historical_dau"] is None
        app = FastAPI()
        app.include_router(router)
        app.include_router(operations_router)

        async def db_session():
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = db_session
        app.dependency_overrides[get_current_user] = lambda: admin
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/admin/audit")
            assert response.status_code == 200
            assert "DO_NOT_EXPOSE" not in response.text
            assert response.json()["items"][0]["changes"] == {"available_before": "0"}
            response = await client.get("/api/admin/users?limit=1&offset=1")
            assert response.status_code == 200 and len(response.json()) == 1
            response = await client.get(f"/api/admin/users?q={support.id}")
            assert [r["user"]["id"] for r in response.json()] == [str(support.id)]
            app.dependency_overrides[get_current_user] = lambda: support
            response = await client.get("/api/admin/support/tickets")
            assert response.status_code == 200 and len(response.json()) == 1
            ticket_id = response.json()[0]["id"]
            response = await client.get(f"/api/admin/support/tickets/{ticket_id}")
            assert response.status_code == 200 and response.json()["status"] == "in_progress"
            assert (await client.get("/api/admin/overview")).status_code == 403
        async with sessions() as session:
            assert (await session.get(User, support.id)).role == "user"
            assert await session.scalar(select(AdminAction.id).where(AdminAction.admin_id == support.id))


@pytest.mark.asyncio
async def test_support_reply_in_paid_deal_replays_once_without_releasing_escrow(monkeypatch):
    configured(monkeypatch)
    async with isolated_pg() as (_, sessions):
        buyer, seller, listing, deal = await paid_order(sessions)
        support = await signed_login(sessions, 3)
        async with sessions() as session, session.begin():
            ticket = SupportTicket(user_id=buyer.id, author_id=buyer.id, buyer_id=buyer.id,
                seller_id=seller.id, listing_id=listing.id, deal_id=deal.id, case_type="deal", topic="Help", status="open")
            session.add(ticket)
        payload = SupportReplyCreate(message="Пожалуйста, проверьте передачу", client_request_id=uuid.uuid4())
        for _ in range(2):
            async with sessions() as session:
                tasks = BackgroundTasks()
                await admin_reply_to_support_ticket(ticket.id, payload, tasks, support, session)
                assert not tasks.tasks  # Uses transactional deal outbox, never direct Telegram calls.
        async with sessions() as session:
            with pytest.raises(HTTPException) as conflict:
                await admin_reply_to_support_ticket(ticket.id, payload.model_copy(update={"message": "Другой текст"}), BackgroundTasks(), support, session)
            assert conflict.value.status_code == 409
        async with sessions() as session:
            buyer_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            seller_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert buyer_wallet.frozen_balance == 100
            assert seller_wallet.available_balance == 0
            assert await session.scalar(select(func.count()).select_from(ConversationMessage).where(ConversationMessage.sender_id == support.id)) == 1
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "deal_admin_message")) == 2
