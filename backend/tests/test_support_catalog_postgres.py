import asyncio
import json
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.config import Settings, get_settings
from app.models import Deal, Notification, SupportMessage, SupportTicket, User, Wallet
from app import message_notifications
from test_catalog_and_acceptance_postgres import client_app, headers
from test_core_workflows import signed_init_data
from test_referral_bonus_postgres import isolated_pg, signed_login
from test_seller_orders_postgres import paid_order
from test_purchase_photo_notifications import transport


@pytest.mark.asyncio
@pytest.mark.parametrize("username", [None, "example"])
async def test_support_create_retry_access_reply_linked_order_and_legacy(username, monkeypatch):
    async with isolated_pg() as (_, sessions):
        buyer, seller, listing, deal = await paid_order(sessions)
        admin = await signed_login(sessions, 89101)
        stranger = await signed_login(sessions, 89102)
        async with sessions() as session, session.begin():
            stored = await session.get(User, admin.id)
            stored.role, stored.bot_started = "admin", True
            old = SupportTicket(user_id=buyer.id, author_id=buyer.id, case_type="general", topic="PAYMENT_ISSUE", status="closed")
            session.add(old)
        application = client_app(sessions)
        application.dependency_overrides[get_settings] = lambda: Settings(bot_token="referral-test-token", admin_id=admin.telegram_id, debug=False)
        buyer_headers = {"X-Telegram-Init-Data": signed_init_data("referral-test-token", {"id": buyer.telegram_id, "first_name": "<script>Имя</script>", **({"username": username} if username else {})})}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            categories = (await client.get("/api/support/categories", headers=buyer_headers)).json()
            assert len(categories) == len({row["key"] for row in categories}) == 11
            payload = {"topic": "TRANSACTION_PROBLEM", "message": "<script>Проблема</script>" * 100, "deal_id": str(deal.id), "client_request_id": str(uuid.uuid4())}
            results = await asyncio.gather(*[client.post("/api/support/tickets", headers=buyer_headers, json=payload) for _ in range(3)])
            assert all(r.status_code == 201 for r in results), [r.text for r in results]
            ticket = results[0].json()
            assert len({r.json()["id"] for r in results}) == 1
            assert ticket["topic_label"] == "Проблема со сделкой" and ticket["deal_id"] == str(deal.id)
            assert ticket["contact_url"] is None
            path = f'/api/support/tickets/{ticket["id"]}'
            assert (await client.get(path, headers=headers(stranger))).status_code == 404
            assert (await client.get(path, headers=headers(seller))).status_code == 404  # Private general inquiry.
            assert (await client.get('/api/admin/support/tickets', headers=headers(stranger))).status_code == 403
            assert (await client.post('/api/support/tickets', headers=headers(stranger), json=payload)).status_code == 404
            view = await client.get(f'/api/admin/support/tickets/{ticket["id"]}', headers=headers(admin))
            assert view.status_code == 200, view.text
            data = view.json()
            assert data["contact_url"] == ("https://t.me/example" if username else f"tg://user?id={buyer.telegram_id}")
            assert data["messages"][0]["body"] == payload["message"]
            legacy = await client.get(f'/api/support/tickets/{old.id}', headers=buyer_headers)
            assert legacy.json()["topic_label"] == "Оплата и баланс"
            reply = {"message": "Ответ через существующую поддержку", "client_request_id": str(uuid.uuid4())}
            responses = await asyncio.gather(*[client.post(f'/api/admin/support/tickets/{ticket["id"]}/messages', headers=headers(admin), json=reply) for _ in range(3)])
            assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
            assert len({r.json()["id"] for r in responses}) == 1
            for _ in range(3):
                assert (await client.get(path, headers=buyer_headers)).status_code == 200
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(SupportTicket)) == 2
            assert await session.scalar(select(func.count()).select_from(SupportMessage)) == 2
            notices = (await session.scalars(select(Notification).where(Notification.notification_type.in_(("support_ticket", "support_created", "support_reply"))))).all()
            assert len(notices) == 3 and all(n.delivery_status == "pending" for n in notices)
            assert "Проблема со сделкой" in next(n.body for n in notices if n.notification_type == "support_ticket")
            assert (await session.get(Deal, deal.id)).status == "paid"  # Linking is not a financial dispute.
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))).frozen_balance == 100
        sent = []
        def telegram(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(sent)}})
        transport(monkeypatch, telegram)
        monkeypatch.setattr(message_notifications, "SessionLocal", sessions)
        for _ in range(5):
            await message_notifications.recover_message_notifications()
        async with sessions() as session:
            notices = (await session.scalars(select(Notification).where(Notification.notification_type.in_(("support_ticket", "support_created", "support_reply"))))).all()
            assert len(notices) == 3 and all(n.delivery_status == "sent" for n in notices)
        admin_sent = [data for data in sent if data["chat_id"] == admin.telegram_id]
        assert len(admin_sent) == 1
        assert "Проблема со сделкой" in admin_sent[0]["text"]
        assert ("@example" if username else "Username отсутствует") in admin_sent[0]["text"]
        assert len([data for data in sent if data["chat_id"] == buyer.telegram_id]) == 2
