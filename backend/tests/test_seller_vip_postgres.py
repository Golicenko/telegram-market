"""Real PostgreSQL locking/migrations, signed HTTP identities; no live money."""

import asyncio
import uuid
from datetime import timedelta

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from app import seller_vip as vip
from app.config import Settings, get_settings
from app.models import (
    AdminAction, Deal, Listing, Notification, PublicationDraft, SellerVipPinUsage,
    SellerVipSubscription, StarPayment, User, Wallet, WalletTransaction,
)
from test_catalog_and_acceptance_postgres import client_app, headers
from test_referral_bonus_postgres import apply_revisions, isolated_pg, signed_login
from test_seller_vip import plans, start
from test_publication_stars_postgres import listing_payload
from app.services import create_listing


async def seed(sessions, user_id):
    async with sessions() as session, session.begin():
        session.add_all(plans())
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        wallet.purchased_balance, wallet.bonus_balance = 500, 50


@pytest.mark.asyncio
async def test_concurrent_purchase_same_and_different_keys_one_debit_then_last_pin_one_transition():
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 99501)
        await seed(sessions, user.id)
        payload = start(funding=(29, 0, 50))

        async def buy(request):
            async with sessions() as session:
                try:
                    row, replayed = await vip.purchase(session, user.id, request)
                    return row.id, replayed
                except HTTPException as error:
                    return error.status_code

        outcomes = await asyncio.wait_for(asyncio.gather(*(buy(payload) for _ in range(8))), timeout=15)
        assert len({row[0] for row in outcomes}) == 1
        assert sum(not row[1] for row in outcomes) == 1
        assert await buy(start()) == 409
        async with sessions() as session, session.begin():
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 1
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
            assert wallet.available_balance == 471 and wallet.bonus_balance == 0 and wallet.earned_balance == 0
            sub = await session.scalar(select(SellerVipSubscription))
            assert sub.price_paid == 79 and sub.bonus_af == 50 and sub.purchased_af == 29
            sub.pins_72h_remaining = 1
            listing_ids = []
            for game in ("car_parking_1", "car_parking_2"):
                listing = Listing(id=uuid.uuid4(), seller_id=user.id, listing_type="regular", game_version=game,
                                  product_kind="car", status="active", brand="Real isolated DB car", model=game,
                                  power_hp=100, max_speed_kph=200, description="Isolated", price_af_coins=10)
                session.add(listing)
                listing_ids.append(listing.id)

        async def pin(listing_id):
            async with sessions() as session:
                try:
                    usage, _ = await vip.pin(session, user.id, vip.PinRequest(listing_id=listing_id, duration_hours=72, request_id=uuid.uuid4()))
                    return usage.id
                except HTTPException as error:
                    return error.status_code

        results = await asyncio.wait_for(asyncio.gather(*(pin(listing_id) for listing_id in listing_ids)), timeout=15)
        assert results.count(409) == 1
        async with sessions() as session:
            sub = await session.scalar(select(SellerVipSubscription))
            assert sub.pins_72h_remaining == 0
            assert await session.scalar(select(func.count()).select_from(SellerVipPinUsage)) == 1
            assert await session.scalar(select(func.count()).select_from(Listing).where(Listing.pinned.is_(True))) == 1
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "vip_completed")) == 1
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 1


