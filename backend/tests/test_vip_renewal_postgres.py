"""Isolated PostgreSQL tests, never a real Telegram charge or production mutation."""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import message_notifications as delivery, promotions
from app.models import Listing, ListingPromotion, Notification, VipExpiry, Wallet, WalletTransaction
from test_referral_bonus_postgres import isolated_pg, signed_login
from test_vip_orders_postgres import setup, receive, fulfill


async def expired(sessions, monkeypatch, balance=4, game="car_parking_1"):
    seller, listing = await setup(sessions, balance, game=game)
    async with sessions() as session, session.begin():
        row = await session.get(Listing, listing.id)
        row.pinned = True
        row.pinned_until = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(promotions, "SessionLocal", sessions)
    # Market reads can expire priority before the worker wakes. They must not
    # erase the stored period or swallow its notification.
    from app.routes import expire_promotions
    async with sessions() as session:
        await expire_promotions(session)
    await asyncio.gather(promotions.expire_once(), promotions.expire_once())
    async with sessions() as session:
        expiry = await session.scalar(select(VipExpiry))
    return seller, listing, expiry


async def renew(sessions, seller, listing, expiry, request_id=None):
    async with sessions() as session:
        return await promotions.start_order(session, seller, promotions.Start(
            request_id=request_id or uuid.uuid4(), listing_id=listing.id, renewal_id=expiry.id))


@pytest.mark.asyncio
@pytest.mark.parametrize("balance,stars", [(0, 10), (4, 6), (10, 0), (20, 0)])
@pytest.mark.parametrize("game", ["car_parking_1", "car_parking_2"])
async def test_legacy_expiry_once_renewal_split_replay_and_new_period(monkeypatch, balance, stars, game):
    async with isolated_pg() as (_, sessions):
        seller, listing, expiry = await expired(sessions, monkeypatch, balance, game)
        await promotions.expire_once()  # restart: old DB period, not an in-memory flag
        async with sessions() as session:
            row = await session.get(Listing, listing.id)
            assert row.status == "active" and not row.pinned and row.deleted_at is None
            assert await session.scalar(select(func.count()).select_from(VipExpiry)) == 1
            notice = await session.scalar(select(Notification).where(Notification.notification_type == "vip_expired"))
            assert notice.payload == {"renewal_id": str(expiry.id), "listing_id": str(listing.id)}
            assert "BMW M5" in notice.body and "10 ⭐" in notice.body and "3 дня" in notice.body
        orders = await asyncio.gather(*[renew(sessions, seller, listing, expiry) for _ in range(3)])
        assert len({order.id for order in orders}) == 1
        order = orders[0]
        assert order.cost_af == 10 and order.stars == stars and order.duration_hours == 72
        if stars:
            await asyncio.gather(*[receive(sessions, seller, order) for _ in range(3)])
        await asyncio.gather(*[fulfill(sessions, order) for _ in range(3)])
        async with sessions() as session:
            row = await session.get(Listing, listing.id)
            assert row.status == "active" and row.pinned
            assert 259100 < (row.pinned_until - datetime.now(UTC)).total_seconds() <= 259200
            assert (await session.get(VipExpiry, expiry.id)).redeemed_at
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert wallet.frozen_balance == 0 and wallet.available_balance == max(0, balance - 10)
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(
                WalletTransaction.transaction_type == "listing_promotion")) == 1
        with pytest.raises(HTTPException) as error:
            await renew(sessions, seller, listing, expiry)
        assert error.value.status_code == 409 and error.value.detail == "VIP уже активен"
        async with sessions() as session, session.begin():
            (await session.get(Listing, listing.id)).pinned_until = datetime.now(UTC) - timedelta(seconds=1)
        await promotions.expire_once()
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(VipExpiry)) == 2
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "vip_expired")) == 2
        with pytest.raises(HTTPException):
            await renew(sessions, seller, listing, expiry)  # old invitation cannot pay for a new period


@pytest.mark.asyncio
async def test_foreign_sold_deleted_precheckout_and_postreceipt_restoration(monkeypatch):
    async with isolated_pg() as (_, sessions):
        seller, listing, expiry = await expired(sessions, monkeypatch)
        stranger = await signed_login(sessions, 980002)
        with pytest.raises(HTTPException) as error:
            await renew(sessions, stranger, listing, expiry)
        assert error.value.status_code == 404
        async with sessions() as session:
            with pytest.raises(HTTPException):
                await promotions.renewal_quote(expiry.id, stranger, session)
        order = await renew(sessions, seller, listing, expiry)
        async with sessions() as session, session.begin():
            (await session.get(Listing, listing.id)).status = "sold"
        async with sessions() as session:
            allowed, _ = await promotions.validate_checkout(session, seller.telegram_id, promotions.PREFIX + str(order.id), "XTR", 6, "query")
            assert not allowed
        # A genuine delayed receipt must still be recorded; unavailable car never pinned.
        await receive(sessions, seller, order)
        await fulfill(sessions, order)
        async with sessions() as session:
            assert (await session.get(ListingPromotion, order.id)).status == "restored"
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert wallet.available_balance == 10 and wallet.frozen_balance == 0
            assert not (await session.get(Listing, listing.id)).pinned
        with pytest.raises(HTTPException):
            await renew(sessions, seller, listing, expiry)
        async with sessions() as session, session.begin():
            row = await session.get(Listing, listing.id)
            row.status = "active"
            row.deleted_at = datetime.now(UTC)
        with pytest.raises(HTTPException):
            await renew(sessions, seller, listing, expiry)


