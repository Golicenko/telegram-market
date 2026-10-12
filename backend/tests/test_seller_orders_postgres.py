"""Seller progress: real PostgreSQL transactions, no production/Telegram requests."""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import func, select, text

from app.config import Settings
from app.models import Deal, DealEvent, Listing, Notification, User, Wallet, WalletTransaction
from app.message_notifications import claim_delivery
from app.seller_orders import queue_seller_order_reminder, recover_seller_order_reminders
from app.services import (purchase_listing, set_deal_status, save_deal_delivery_details,
    send_conversation_message, auto_cancel_undelivered_deal)
from test_referral_bonus_postgres import isolated_pg, signed_login, apply_revisions


async def paid_order(sessions):
    buyer = await signed_login(sessions, 9701)
    seller = await signed_login(sessions, 9702)
    async with sessions() as session, session.begin():
        for user in (buyer, seller):
            (await session.get(User, user.id)).bot_started = True
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        wallet.purchased_balance = 100
        listing = Listing(seller_id=seller.id, game_version="car_parking_2", listing_type="regular",
            status="active", brand="Car", model="Test", power_hp=1, max_speed_kph=1,
            description="Isolated test", price_af_coins=100)
        session.add(listing)
    async with sessions() as session:
        deal, _, _ = await purchase_listing(session, buyer, listing.id)
    return buyer, seller, listing, deal


@pytest.mark.asyncio
async def test_paid_order_notifies_before_id_once_and_routes_to_deal():
    async with isolated_pg() as (_, sessions):
        buyer, seller, listing, deal = await paid_order(sessions)
        async with sessions() as session:
            retry, _, created = await purchase_listing(session, buyer, listing.id)
            assert retry.id == deal.id and not created
        async with sessions() as session:
            stored = await session.get(Deal, deal.id)
            assert stored.buyer_game_id is None
            assert stored.seller_purchase_notification_status == "outbox"
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "deal_created")) == 1
        async with sessions() as session:
            job = await claim_delivery(session, seller.id, datetime.now(UTC))
        assert job["params"] == {"deal_id": str(deal.id)}
        assert "Car Parking 2" in job["text"] and "100" in job["text"]
        assert "Срок передачи:" in job["text"] and "UTC" in job["text"]
        async with sessions() as session:
            await save_deal_delivery_details(session, buyer, deal.id, "AB123456")
        async with sessions() as session:
            await save_deal_delivery_details(session, buyer, deal.id, "AB123456")
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "conversation_message")) == 1
            assert (await session.get(Deal, deal.id)).seller_purchase_notification_status == "outbox"


