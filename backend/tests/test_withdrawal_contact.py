import uuid
from types import SimpleNamespace
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func

from app.models import User, WithdrawalRequest, SupportMessage, Notification
from app.withdrawal_support import profile_url, validated_username
from test_referral_bonus_postgres import isolated_pg, signed_login


@pytest.mark.parametrize("value", [None, "", "a/bad", "bad?x=1", "@example", "<script>"])
def test_invalid_username_never_becomes_url(value):
    assert validated_username(value) is None
    assert profile_url(SimpleNamespace(username=value, telegram_id=123)) == "tg://user?id=123"


def test_valid_username_link():
    assert profile_url(SimpleNamespace(username="Example_1", telegram_id=123)) == "https://t.me/Example_1"


@pytest.mark.asyncio
async def test_http_search_support_access_replay_and_blocked_delivery(monkeypatch):
    from app.auth import get_current_user
    from app.database import get_session
    from app.routes import router
    from app.message_notifications import claim_delivery, send_delivery
    import app.message_notifications as outbox

    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 9701)
        admin = await signed_login(sessions, 9702)
        stranger = await signed_login(sessions, 9703)
        admin.role = "admin"
        async with sessions() as session, session.begin():
            stored_user = await session.get(User, user.id)
            stored_user.bot_started = True
            withdrawal = WithdrawalRequest(user_id=user.id, amount=42, payout_method="manual_gift",
                details="Historical fixture", status="pending", payout_stars=25)
            session.add(withdrawal)
        actor = user
        async def current(): return actor
        async def database():
            async with sessions() as session:
                yield session
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = current
        app.dependency_overrides[get_session] = database
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/admin/withdrawals")).status_code == 403
            actor = stranger
            assert (await client.post(f"/api/withdrawals/{withdrawal.id}/support")).status_code == 404
            actor = user
            response = await client.post(f"/api/withdrawals/{withdrawal.id}/support")
            assert response.status_code == 200, response.text
            ticket = response.json()
            assert withdrawal.public_id in ticket["topic"]
            actor = stranger
            assert (await client.get(f'/api/support/tickets/{ticket["id"]}')).status_code == 404
            assert (await client.post(f'/api/support/tickets/{ticket["id"]}/messages', json={"message":"Intrude"})).status_code == 404
            actor = admin
            response = await client.get("/api/admin/withdrawals", params={"q":withdrawal.public_id})
            assert response.status_code == 200, response.text
            assert len(response.json()) == 1
            assert response.json()[0]["profile_url"] == "tg://user?id=9701"
            assert (await client.get("/api/admin/withdrawals", params={"q":"#999999"})).json() == []
            assert (await client.get("/api/admin/withdrawals", params={"q":"not-a-number"})).status_code == 422
            path = f'/api/admin/support/tickets/{ticket["id"]}/messages'
            assert (await client.post(path, json={"message":"Missing key"})).status_code == 422
            payload = {"message":"Уточните получение подарка", "client_request_id":str(uuid.uuid4())}
            for _ in range(2):
                response = await client.post(path, json=payload)
                assert response.status_code == 201, response.text
            actor = user
            assert (await client.get(f'/api/support/tickets/{ticket["id"]}')).json()["messages"][0]["body"] == payload["message"]
            response = await client.post(f'/api/support/tickets/{ticket["id"]}/messages', json={"message":"Получил, спасибо", "client_request_id":str(uuid.uuid4())})
            assert response.status_code == 201
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SupportMessage)) == 2
                assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "withdrawal_support_reply")) == 1
            async with sessions() as session:
                job = await claim_delivery(session, user.id, datetime.now(UTC))
            assert job["params"] == {"support_case": ticket["id"]}
            assert payload["message"] in job["text"]
            sent_payloads = []
            class FakeClient:
                def __init__(self, **kw): pass
                async def __aenter__(self): return self
                async def __aexit__(self, *args): pass
                async def post(self, url, json):
                    sent_payloads.append(json)
                    return SimpleNamespace(is_success=False, status_code=403,
                        json=lambda:{"ok":False,"error_code":403,"description":"Forbidden: bot was blocked by the user"})
            monkeypatch.setattr(outbox, "get_settings", lambda: SimpleNamespace(bot_token="test-only", externally_reachable_url="https://example.test"))
            monkeypatch.setattr(outbox.httpx, "AsyncClient", FakeClient)
            assert await send_delivery(job) == ("blocked", "telegram_bot_blocked_by_user")
            assert "support_case=" in sent_payloads[0]["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"]
            async with sessions() as session, session.begin():
                notice = await session.get(Notification, job["ids"][0])
                notice.delivery_status = "blocked"
                notice.delivery_error = "telegram_bot_blocked_by_user"
            actor = admin
            response = await client.get("/api/admin/withdrawals")
            assert response.json()[0]["contact_delivery_status"] == "blocked"
            assert response.json()[0]["status"] == "pending"
