"""Real concurrent PostgreSQL requests, never a production database."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import Deal, DealEvent, Listing, Notification, User, Wallet, WalletTransaction
from app.services import complete_deal, purchase_listing, set_deal_status
from test_referral_bonus_postgres import isolated_pg, signed_login


@pytest.mark.asyncio
async def test_two_devices_transfer_and_receipt_transition_once_after_reconnect(monkeypatch):
    from app import routes
    from app.bot import BroadcastSendResult

    async with isolated_pg() as (_, sessions):
        monkeypatch.setattr(routes, "SessionLocal", sessions)
        sent = []

        async def send(telegram_id, **payload):
            sent.append((telegram_id, payload))
            return BroadcastSendResult(success=True)

        monkeypatch.setattr(routes, "send_deal_transfer_reminder", send)
        buyer = await signed_login(sessions, 801)
        seller = await signed_login(sessions, 802)
        async with sessions() as session, session.begin():
            (await session.get(User, buyer.id)).bot_started = True
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            wallet.purchased_balance = 100
            listing = Listing(seller_id=seller.id, game_version="car_parking_1",
                listing_type="regular", status="active", brand="Car", model="Test",
                power_hp=1, max_speed_kph=1, description="Test", price_af_coins=100)
            session.add(listing)
        async with sessions() as session:
            deal, _, _ = await purchase_listing(session, buyer, listing.id)
        async with sessions() as session, session.begin():
            stored = await session.get(Deal, deal.id)
            stored.buyer_game_id = "ab123456"
            stored.seller_response_deadline = datetime.now(UTC) + timedelta(hours=24)
            stored.seller_delivery_deadline = datetime.now(UTC) + timedelta(hours=24)

        async def transfer():
            async with sessions() as session:
                return await set_deal_status(session, seller, deal.id, "transfer_in_progress")

        # A purchase retry can hold Listing while waiting for Deal. The seller
        # transition must not take a reverse Deal -> Listing lock.
        async with sessions() as purchase_retry, purchase_retry.begin():
            await purchase_retry.scalar(select(Listing).where(Listing.id == listing.id).with_for_update())
            results = await asyncio.wait_for(asyncio.gather(*(transfer() for _ in range(8))), 20)
        assert all(result.status == "transfer_in_progress" for result in results)
        async with sessions() as session, session.begin():
            stored = await session.get(Deal, deal.id)
            assert stored.buyer_game_id == "ab123456"
            assert stored.seller_responded_at is not None
            assert stored.buyer_transfer_reminder_status == "pending"
            assert await session.scalar(select(func.count()).select_from(DealEvent).where(DealEvent.event_type == "seller_marked_transferred")) == 1
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "deal_status")) == 1
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "sale_income")) == 0
            bw = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            sw = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert bw.frozen_balance == 100 and sw.available_balance == 0
            stored.transfer_started_at = datetime.now(UTC) - timedelta(seconds=61)

        await asyncio.gather(*(routes.notify_deal_transfer_buyer(deal.id) for _ in range(4)))
        assert sent == [(buyer.telegram_id, {"deal_id": str(deal.id)})]

        async def receipt():
            async with sessions() as session:
                return await complete_deal(session, buyer, deal.id)

        results = await asyncio.wait_for(asyncio.gather(*(receipt() for _ in range(8))), 20)
        assert all(result.status == "completed" for result in results)
        # Another connection after the concurrent requests sees exactly one settlement.
        async with sessions() as session:
            stored = await session.get(Deal, deal.id)
            sw = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            bw = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            assert sw.available_balance == stored.seller_payout
            assert bw.frozen_balance == 0
            for model, condition in (
                (WalletTransaction, WalletTransaction.transaction_type == "sale_income"),
                (DealEvent, DealEvent.event_type == "buyer_confirmed"),
                (Notification, Notification.notification_type == "deal_completed"),
            ):
                assert await session.scalar(select(func.count()).select_from(model).where(condition)) == 1