@pytest.mark.asyncio
async def test_parallel_acceptance_once_no_money_no_timer_extension_and_refund_at_24h():
    from app.routes import seller_contacted
    async with isolated_pg() as (_, sessions):
        buyer, seller, listing, deal = await paid_order(sessions)
        deadline = deal.seller_delivery_deadline

        async def accept():
            tasks = BackgroundTasks()
            async with sessions() as session:
                result = await seller_contacted(deal.id, tasks, seller, session)
                assert not tasks.tasks  # No duplicate legacy direct-send side effect.
                return result

        # Acceptance must not reverse the purchase's Listing -> Deal lock order.
        async with sessions() as session, session.begin():
            await session.scalar(select(Listing).where(Listing.id == listing.id).with_for_update())
            results = await asyncio.wait_for(asyncio.gather(*(accept() for _ in range(8))), 20)
        assert all(r.status == "seller_contacted" and r.seller_accepted_at for r in results)
        assert len({r.seller_accepted_at for r in results}) == 1
        async with sessions() as session:
            stored = await session.get(Deal, deal.id)
            assert stored.seller_delivery_deadline == deadline
            assert stored.transfer_started_at is None
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))).frozen_balance == 100
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).available_balance == 0
            assert await session.scalar(select(func.count()).select_from(DealEvent).where(DealEvent.event_type == "seller_order_accepted")) == 1
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "seller_order_accepted")) == 1
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 1
        async with sessions() as session:
            job = await claim_delivery(session, buyer.id, datetime.now(UTC))
            assert job["params"] == {"deal_id": str(deal.id)} and "Продавец принял" in job["text"]

        async def timeout():
            async with sessions() as session:
                return await auto_cancel_undelivered_deal(session, deal.id, now=deadline + timedelta(seconds=1))
        assert sum(await asyncio.gather(*(timeout() for _ in range(8)))) == 1
        async with sessions() as session:
            stored = await session.get(Deal, deal.id)
            assert stored.status == "cancelled" and stored.cancellation_reason == "delivery_timeout"
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))).available_balance == 100
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "refund")) == 1
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "sale_income")) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["buyer", "stranger", "unpaid", "no_hold", "cancelled", "completed", "expired"])
async def test_acceptance_rejects_wrong_actor_or_invalid_order(case):
    async with isolated_pg() as (_, sessions):
        buyer, seller, _, deal = await paid_order(sessions)
        actor = buyer if case == "buyer" else seller
        if case == "stranger":
            actor = await signed_login(sessions, 9703)
        async with sessions() as session, session.begin():
            stored = await session.get(Deal, deal.id)
            if case == "unpaid":
                stored.status = "pending_payment"
            elif case == "no_hold":
                wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
                wallet.purchased_frozen_balance = 0
            elif case in {"cancelled", "completed"}:
                stored.status = case
            elif case == "expired":
                stored.seller_delivery_deadline = datetime.now(UTC) - timedelta(seconds=1)
        async with sessions() as session:
            with pytest.raises(HTTPException) as error:
                await set_deal_status(session, actor, deal.id, "seller_contacted")
            assert error.value.status_code == (403 if case in {"buyer", "stranger"} else 409)
        async with sessions() as session:
            assert (await session.get(Deal, deal.id)).seller_accepted_at is None
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "seller_order_accepted")) == 0


@pytest.mark.asyncio
async def test_reminders_restart_concurrency_and_missed_slots_coalesce(monkeypatch):
    monkeypatch.setattr("app.seller_orders.get_settings", lambda: Settings(seller_order_reminder_seconds=[2, 12, 23]))
    async with isolated_pg() as (_, sessions):
        _, _, _, deal = await paid_order(sessions)
        async def queue(seconds):
            async with sessions() as session:
                return await queue_seller_order_reminder(session, deal.id, deal.created_at + timedelta(seconds=seconds))
        assert not await queue(1)
        assert sum(await asyncio.gather(*(queue(2) for _ in range(8)))) == 1
        # New connections after downtime are the restart analogue; skip missed 12s slot.
        assert await queue(23)
        assert not await queue(23)
        async with sessions() as session:
            stored = await session.get(Deal, deal.id)
            assert stored.seller_reminder_stage == 3
            assert stored.seller_delivery_deadline == deal.seller_delivery_deadline
            notices = list((await session.scalars(select(Notification).where(Notification.notification_type == "seller_order_reminder"))).all())
            assert sorted(n.payload["stage"] for n in notices) == [1, 3]
            assert {n.payload["stage"]: n.delivery_status for n in notices} == {1: "suppressed", 3: "pending"}
            assert await session.scalar(select(func.count()).select_from(DealEvent).where(DealEvent.event_type == "seller_reminder_queued")) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["accept", "message", "dispute", "expiry"])
