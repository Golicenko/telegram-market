"""Regression checks against disposable PostgreSQL schemas, never production."""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.models import AdminAction, AdminBalanceAdjustment, Deal, Listing, Wallet, WalletTransaction
from app.services import adjust_balance, complete_deal, purchase_listing, cancel_deal
from test_referral_bonus_postgres import isolated_pg, signed_login, apply_revisions


@pytest.mark.asyncio
async def test_parallel_admin_command_is_applied_once_and_collision_rejected():
    async with isolated_pg() as (_, sessions):
        admin = await signed_login(sessions, 911)
        buyer = await signed_login(sessions, 912)
        admin.role = "admin"
        payload = SimpleNamespace(user_id=buyer.id, request_id=uuid.uuid4(), amount=Decimal("100"), reason="Audit regression")

        async def execute(command):
            async with sessions() as session:
                return await adjust_balance(session, admin, command)

        await asyncio.wait_for(asyncio.gather(*(execute(payload) for _ in range(10))), 20)
        with pytest.raises(HTTPException) as conflict:
            await execute(SimpleNamespace(**{**vars(payload), "user_id": admin.id}))
        assert conflict.value.status_code == 409
        async with sessions() as session:
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            assert wallet.available_balance == 100
            for model in (AdminBalanceAdjustment, AdminAction, WalletTransaction):
                assert await session.scalar(select(func.count()).select_from(model)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["complete", "cancel"])
async def test_purchase_retry_and_financial_transition_have_compatible_lock_order(operation):
    async with isolated_pg() as (_, sessions):
        buyer = await signed_login(sessions, 921)
        seller = await signed_login(sessions, 922)
        async with sessions() as session, session.begin():
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            wallet.purchased_balance = 100
            listing = Listing(seller_id=seller.id, game_version="car_parking_1", listing_type="regular", status="active", brand="Test", model="Car", power_hp=1, max_speed_kph=1, description="Isolated test", price_af_coins=100)
            session.add(listing)
        async with sessions() as session:
            deal, _, _ = await purchase_listing(session, buyer, listing.id)
        if operation == "complete":
            async with sessions() as session, session.begin():
                stored = await session.get(Deal, deal.id)
                stored.status = "transfer_in_progress"
                stored.transfer_started_at = datetime.now(UTC) - timedelta(seconds=61)

        # Force purchase to hold Listing before settlement begins. Old code
        # locked Deal first and then waited for Listing: a real deadlock.
        async with sessions() as buying, sessions() as finishing:
            listing_locked, finish_first_read = asyncio.Event(), asyncio.Event()
            buy_scalar, finish_scalar = buying.scalar, finishing.scalar

            async def paused_buy(statement, *args, **kwargs):
                result = await buy_scalar(statement, *args, **kwargs)
                if isinstance(result, Listing) and not listing_locked.is_set():
                    listing_locked.set()
                    await finish_first_read.wait()
                return result

            async def observed_finish(statement, *args, **kwargs):
                result = await finish_scalar(statement, *args, **kwargs)
                finish_first_read.set()
                return result

            buying.scalar, finishing.scalar = paused_buy, observed_finish
            retry = asyncio.create_task(purchase_listing(buying, buyer, listing.id))
            await asyncio.wait_for(listing_locked.wait(), 5)
            action = complete_deal if operation == "complete" else cancel_deal
            results = await asyncio.wait_for(asyncio.gather(retry, action(finishing, buyer, deal.id)), 20)
            assert results[0][2] is False
        async with sessions() as session:
            stored = await session.get(Deal, deal.id)
            assert stored.status == ("completed" if operation == "complete" else "cancelled")
            bw = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            sw = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert bw.frozen_balance == 0
            assert bw.available_balance == (0 if operation == "complete" else 100)
            assert sw.available_balance == (100 if operation == "complete" else 0)


@pytest.mark.asyncio
async def test_additive_adjustment_migration_keeps_historical_null_keys():
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: apply_revisions(sync, target="0043_referral_bonus_safety"))
            user_id, transaction_id, adjustment_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            await conn.execute(text("INSERT INTO users (id,telegram_id,first_name) VALUES (:u,931,'Historical test')"), {"u": user_id})
            await conn.execute(text("INSERT INTO wallet_transactions (id,user_id,transaction_type,amount,available_before,available_after,frozen_before,frozen_after,description) VALUES (:t,:u,'admin_adjustment',5,0,5,0,0,'Historical test')"), {"u": user_id, "t": transaction_id})
            await conn.execute(text("INSERT INTO admin_balance_adjustments (id,admin_id,user_id,amount,reason,wallet_transaction_id) VALUES (:a,:u,:u,5,'Historical test',:t)"), {"a": adjustment_id, "u": user_id, "t": transaction_id})
            # Replay the next migration against the actual prior schema.
            await conn.run_sync(lambda sync: apply_revisions(sync, target="0044_admin_balance_idempotency", after="0043_referral_bonus_safety"))
            columns = await conn.scalar(text("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='admin_balance_adjustments' AND column_name='request_id' AND is_nullable='YES'"))
            assert columns == 1
            constraint = await conn.scalar(text("SELECT COUNT(*) FROM pg_constraint WHERE conname='uq_admin_balance_request' AND conrelid='admin_balance_adjustments'::regclass"))
            assert constraint == 1
            historical = (await conn.execute(text("SELECT request_id, amount, wallet_transaction_id FROM admin_balance_adjustments WHERE id=:a"), {"a": adjustment_id})).one()
            assert historical == (None, Decimal("5"), transaction_id)
            assert await conn.scalar(text("SELECT COUNT(*) FROM wallet_transactions")) == 1
