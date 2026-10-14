import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import promotions
from app.config import Settings
from app.models import Listing, ListingPromotion, Notification, StarPayment, Wallet, WalletTransaction
from app.schemas import ListingCreate
from test_catalog_and_acceptance_postgres import client_app, headers
from test_referral_bonus_postgres import isolated_pg, signed_login


async def setup(sessions, balance=2, *, bonus=0, game="car_parking_1"):
    seller = await signed_login(sessions, 980001)
    async with sessions() as session, session.begin():
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
        wallet.purchased_balance, wallet.bonus_balance = balance, bonus
        listing = Listing(seller_id=seller.id, game_version=game, listing_type="regular", status="active",
            brand="BMW", model="M5", power_hp=600, max_speed_kph=300, description="Test", price_af_coins=100)
        session.add(listing)
    return seller, listing


def payment(order, suffix="first"):
    return {"currency": "XTR", "total_amount": order.stars, "invoice_payload": promotions.PREFIX + str(order.id),
            "telegram_payment_charge_id": str(order.id) + suffix}


async def start(sessions, seller, listing, request_id=None):
    async with sessions() as session:
        return await promotions.start_order(session, seller, promotions.Start(request_id=request_id or uuid.uuid4(), listing_id=listing.id))


async def receive(sessions, seller, order, suffix="first"):
    async with sessions() as session:
        return await promotions.receive_payment(session, seller.telegram_id, payment(order, suffix))


async def fulfill(sessions, order):
    async with sessions() as session:
        await promotions.fulfill(session, order.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("balance,stars,remaining", [(0, 5, 0), (2, 3, 0), (4, 1, 0), (5, 0, 0), (10, 0, 5), (Decimal("2.50"), 3, Decimal("0.50"))])
@pytest.mark.parametrize("game", ["car_parking_1", "car_parking_2"])
async def test_exact_split_receipt_replay_atomic_activation_and_duration(balance, stars, remaining, game):
    async with isolated_pg() as (_, sessions):
        seller, listing = await setup(sessions, balance, game=game)
        order = await start(sessions, seller, listing)
        assert order.stars == stars and order.balance_af == min(balance, 5)
        async with sessions() as session:
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert wallet.available_balance + wallet.frozen_balance == balance
            assert not (await session.get(Listing, listing.id)).pinned
        if stars:
            results = await asyncio.gather(*[receive(sessions, seller, order) for _ in range(3)])
            assert results == [order.id] * 3
        await asyncio.gather(*[fulfill(sessions, order) for _ in range(3)])
        async with sessions() as session:
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert wallet.available_balance == remaining and wallet.frozen_balance == 0
            stored = await session.get(Listing, listing.id)
            assert stored.pinned and 86300 < (stored.pinned_until - datetime.now(UTC)).total_seconds() <= 86400
            expiry = stored.pinned_until
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "listing_promotion")) == 1
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "vip_completed")) == 1
            assert await session.scalar(select(func.count()).select_from(StarPayment)) == (1 if stars else 0)
        await fulfill(sessions, order)  # New session simulates restart, not an in-memory timer.
        async with sessions() as session:
            assert (await session.get(Listing, listing.id)).pinned_until == expiry


@pytest.mark.asyncio
async def test_two_devices_one_invoice_and_precheckout_claim(monkeypatch):
    async with isolated_pg() as (_, sessions):
        seller, listing = await setup(sessions)
        orders = await asyncio.gather(*[start(sessions, seller, listing) for _ in range(4)])
        assert len({o.id for o in orders}) == 1
        sent = []
        async def bot(method, body):
            sent.append((method, body))
            return {"ok": True, "result": "https://t.me/$test-vip"}
        monkeypatch.setattr(promotions, "call_bot_api", bot)
        async def invoice():
            async with sessions() as session:
                await promotions.invoice(session, orders[0].id)
        await asyncio.gather(invoice(), invoice(), invoice())
        assert len(sent) == 1 and sent[0][1]["prices"][0]["amount"] == 3
        async def checkout(query_id):
            async with sessions() as session:
                return await promotions.validate_checkout(session, seller.telegram_id, promotions.PREFIX + str(orders[0].id), "XTR", 3, query_id)
        assert (await checkout("q1"))[0]
        assert (await checkout("q1"))[0]
        assert not (await checkout("q2"))[0]


@pytest.mark.asyncio
async def test_cancel_failure_expiry_bonus_and_late_success(monkeypatch):
    async with isolated_pg() as (_, sessions):
        seller, listing = await setup(sessions, balance=0, bonus=2)
        order = await start(sessions, seller, listing)
        assert order.funding["bonus"] == "2.00"
        async with sessions() as session:
            await promotions.cancel(order.id, seller, session)
        async with sessions() as session:
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert wallet.bonus_balance == 2 and wallet.frozen_balance == 0
        await receive(sessions, seller, order)
        await fulfill(sessions, order)
        async with sessions() as session:
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert wallet.bonus_balance == 2 and wallet.purchased_balance == 3 and wallet.earned_balance == 0
            assert (await session.get(ListingPromotion, order.id)).status == "restored"
            assert not (await session.get(Listing, listing.id)).pinned
        # Another order with a zero-balance wallet is cancelled automatically on expiry.
        async with sessions() as session, session.begin():
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            wallet.purchased_balance = 0
        next_order = await start(sessions, seller, listing)
        async with sessions() as session, session.begin():
            (await session.get(ListingPromotion, next_order.id)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
        monkeypatch.setattr(promotions, "SessionLocal", sessions)
        await promotions.recover_once()
        async with sessions() as session:
            assert (await session.get(ListingPromotion, next_order.id)).status == "cancelled"
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).bonus_balance == 2