@pytest.mark.asyncio
async def test_signed_api_access_split_active_state_expiry_and_admin_audit():
    async with isolated_pg() as (_, sessions):
        user, admin, support = [await signed_login(sessions, number) for number in (99601, 99602, 99603)]
        await seed(sessions, user.id)
        app = client_app(sessions)
        app.include_router(vip.router)
        app.dependency_overrides[get_settings] = lambda: Settings(
            bot_token="referral-test-token", admin_id=admin.telegram_id, support_telegram_ids={support.telegram_id}, debug=False,
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://isolated") as client:
            assert (await client.get("/api/seller-vip")).status_code == 401
            overview = await client.get("/api/seller-vip", headers=headers(user))
            assert overview.status_code == 200 and "no-store" in overview.headers["cache-control"]
            assert [plan["price_af"] for plan in overview.json()["plans"]] == [79, 249]
            assert overview.json()["active_subscription"] is None
            quote = await client.post("/api/seller-vip/quote", headers=headers(user), json={"plan_code": "month"})
            assert quote.status_code == 200
            assert quote.json()["bonus_af"] == 50 and quote.json()["regular_af"] == 29
            malicious = await client.post("/api/seller-vip/purchases", headers=headers(user), json={"plan_code": "month", "request_id": str(uuid.uuid4()), "price_af": 1})
            assert malicious.status_code == 422
            payload = {"plan_code": "month", "request_id": str(uuid.uuid4()), "quote_fingerprint": quote.json()["quote_fingerprint"]}
            paid = await client.post("/api/seller-vip/purchases", headers=headers(user), json=payload)
            assert paid.status_code == 200 and not paid.json()["replayed"]
            subscription_id = paid.json()["subscription"]["id"]
            retry = await client.post("/api/seller-vip/purchases", headers=headers(user), json=payload)
            assert retry.status_code == 200 and retry.json()["replayed"]
            assert retry.json()["subscription"]["id"] == subscription_id
            active = (await client.get("/api/seller-vip", headers=headers(user))).json()["active_subscription"]
            assert active["car_limit"] == 15 and active["pins_72h_remaining"] == 10
            assert active["remaining_seconds"] > 29 * 86400
            assert (await client.get("/api/admin/seller-vip", headers=headers(user))).status_code == 403
            assert (await client.get("/api/admin/seller-vip", headers=headers(support))).status_code == 403
            report = await client.get("/api/admin/seller-vip", headers=headers(admin))
            assert report.status_code == 200 and report.json()["items"][0]["payment_source"] == "mixed"
            assert report.json()["items"][0]["telegram_id"] == user.telegram_id
            command = {"user_id": str(user.id), "action": "extend", "days": 2, "request_id": str(uuid.uuid4()), "reason": "Explicit isolated extension", "confirmed": True}
            assert (await client.post("/api/admin/seller-vip/actions", headers=headers(support), json=command)).status_code == 403
            no_confirm = await client.post("/api/admin/seller-vip/actions", headers=headers(admin), json={**command, "confirmed": False})
            assert no_confirm.status_code == 422
            extended = await client.post("/api/admin/seller-vip/actions", headers=headers(admin), json=command)
            assert extended.status_code == 200 and not extended.json()["replayed"]
            assert (await client.post("/api/admin/seller-vip/actions", headers=headers(admin), json=command)).json()["replayed"]
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(AdminAction).where(AdminAction.action == "seller_vip_extend")) == 1
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 1
        async with sessions() as session, session.begin():
            sub = await session.get(SellerVipSubscription, uuid.UUID(subscription_id))
            sub.starts_at = vip.now_utc() - timedelta(days=30)
            sub.expires_at = vip.now_utc() + timedelta(hours=23)
        async with sessions() as session:
            await vip.process_expiries(session)
        async with sessions() as session:
            await vip.process_expiries(session)
        async with sessions() as session, session.begin():
            sub = await session.get(SellerVipSubscription, uuid.UUID(subscription_id))
            sub.expires_at = vip.now_utc() - timedelta(seconds=1)
        async with sessions() as session:
            await vip.process_expiries(session)
        async with sessions() as session:
            await vip.process_expiries(session)
        async with sessions() as session:
            assert await vip.active_subscription(session, user.id) is None
            for name in ("seller_vip_expiring", "seller_vip_expired"):
                assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == name)) == 1


@pytest.mark.asyncio
async def test_additive_migration_seeds_exact_plans_preserves_existing_wallet_and_account_pause():
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: apply_revisions(sync, target="0056_account_video_processing"))
            uid, wid = uuid.uuid4(), uuid.uuid4()
            await connection.execute(text("INSERT INTO users(id,telegram_id,role,first_name,is_blocked) VALUES(:id,99701,'user','Existing',false)"), {"id": uid})
            await connection.execute(text("INSERT INTO wallets(id,user_id,purchased_balance,earned_balance,purchased_frozen_balance,earned_frozen_balance,total_earned,version) VALUES(:id,:user,100,0,0,0,0,0)"), {"id": wid, "user": uid})
            await connection.run_sync(lambda sync: apply_revisions(sync, target="0057_seller_vip", after="0056_account_video_processing"))
            result = (await connection.execute(text("SELECT code,duration_days,price_af,pins_72h,pins_24h,car_limit,account_limit FROM seller_vip_plans ORDER BY duration_days"))).all()
            assert result == [("month", 30, 79, 10, 0, 15, 10), ("quarter", 90, 249, 45, 23, 68, 45)]
            assert await connection.scalar(text("SELECT purchased_balance FROM wallets WHERE id=:id"), {"id": wid}) == 100
            assert await connection.scalar(text("SELECT count(*) FROM seller_vip_subscriptions")) == 0
            assert await connection.scalar(text("SELECT count(*) FROM account_grants")) == 0


