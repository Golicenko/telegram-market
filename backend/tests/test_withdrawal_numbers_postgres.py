"""Real sequence, migration, reservation and contact tests on disposable PostgreSQL."""
import asyncio
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, func

from app.models import GiftWithdrawalQuote, WithdrawalRequest, Wallet, WalletTransaction, Notification, SupportTicket
from app.gift_withdrawals import reserve_gift_withdrawal
from app.services import decide_withdrawal
from app.withdrawal_support import withdrawal_support_ticket
from test_referral_bonus_postgres import isolated_pg, signed_login, apply_revisions


@pytest.mark.asyncio
async def test_100_parallel_requests_unique_numbers_and_quote_replay(monkeypatch):
    async def catalog(): return [{"id": "gift15", "star_count": 15}]
    monkeypatch.setattr("app.gift_withdrawals.available_gifts", catalog)
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 9601)
        admin = await signed_login(sessions, 9602)
        from datetime import UTC, datetime, timedelta
        async with sessions() as session, session.begin():
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
            wallet.earned_balance = 3000
            stored_admin = await session.get(type(admin), admin.id)
            stored_admin.role = "admin"
            quotes = [GiftWithdrawalQuote(user_id=user.id, budget=30, gross_af=Decimal("21.43"),
                fee_af=Decimal("6.43"), payout_stars=15, gift_plan=[{"gift_id":"gift15","star_count":15,"quantity":1}],
                expires_at=datetime.now(UTC) + timedelta(minutes=5)) for _ in range(100)]
            session.add_all(quotes)
        async def reserve(quote):
            async with sessions() as session:
                return await reserve_gift_withdrawal(session, user, quote.id, "")
        requests = await asyncio.wait_for(asyncio.gather(*(reserve(q) for q in quotes)), 60)
        assert len({r.public_number for r in requests}) == 100
        assert sorted(r.public_number for r in requests) == list(range(1, 101))
        retries = await asyncio.gather(*(reserve(quotes[0]) for _ in range(10)))
        assert {r.id for r in retries} == {requests[0].id}
        admin.role = "admin"
        async def decide(action):
            async with sessions() as session:
                return await decide_withdrawal(session, admin, requests[0].id, action, None, "manual-test")
        await asyncio.gather(*(decide("approve") for _ in range(5)))
        await asyncio.gather(*(decide("paid") for _ in range(5)))
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(WithdrawalRequest)) == 100
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "withdrawal_paid")) == 1
            notices = list((await session.scalars(select(Notification).where(Notification.notification_type == "withdrawal_paid"))).all())
            assert len(notices) == 1 and requests[0].public_id in notices[0].body and "15 ⭐" in notices[0].body
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
            assert wallet.earned_balance == Decimal("857.00")
            assert wallet.earned_frozen_balance == Decimal("2121.57")
        async def contact(actor):
            async with sessions() as session:
                return await withdrawal_support_ticket(session, actor, requests[0].id)
        tickets = await asyncio.gather(*(contact(admin) for _ in range(5)))
        assert len({t.id for t in tickets}) == 1
        assert (await contact(user)).id == tickets[0].id
        stranger = await signed_login(sessions, 9603)
        with pytest.raises(HTTPException) as error:
            await contact(stranger)
        assert error.value.status_code == 404
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(SupportTicket)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("history", [False, True])
async def test_backfill_all_statuses_then_sequence_survives_rollback(history):
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: apply_revisions(sync, target="0044_admin_balance_idempotency"))
            uid = uuid.uuid4()
            await conn.execute(text("INSERT INTO users(id,telegram_id,first_name) VALUES (:u,9611,'History')"), {"u": uid})
            ids = [uuid.UUID(int=i) for i in range(1, 6)] if history else []
            for wid, status in zip(reversed(ids), ["paid", "cancelled", "rejected", "approved", "pending"]):
                await conn.execute(text("INSERT INTO withdrawal_requests(id,user_id,amount,payout_method,details,status,created_at) VALUES (:id,:u,42,'manual','History',:s,'2025-01-01')"), {"id": wid, "u": uid, "s": status})
            await conn.run_sync(lambda sync: apply_revisions(sync, target="head", after="0044_admin_balance_idempotency"))
            rows = list((await conn.execute(text("SELECT id,public_number,amount FROM withdrawal_requests ORDER BY public_number"))).all())
            assert rows == [(wid, i, Decimal(42)) for i, wid in enumerate(ids, 1)]
        insert = text("INSERT INTO withdrawal_requests(id,user_id,amount,payout_method,details,status) VALUES (:id,:u,42,'manual','New','pending') RETURNING public_number")
        async with engine.connect() as conn:
            rolled_number = await conn.scalar(insert, {"id": uuid.uuid4(), "u": uid})
            await conn.rollback()
        async with engine.begin() as conn:
            next_number = await conn.scalar(insert, {"id": uuid.uuid4(), "u": uid})
            assert next_number == rolled_number + 1 == len(ids) + 2
        async with engine.begin() as conn:
            # A fresh connection (restart analogue) continues the same DB sequence.
            assert await conn.scalar(insert, {"id": uuid.uuid4(), "u": uid}) == next_number + 1