async def test_response_or_terminal_state_suppresses_queued_and_future_reminders(response, monkeypatch):
    monkeypatch.setattr("app.seller_orders.get_settings", lambda: Settings(seller_order_reminder_seconds=[2, 12, 23]))
    async with isolated_pg() as (_, sessions):
        _, seller, _, deal = await paid_order(sessions)
        async with sessions() as session, session.begin():
            # Initial notice was delivered; focus on a previously queued reminder.
            notice = await session.scalar(select(Notification).where(Notification.notification_type == "deal_created"))
            notice.delivery_status = "sent"
        async with sessions() as session:
            assert await queue_seller_order_reminder(session, deal.id, deal.created_at + timedelta(seconds=2))
        async with sessions() as session:
            if response == "accept":
                await set_deal_status(session, seller, deal.id, "seller_contacted")
            elif response == "message":
                await send_conversation_message(session, seller, deal.conversation_id, "Готов передать", uuid.uuid4(), deal.id)
            else:
                async with session.begin():
                    stored = await session.get(Deal, deal.id)
                    if response == "dispute":
                        stored.status = "disputed"
                    else:
                        stored.seller_delivery_deadline = datetime.now(UTC) - timedelta(seconds=1)
        async with sessions() as session:
            assert not await queue_seller_order_reminder(session, deal.id, deal.created_at + timedelta(seconds=23))
        async with sessions() as session:
            assert await claim_delivery(session, seller.id, datetime.now(UTC)) is None
        async with sessions() as session:
            notice = await session.scalar(select(Notification).where(Notification.notification_type == "seller_order_reminder"))
            assert notice.delivery_status == "suppressed"


@pytest.mark.asyncio
async def test_worker_recovers_due_reminder_without_telegram_or_financial_effect(monkeypatch):
    monkeypatch.setattr("app.seller_orders.get_settings", lambda: Settings(seller_order_reminder_seconds=[2, 12, 23]))
    async with isolated_pg() as (_, sessions):
        monkeypatch.setattr("app.database.SessionLocal", sessions)
        _, seller, _, deal = await paid_order(sessions)
        async with sessions() as session, session.begin():
            stored = await session.get(Deal, deal.id)
            stored.created_at = datetime.now(UTC) - timedelta(seconds=24)
        await recover_seller_order_reminders()
        await recover_seller_order_reminders()
        async with sessions() as session:
            assert (await session.get(Deal, deal.id)).seller_reminder_stage == 3
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 1
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "seller_order_reminder")) == 1
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).available_balance == 0


@pytest.mark.asyncio
async def test_migration_preserves_historical_order_deadline_and_money():
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: apply_revisions(sync, target="0045_withdrawal_public_numbers"))
            buyer, seller, listing, deal = (uuid.uuid4() for _ in range(4))
            for uid, tid in ((buyer, 9801), (seller, 9802)):
                await conn.execute(text("INSERT INTO users(id,telegram_id,first_name) VALUES (:u,:tid,'Test')"), {"u":uid,"tid":tid})
            await conn.execute(text("INSERT INTO listings(id,seller_id,game_version,listing_type,status,brand,model,power_hp,max_speed_kph,description,price_af_coins) VALUES (:id,:seller,'car_parking_1','regular','reserved','Car','Test',1,1,'Test',100)"), {"id":listing,"seller":seller})
            await conn.execute(text("INSERT INTO deals(id,listing_id,buyer_id,seller_id,status,price_af_coins,frozen_amount,purchased_frozen_amount,seller_payout,platform_commission,seller_delivery_deadline,seller_purchase_notification_status) VALUES (:id,:listing,:buyer,:seller,'seller_contacted',100,100,100,70,30,'2026-01-02T00:00:00Z','sent')"), {"id":deal,"listing":listing,"buyer":buyer,"seller":seller})
            await conn.run_sync(lambda sync: apply_revisions(sync, target="head", after="0045_withdrawal_public_numbers"))
            row = (await conn.execute(text("SELECT seller_accepted_at,seller_reminder_stage,seller_delivery_deadline,frozen_amount,seller_purchase_notification_status FROM deals WHERE id=:id"), {"id":deal})).one()
            assert row == (None, 0, datetime(2026,1,2,tzinfo=UTC), 100, "sent")
            await conn.execute(text("UPDATE deals SET seller_purchase_notification_status='outbox' WHERE id=:id"), {"id":deal})


@pytest.mark.parametrize("offsets", [[0], [86400], [12, 2], [2, 2], [1, 2, 3, 4]])
def test_reminder_configuration_rejects_unbounded_schedule(offsets):
    with pytest.raises(ValueError):
        Settings(seller_order_reminder_seconds=offsets)


def test_reminder_configuration_can_be_disabled():
    assert Settings(seller_order_reminder_seconds=[]).seller_order_reminder_seconds == []