@pytest.mark.asyncio
async def test_last_vip_car_slot_race_paid_draft_cannot_bypass_and_expiry_never_deletes():
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 99801)
        await seed(sessions, user.id)
        async with sessions() as session:
            sub, _ = await vip.purchase(session, user.id, start(funding=(29, 0, 50)))
        async with sessions() as session, session.begin():
            (await session.get(SellerVipSubscription, sub.id)).car_limit = 1

        async def publish():
            async with sessions() as session:
                try:
                    listing = await create_listing(session, user, listing_payload(), listing_type="regular")
                    return listing.id
                except HTTPException as error:
                    assert error.detail["code"] == "seller_vip_listing_limit"
                    return error.status_code

        results = await asyncio.wait_for(asyncio.gather(publish(), publish()), timeout=15)
        assert results.count(409) == 1
        winner_id = next(value for value in results if isinstance(value, uuid.UUID))
        payload = listing_payload()
        async with sessions() as session, session.begin():
            payment = StarPayment(id=uuid.uuid4(), user_id=user.id, telegram_payment_charge_id=str(uuid.uuid4()),
                                  xtr_amount=5, af_coin_amount=0, status="publication_paid", raw_payload={"isolated": True})
            session.add(payment)
            await session.flush()
            draft = PublicationDraft(id=uuid.uuid4(), user_id=user.id, request_id=payload.client_request_id,
                                     payload=payload.model_dump(mode="json"), price_stars=5, status="paid", payment_id=payment.id)
            session.add(draft)
        async with sessions() as session:
            with pytest.raises(HTTPException) as error:
                await create_listing(session, user, payload, listing_type="regular", publication_id=draft.id)
            assert error.value.status_code == 409 and error.value.detail["code"] == "seller_vip_listing_limit"
        async with sessions() as session, session.begin():
            assert await session.scalar(select(func.count()).select_from(Listing)) == 1
            assert (await session.get(PublicationDraft, draft.id)).status == "paid"
            active = await session.get(SellerVipSubscription, sub.id)
            active.starts_at = vip.now_utc() - timedelta(days=30)
            active.expires_at = vip.now_utc() - timedelta(seconds=1)
        async with sessions() as session:
            await vip.process_expiries(session)
        async with sessions() as session:
            assert await vip.active_limits(session, user.id) is None
            original = await session.get(Listing, winner_id)
            assert original.status == "active" and original.deleted_at is None
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "seller_vip_purchase")) == 1


@pytest.mark.asyncio
async def test_about_signed_http_real_counts_no_screenshot_offsets_or_visitor_founder_photo(monkeypatch):
    from app import about
    from test_seller_orders_postgres import paid_order

    async with isolated_pg() as (_, sessions):
        buyer, _, _, deal = await paid_order(sessions)
        # Same real isolated identities purchase a second car; it remains paid,
        # and must not increase the successful-deals public statistic.
        await paid_order(sessions)
        async with sessions() as session, session.begin():
            row = await session.get(Deal, deal.id)
            row.status = "completed"
            row.completed_at = vip.now_utc()
            session.add(User(id=uuid.uuid4(), telegram_id=-1, first_name="Not a validated Telegram user"))
            (await session.get(User, buyer.id)).photo_url = "https://example.com/visitor-avatar.jpg"
        application = client_app(sessions)
        application.include_router(about.router)
        monkeypatch.setattr(about, "get_settings", lambda: Settings(about_founder_photo_url="https://example.com/founder.jpg"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(application), base_url="http://isolated") as client:
            assert (await client.get("/api/about")).status_code == 401
            result = await client.get("/api/about", headers=headers(buyer))
            assert result.status_code == 200 and "no-store" in result.headers["cache-control"]
            assert result.json()["users"] == 2 and result.json()["completed_deals"] == 1
            assert result.json()["statistics_source"] == "database"
            assert result.json()["founder"]["photo_url"] == "https://example.com/founder.jpg"
            assert "visitor-avatar" not in result.text and "telegram_id" not in result.text
            async with sessions() as session, session.begin():
                (await session.get(Deal, deal.id)).cancelled_at = vip.now_utc()
            assert (await client.get("/api/about", headers=headers(buyer))).json()["completed_deals"] == 0
