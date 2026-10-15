"""Isolated PostgreSQL + signed HTTP identities; all external gifts are fixtures."""
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import uuid

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, text

from app.config import Settings, get_settings
from app.models import Deal, Wallet, WalletTransaction, WithdrawalRequest, User, Notification, AdminAction
from app.gift_withdrawals import preview_withdrawal, reserve_gift_withdrawal, record_gift_delivery
from app.schemas import GiftDeliveryCreate
from app.services import save_deal_delivery_details, set_deal_status, complete_deal, decide_withdrawal
from test_referral_bonus_postgres import isolated_pg, signed_login, apply_revisions
from test_seller_orders_postgres import paid_order
from test_catalog_and_acceptance_postgres import client_app, headers
from test_listing_images import make_image
from test_manual_gift_withdrawals import GIFTS


@pytest.mark.asyncio
@pytest.mark.parametrize("game", ["car_parking_1", "car_parking_2"])
async def test_paid_sale_to_manual_partial_gifts_one_settlement_no_double_fee(monkeypatch, game):
    async def catalog():
        return GIFTS
    monkeypatch.setattr("app.gift_withdrawals.available_gifts", catalog)
    async with isolated_pg() as (_, sessions):
        buyer, seller, listing, deal = await paid_order(sessions, game)
        admin = await signed_login(sessions, 99005)
        admin.role = "admin"
        async with sessions() as session, session.begin():
            (await session.get(User, admin.id)).role = "admin"
        async with sessions() as session:
            await save_deal_delivery_details(session, buyer, deal.id, "00AB123")
        async with sessions() as session:
            await set_deal_status(session, seller, deal.id, "seller_contacted")
        async with sessions() as session:
            await set_deal_status(session, seller, deal.id, "transfer_in_progress")
        async with sessions() as session, session.begin():
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).earned_balance == 0
            (await session.get(Deal, deal.id)).transfer_started_at = datetime.now(UTC) - timedelta(minutes=2)
        async with sessions() as session:
            await complete_deal(session, buyer, deal.id)
        async with sessions() as session:
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).earned_balance == 100
        async with sessions() as session:
            quote = await preview_withdrawal(session, seller, Decimal("42.86"))
        async def reserve():
            async with sessions() as session:
                return await reserve_gift_withdrawal(session, seller, uuid.UUID(quote["quote_id"]), "Test only")
        requests = await asyncio.gather(*(reserve() for _ in range(8)))
        request_id = requests[0].id
        assert len({item.id for item in requests}) == 1
        async with sessions() as session:
            await decide_withdrawal(session, admin, request_id, "approve", None)
        command = GiftDeliveryCreate(request_id=uuid.uuid4(), gift_id="15", quantity=1, reference="test-first-gift")
        async def delivery(value):
            async with sessions() as session:
                return await record_gift_delivery(session, admin, request_id, value)
        await asyncio.gather(*(delivery(command) for _ in range(8)))
        for action in ("paid", "reject"):
            async with sessions() as session:
                with pytest.raises(HTTPException) as error:
                    await decide_withdrawal(session, admin, request_id, action, "test")
                assert error.value.status_code == 409
        second = GiftDeliveryCreate(request_id=uuid.uuid4(), gift_id="15", quantity=1, reference="test-second-gift")
        app = client_app(sessions)
        # Real auth re-evaluates roles from the server allowlist on every login;
        # changing User.role alone must NOT grant HTTP administrator permissions.
        app.dependency_overrides[get_settings] = lambda: Settings(
            bot_token="referral-test-token", debug=False, admin_telegram_ids={admin.telegram_id})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            endpoint = f"/api/admin/withdrawals/{request_id}/gifts/delivered"
            assert (await client.post(endpoint, json=second.model_dump(mode="json"), headers=headers(seller))).status_code == 403
            for _ in range(2):
                response = await client.post(endpoint, json=second.model_dump(mode="json"), headers=headers(admin))
                assert response.status_code == 200, response.text
                assert response.json()["gift_remaining_stars"] == 0
                assert "gift_deliveries" not in response.json()  # Actor/proof remain admin-only.
        async def settle():
            async with sessions() as session:
                return await decide_withdrawal(session, admin, request_id, "paid", None)
        await asyncio.gather(*(settle() for _ in range(8)))
        async with sessions() as session:
            stored = await session.get(WithdrawalRequest, request_id)
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert len(stored.gift_deliveries) == 2 and stored.gift_remaining_stars == 0
            assert stored.fee_af == Decimal("12.86")
            assert wallet.earned_balance == Decimal("57.14") and wallet.earned_frozen_balance == 0
            for kind in ("withdrawal_paid", "withdrawal_reserved", "sale_income"):
                assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == kind)) == 1
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "withdrawal_paid")) == 1
            assert await session.scalar(select(func.count()).select_from(AdminAction).where(AdminAction.action == "withdrawal_gift_delivered")) == 2


