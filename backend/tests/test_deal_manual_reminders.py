import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.deal_reminders import manual_receipt_pause_until, request_reminder
from app.message_notifications import claim_delivery
from app.models import Deal, DealEvent, Notification, Wallet, WalletTransaction
from app.services import save_deal_delivery_details, set_deal_status
from test_referral_bonus_postgres import isolated_pg
from test_seller_orders_postgres import paid_order


@pytest.mark.asyncio
async def test_manual_id_reminder_atomic_replay_cooldown_and_no_money():
    async with isolated_pg() as (_, sessions):
        buyer,seller,listing,deal=await paid_order(sessions)
        async with sessions() as session:
            await set_deal_status(session,seller,deal.id,"seller_contacted")
        key=uuid.uuid4()
        async def send(actor=seller,request_id=key):
            async with sessions() as session:
                return await request_reminder(session,actor,deal.id,"id",request_id)
        results=await asyncio.gather(*[send() for _ in range(10)])
        assert sum(not item["replayed"] for item in results)==1
        with pytest.raises(HTTPException) as error:
            await send(request_id=uuid.uuid4())
        assert error.value.status_code==429 and int(error.value.headers["Retry-After"])>0
        for actor in (buyer,SimpleNamespace(id=uuid.uuid4())):
            with pytest.raises(HTTPException) as error:
                await send(actor)
            assert error.value.status_code==403
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(DealEvent).where(DealEvent.event_type=="manual_id_reminder"))==1
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type=="deal_manual_reminder"))==1
            wallet=await session.scalar(select(Wallet).where(Wallet.user_id==seller.id))
            assert wallet.earned_balance==0
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.user_id==seller.id))==0
        async with sessions() as session:
            await save_deal_delivery_details(session,buyer,deal.id,"ABC123")
        with pytest.raises(HTTPException) as error:
            await send(request_id=uuid.uuid4())
        assert error.value.status_code==409
        async with sessions() as session:
            await claim_delivery(session,buyer.id,datetime.now(UTC))
        async with sessions() as session:
            notice=await session.scalar(select(Notification).where(Notification.notification_type=="deal_manual_reminder"))
            assert notice.delivery_status=="suppressed"


@pytest.mark.asyncio
async def test_manual_receipt_reuses_already_queued_automatic_reminder():
    async with isolated_pg() as (_, sessions):
        buyer,seller,listing,deal=await paid_order(sessions)
        async with sessions() as session:
            with pytest.raises(HTTPException) as error:
                await request_reminder(session,seller,deal.id,"receipt",uuid.uuid4())
            assert error.value.status_code==409
        async with sessions() as session:
            await set_deal_status(session,seller,deal.id,"seller_contacted")
        async with sessions() as session:
            await save_deal_delivery_details(session,buyer,deal.id,"AB123")
        async with sessions() as session:
            await set_deal_status(session,seller,deal.id,"transfer_in_progress")
        async with sessions() as session:
            await request_reminder(session,seller,deal.id,"receipt",uuid.uuid4())
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type=="deal_manual_reminder"))==0
            event=await session.scalar(select(DealEvent).where(DealEvent.event_type=="manual_receipt_reminder"))
            assert event.details["automatic_already_queued"] is True


@pytest.mark.asyncio
async def test_manual_reminder_notification_opens_the_exact_deal():
    async with isolated_pg() as (_, sessions):
        buyer,seller,listing,deal=await paid_order(sessions)
        async with sessions() as session:
            await set_deal_status(session,seller,deal.id,"seller_contacted")
        async with sessions() as session:
            await request_reminder(session,seller,deal.id,"id",uuid.uuid4())
        async with sessions() as session, session.begin():
            await session.execute(update(Notification).where(Notification.notification_type!="deal_manual_reminder")
                .values(delivery_status="not_required"))
        async with sessions() as session:
            job=await claim_delivery(session,buyer.id,datetime.now(UTC))
        assert job["params"]=={"deal_id":str(deal.id)}
        assert job["notification_type"]=="deal_manual_reminder"
        assert "игровой ID" in job["text"]


@pytest.mark.asyncio
async def test_pending_reuse_and_automatic_cooldown_after_actual_manual_delivery():
    async with isolated_pg() as (_, sessions):
        buyer,seller,listing,deal=await paid_order(sessions)
        async with sessions() as session:
            await set_deal_status(session,seller,deal.id,"seller_contacted")
        async with sessions() as session:
            await save_deal_delivery_details(session,buyer,deal.id,"AB123")
        async with sessions() as session:
            await set_deal_status(session,seller,deal.id,"transfer_in_progress")
        now=datetime.now(UTC)
        async with sessions() as session, session.begin():
            stored=await session.get(Deal,deal.id)
            stored.buyer_transfer_reminder_scheduled_at=now+timedelta(minutes=5)
        async with sessions() as session:
            await request_reminder(session,seller,deal.id,"receipt",uuid.uuid4())
        # Isolated fixture ages the request while its message remains queued.
        async with sessions() as session, session.begin():
            await session.execute(update(DealEvent).where(DealEvent.event_type=="manual_receipt_reminder")
                .values(created_at=now-timedelta(hours=2)))
        async with sessions() as session:
            await request_reminder(session,seller,deal.id,"receipt",uuid.uuid4())
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type=="deal_manual_reminder"))==1
            stored=await session.get(Deal,deal.id)
            assert await manual_receipt_pause_until(session,stored,now)>=now+timedelta(hours=1)
        async with sessions() as session, session.begin():
            await session.execute(update(Notification).where(Notification.notification_type=="deal_manual_reminder")
                .values(delivery_status="sent",delivery_sent_at=now))
        async with sessions() as session:
            stored=await session.get(Deal,deal.id)
            assert await manual_receipt_pause_until(session,stored,now+timedelta(minutes=50))==now+timedelta(hours=1)
            assert await manual_receipt_pause_until(session,stored,now+timedelta(hours=2)) is None