@pytest.mark.asyncio
async def test_paid_crash_recovery_unavailable_listing_and_extra_charge(monkeypatch):
    async with isolated_pg() as (_, sessions):
        seller, listing = await setup(sessions)
        order = await start(sessions, seller, listing)
        await receive(sessions, seller, order)  # Crash here, BEFORE activation.
        async with sessions() as session:
            assert (await session.get(ListingPromotion, order.id)).status == "paid"
        monkeypatch.setattr(promotions, "SessionLocal", sessions)
        await promotions.recover_once()
        await promotions.recover_once()
        await receive(sessions, seller, order, "second-charge")
        refunded = []
        async def refund(method, body):
            refunded.append((method, body))
            return {"ok": True, "result": True}
        monkeypatch.setattr(promotions, "call_bot_api", refund)
        await promotions.recover_once()
        await promotions.recover_once()
        assert len(refunded) == 1 and refunded[0][0] == "refundStarPayment"
        async with sessions() as session, session.begin():
            stored = await session.get(Listing, listing.id)
            stored.pinned_until = datetime.now(UTC) - timedelta(hours=1)
            (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).purchased_balance = 2
        second = await start(sessions, seller, listing)
        await receive(sessions, seller, second)
        async with sessions() as session, session.begin():
            (await session.get(Listing, listing.id)).status = "deleted"
        await fulfill(sessions, second)
        async with sessions() as session:
            assert (await session.get(ListingPromotion, second.id)).status == "restored"
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert wallet.available_balance == 5 and wallet.frozen_balance == 0


@pytest.mark.asyncio
async def test_unpaid_and_forged_payment_and_permissions():
    async with isolated_pg() as (_, sessions):
        seller, listing = await setup(sessions)
        stranger = await signed_login(sessions, 980002)
        order = await start(sessions, seller, listing)
        await fulfill(sessions, order)  # Frontend says paid; backend does not.
        for change in ({"is_test": True}, {"total_amount": 1}, {"currency": "USD"}):
            async with sessions() as session, pytest.raises(HTTPException):
                await promotions.receive_payment(session, seller.telegram_id, {**payment(order), **change})
        app = client_app(sessions)
        app.include_router(promotions.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(f"/api/vip/orders/{order.id}", headers=headers(stranger))).status_code == 404
            assert (await client.post(f"/api/vip/orders/{order.id}/cancel", headers=headers(stranger))).status_code == 404
            assert (await client.get("/api/admin/vip/orders", headers=headers(seller))).status_code == 403
            assert (await client.post("/api/vip/orders", headers=headers(stranger), json={"request_id": str(uuid.uuid4()), "listing_id": str(listing.id)})).status_code == 404
        async with sessions() as session:
            assert not (await session.get(Listing, listing.id)).pinned
            assert await session.scalar(select(func.count()).select_from(StarPayment)) == 0


@pytest.mark.asyncio
async def test_new_publication_and_pin_commit_together():
    async with isolated_pg() as (_, sessions):
        seller, _ = await setup(sessions)
        payload = ListingCreate(client_request_id=uuid.uuid4(), game_version="car_parking_2", brand="BMW", model="M5",
            power_hp=600, max_speed_kph=300, description="Test listing", price_af_coins=50,
            image_urls=["https://example.com/car.jpg"], promote_for_24h=True)
        async with sessions() as session:
            order = await promotions.start_order(session, seller, promotions.Start(request_id=uuid.uuid4(), listing_payload=payload))
        await receive(sessions, seller, order)
        await fulfill(sessions, order)
        await fulfill(sessions, order)
        async with sessions() as session:
            stored = await session.get(ListingPromotion, order.id)
            assert stored.status == "completed"
            listing = await session.get(Listing, stored.listing_id)
            assert listing.pinned and listing.client_request_id == payload.client_request_id
            assert await session.scalar(select(func.count()).select_from(Listing).where(Listing.client_request_id == payload.client_request_id)) == 1


def test_config_drives_quote_not_client_and_bonus_is_spendable(monkeypatch):
    monkeypatch.setattr(promotions, "get_settings", lambda: Settings(listing_promotion_cost_af_coins=7, listing_promotion_hours=12))
    assert promotions.quote_values(2) == {"cost_af": Decimal("7.00"), "balance_af": Decimal("2.00"), "stars": 5,
        "duration_hours": 12, "af_per_star": 1, "rounding_credit_af": Decimal("0.00")}