@pytest.mark.asyncio
async def test_signed_image_uploads_read_back_and_publish_cp1_cp2():
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 99006)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client_app(sessions)), base_url="http://test") as client:
            assert (await client.get("/api/uploads/policy")).status_code == 401
            assert (await client.get("/api/help/rules")).status_code == 401
            policy = await client.get("/api/uploads/policy", headers=headers(user))
            assert policy.status_code == 200 and "avif" in policy.json()["formats"]
            rules = await client.get("/api/help/rules", headers=headers(user))
            assert rules.status_code == 200, rules.text
            assert rules.json()["withdrawal_fee_percent"] == 30
            assert rules.json()["car_seller_percent"] == 100
            assert "bot_token" not in rules.text and "database_url" not in rules.text
            async def upload(fmt, name, mime):
                response = await client.post("/api/uploads", files={"file": (name, make_image(fmt), mime)}, headers=headers(user))
                assert response.status_code == 201, response.text
                url = response.json()["url"]
                response = await client.get(url)
                assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
                assert response.content.startswith(b"\xff\xd8\xff")
                return url
            urls = await asyncio.gather(upload("JPEG", "car.jpg", "image/jpeg"), upload("PNG", "screen.png", ""), upload("HEIF", "iphone.heic", "application/octet-stream"), upload("AVIF", "edited.jpg", "image/jpeg"))
            bad = await client.post("/api/uploads", files={"file": ("fake.jpg", b"<svg>script</svg>", "image/jpeg")}, headers=headers(user))
            assert bad.status_code == 415
            for game in ("car_parking_1", "car_parking_2"):
                payload = {"client_request_id": str(uuid.uuid4()), "game_version": game, "brand": "Test car", "power_hp": 200, "max_speed_kph": 200, "description": "Test only", "price_af_coins": 100, "delivery_time_estimate": "up_to_1h", "image_urls": urls, "promote_for_24h": False}
                results = await asyncio.gather(*(client.post("/api/listings", json=payload, headers=headers(user)) for _ in range(2)))
                assert all(r.status_code == 201 for r in results), [r.text for r in results]
                assert results[0].json()["id"] == results[1].json()["id"]
                assert results[0].json()["images"] == urls


@pytest.mark.asyncio
async def test_additive_migration_preserves_historical_amount_and_status():
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: apply_revisions(sync, target="0051_vip_expiries"))
            user, request = uuid.uuid4(), uuid.uuid4()
            await conn.execute(text("INSERT INTO users(id,telegram_id,first_name,role,is_blocked,bot_started) VALUES (:id,99007,'Test','user',false,true)"), {"id": user})
            await conn.execute(text("INSERT INTO withdrawal_requests(id,user_id,amount,payout_method,details,status,fee_af,payout_stars) VALUES (:id,:u,21.43,'manual_gift','Historical','paid',6.43,15)"), {"id": request, "u": user})
            await conn.run_sync(lambda sync: apply_revisions(sync, target="head", after="0051_vip_expiries"))
            row = (await conn.execute(text("SELECT amount,fee_af,payout_stars,status,gift_deliveries FROM withdrawal_requests"))).one()
            assert tuple(row) == (Decimal("21.43"), Decimal("6.43"), 15, "paid", [])