@pytest.mark.asyncio
async def test_cancel_no_pin_no_final_debit_and_retry(monkeypatch):
    async with isolated_pg() as (_, sessions):
        seller, listing, expiry = await expired(sessions, monkeypatch)
        order = await renew(sessions, seller, listing, expiry)
        async with sessions() as session:
            await promotions.cancel(order.id, seller, session)
        await fulfill(sessions, order)
        async with sessions() as session:
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert wallet.available_balance == 4 and wallet.frozen_balance == 0
            assert not (await session.get(Listing, listing.id)).pinned
        retry = await renew(sessions, seller, listing, expiry)
        assert retry.id != order.id and retry.stars == 6


@pytest.mark.asyncio
async def test_market_read_expires_priority_without_losing_worker_event(monkeypatch):
    from app.routes import list_listings
    async with isolated_pg() as (_, sessions):
        seller, listing = await setup(sessions)
        async with sessions() as session, session.begin():
            row = await session.get(Listing, listing.id)
            row.pinned = True
            row.pinned_until = datetime.now(UTC) - timedelta(seconds=1)
            row.created_at = datetime.now(UTC) - timedelta(days=1)
            newer = Listing(seller_id=seller.id, game_version="car_parking_2", listing_type="regular", status="active",
                brand="Newer", model="CP2", power_hp=100, max_speed_kph=200, description="Test", price_af_coins=100)
            session.add(newer)
        async with sessions() as session:
            rows = await list_listings("regular", None, None, None, None, None, seller, session)
            assert rows[0].id == newer.id
            assert rows[1].id == listing.id and not rows[1].pinned
        monkeypatch.setattr(promotions, "SessionLocal", sessions)
        await promotions.expire_once()
        async with sessions() as session:
            assert (await session.scalar(select(VipExpiry))).listing_id == listing.id


@pytest.mark.asyncio
async def test_outbox_claim_restart_and_stale_notification(monkeypatch):
    async with isolated_pg() as (_, sessions):
        seller, listing, expiry = await expired(sessions, monkeypatch, 10)
        from app.models import User
        async with sessions() as session, session.begin():
            (await session.get(User, seller.id)).bot_started = True
        async with sessions() as session:
            job = await delivery.claim_delivery(session, seller.id, datetime.now(UTC))
            assert job["params"] == {"vip_renewal": str(expiry.id)}
        async with sessions() as session:
            assert await delivery.claim_delivery(session, seller.id, datetime.now(UTC)) is None
        async with sessions() as session, session.begin():
            notice = await session.get(Notification, job["ids"][0])
            notice.delivery_status = "pending"  # definitive rejected send retry
        order = await renew(sessions, seller, listing, expiry)
        await fulfill(sessions, order)
        async with sessions() as session:
            next_job = await delivery.claim_delivery(session, seller.id, datetime.now(UTC))
            assert next_job["notification_type"] == "vip_completed"
        async with sessions() as session:
            assert (await session.get(Notification, job["ids"][0])).delivery_status == "suppressed"


@pytest.mark.asyncio
async def test_real_migration_retains_pin_and_supports_expiry(monkeypatch):
    from test_referral_bonus_postgres import apply_revisions
    async with isolated_pg(tables=False) as (engine, sessions):
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: apply_revisions(sync, target="0050_listing_promotions"))
        # Insert pre-upgrade rows without ORM querying the new column.
        from sqlalchemy import text
        uid, lid = uuid.uuid4(), uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO users(id,telegram_id,first_name,role) VALUES (:id,980009,'Legacy','user')"), {"id": uid})
            await conn.execute(text("INSERT INTO listings(id,seller_id,listing_type,status,brand,model,description,power_hp,max_speed_kph,price_af_coins,pinned,pinned_until,game_version) VALUES (:id,:seller,'regular','active','Legacy','CP2','Test',1,1,100,true,now()-interval '1 second','car_parking_2')"), {"id": lid, "seller": uid})
            active_id = uuid.uuid4()
            active_until = datetime.now(UTC) + timedelta(hours=13)
            await conn.execute(text("INSERT INTO listings(id,seller_id,listing_type,status,brand,model,description,power_hp,max_speed_kph,price_af_coins,pinned,pinned_until,game_version) VALUES (:id,:seller,'regular','active','Active','CP1','Test',1,1,55,true,:until,'car_parking_1')"), {"id": active_id, "seller": uid, "until": active_until})
            await conn.run_sync(lambda sync: apply_revisions(sync, target="head", after="0050_listing_promotions"))
        monkeypatch.setattr(promotions, "SessionLocal", sessions)
        await promotions.expire_once()
        async with sessions() as session:
            row = await session.get(Listing, lid)
            assert row.status == "active" and not row.pinned and row.price_af_coins == 100
            assert (await session.scalar(select(VipExpiry))).listing_id == lid
            active = await session.get(Listing, active_id)
            assert active.pinned and active.pinned_until == active_until and active.price_af_coins == 55


@pytest.mark.asyncio
async def test_disabled_notifications_and_exact_configured_period(monkeypatch):
    from app.config import Settings
    monkeypatch.setattr(promotions, "get_settings", lambda: Settings(vip_expiry_notifications_enabled=False,
        vip_renewal_price_stars=12, vip_renewal_hours=96))
    async with isolated_pg() as (_, sessions):
        seller, listing, expiry = await expired(sessions, monkeypatch, 20)
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Notification)) == 0
            quote = await promotions.renewal_quote(expiry.id, seller, session)
            assert quote["price_stars"] == 12 and quote["duration_hours"] == 96
        order = await renew(sessions, seller, listing, expiry)
        await fulfill(sessions, order)
        async with sessions() as session:
            row = await session.get(Listing, listing.id)
            assert 345500 < (row.pinned_until - datetime.now(UTC)).total_seconds() <= 345600
        await promotions.expire_once()  # Not 24h, and not blindly one fixed period.
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(VipExpiry)) == 1
