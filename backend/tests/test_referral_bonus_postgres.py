"""Real PostgreSQL locks and migration rehearsal in isolated disposable schemas."""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import get_current_user
from app.config import Settings, normalize_database_url
from app.models import (
    Base,
    Referral,
    ReferralReward,
    User,
    Wallet,
    Listing,
    StarPaymentIntent,
)
from app.referrals import credit_reward, backfill_referral_codes
from app.services import purchase_listing, complete_deal, process_successful_payment
from datetime import UTC, datetime, timedelta
from test_referrals import init_data


@asynccontextmanager
async def isolated_pg(*, tables=True):
    url = os.environ.get("REFERRAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated PostgreSQL test database not configured")
    schema = "referral_test_" + uuid.uuid4().hex
    bootstrap = create_async_engine(normalize_database_url(url))
    async with bootstrap.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        normalize_database_url(url),
        pool_size=8,
        max_overflow=2,
        connect_args={
            "server_settings": {"search_path": schema, "lock_timeout": "10000"}
        },
    )
    try:
        if tables:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        # Delete ONLY the unpredictable schema created above in the explicit test DB.
        assert schema.startswith("referral_test_") and len(schema) == 46
        async with bootstrap.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await bootstrap.dispose()


async def signed_login(sessions, telegram_id, code=None):
    async with sessions() as session:
        return await get_current_user(
            Request({"type": "http"}),
            init_data(telegram_id, code),
            None,
            session,
            Settings(bot_token="referral-test-token", debug=False),
        )


@pytest.mark.asyncio
async def test_exactly_one_twentieth_referral_and_concurrent_reward_retry():
    async with isolated_pg() as (_, sessions):
        owner = await signed_login(sessions, 1)
        for n in range(2, 21):
            await signed_login(sessions, n, owner.referral_code)
        await asyncio.gather(
            signed_login(sessions, 21, owner.referral_code),
            signed_login(sessions, 22, owner.referral_code),
        )

        async def retry_reward():
            async with sessions() as session, session.begin():
                wallet = await session.scalar(
                    select(Wallet).where(Wallet.user_id == owner.id).with_for_update()
                )
                await credit_reward(session, wallet, Decimal(50), milestone=20)

        await asyncio.gather(*(retry_reward() for _ in range(5)))
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(Referral)) == 20
            )
            assert (
                await session.scalar(select(func.count()).select_from(ReferralReward))
                == 3
            )
            wallet = await session.scalar(
                select(Wallet).where(Wallet.user_id == owner.id)
            )
            assert wallet.bonus_balance == 75 and wallet.earned_balance == 0


@pytest.mark.asyncio
async def test_concurrent_first_login_and_existing_bot_account_never_reattribute():
    async with isolated_pg() as (_, sessions):
        owners = [await signed_login(sessions, i) for i in (1, 2)]
        async with sessions() as session, session.begin():
            existing = User(
                telegram_id=3, first_name="Known bot user", bot_started=True
            )
            session.add(existing)
            await session.flush()
            session.add(Wallet(user_id=existing.id))
        await asyncio.gather(
            *(signed_login(sessions, 3, owner.referral_code) for owner in owners)
        )
        await asyncio.gather(
            *(signed_login(sessions, 4, owner.referral_code) for owner in owners)
        )
        async with sessions() as session:
            assert await session.get(Referral, existing.id) is None
            assert await session.scalar(select(func.count()).select_from(Referral)) == 1
            assert (
                await session.scalar(
                    select(func.count()).select_from(User).where(User.telegram_id == 4)
                )
                == 1
            )


@pytest.mark.asyncio
async def test_batched_backfill_retries_collision_and_never_qualifies_old_accounts(
    monkeypatch,
):
    from app import referrals

    async with isolated_pg() as (_, sessions):
        owner = await signed_login(sessions, 1)
        async with sessions() as session, session.begin():
            session.add_all(
                [User(telegram_id=n, first_name="Known account") for n in range(2, 206)]
            )
        original = referrals.new_code
        collision = [owner.referral_code]
        monkeypatch.setattr(
            referrals, "new_code", lambda: collision.pop() if collision else original()
        )
        assert (
            sum(
                await asyncio.gather(
                    backfill_referral_codes(sessions, 25),
                    backfill_referral_codes(sessions, 25),
                )
            )
            == 204
        )
        assert await backfill_referral_codes(sessions) == 0
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count(func.distinct(User.referral_code)))
                )
                == 205
            )
            assert await session.scalar(select(func.count()).select_from(Referral)) == 0


@pytest.mark.asyncio
async def test_referral_topup_and_sale_settlement_use_compatible_wallet_lock_order():
    async with isolated_pg() as (_, sessions):
        seller = await signed_login(sessions, 1)
        buyer = await signed_login(sessions, 2, seller.referral_code)
        async with sessions() as session, session.begin():
            wallet = await session.scalar(
                select(Wallet).where(Wallet.user_id == buyer.id)
            )
            wallet.purchased_balance = 100
            listing = Listing(
                seller_id=seller.id,
                game_version="car_parking_1",
                listing_type="regular",
                status="active",
                brand="Car",
                model="Test",
                power_hp=1,
                max_speed_kph=1,
                description="Test",
                price_af_coins=100,
            )
            session.add(listing)
        async with sessions() as session:
            deal, _, _ = await purchase_listing(session, buyer, listing.id)
        async with sessions() as session, session.begin():
            from app.models import Deal

            pending = await session.get(Deal, deal.id)
            pending.status = "transfer_in_progress"
            pending.transfer_started_at = datetime.now(UTC) - timedelta(minutes=2)
            intent = StarPaymentIntent(
                user_id=buyer.id,
                invoice_payload=f"autoflow_topup:{uuid.uuid4()}",
                xtr_amount=100,
                purpose="topup",
                status="pending",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            session.add(intent)
        payment = {
            "currency": "XTR",
            "invoice_payload": intent.invoice_payload,
            "total_amount": 100,
            "telegram_payment_charge_id": str(uuid.uuid4()),
        }

        async def settle():
            async with sessions() as session:
                return await complete_deal(session, buyer, deal.id)

        async def topup():
            async with sessions() as session:
                return await process_successful_payment(
                    session, buyer.telegram_id, payment
                )

        await asyncio.wait_for(asyncio.gather(settle(), topup()), timeout=15)
        async with sessions() as session:
            sw = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            assert sw.earned_balance == 100 and sw.bonus_balance == 5


def apply_revisions(connection, *, target, after=None):
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    scripts = ScriptDirectory.from_config(config)
    revisions = list(scripts.iterate_revisions(target, after or "base"))
    with Operations.context(MigrationContext.configure(connection)):
        for revision in reversed(revisions):
            revision.module.upgrade()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_state", ["safe", "spent", "low_balance", "low_total_earned"])
async def test_migration_preserves_safe_legacy_money_or_aborts_ambiguity(legacy_state):
    from scripts.audit_referral_legacy import read_legacy_rewards

    needs_review = legacy_state != "safe"
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync: apply_revisions(sync, target="0042_referral_program")
            )
            uid, wid, tid, rid = (uuid.uuid4() for _ in range(4))
            await conn.execute(
                text("""INSERT INTO users (id,telegram_id,role,first_name,is_blocked)
                VALUES (:id,1,'user','Legacy',false)"""),
                {"id": uid},
            )
            await conn.execute(
                text("""INSERT INTO wallets (id,user_id,purchased_balance,earned_balance,
                purchased_frozen_balance,earned_frozen_balance,total_earned,version)
                VALUES (:id,:u,0,10,0,0,10,0)"""),
                {"id": wid, "u": uid},
            )
            await conn.execute(
                text("""INSERT INTO wallet_transactions (id,user_id,transaction_type,amount,
                available_before,available_after,frozen_before,frozen_after,description)
                VALUES (:id,:u,'referral_milestone',10,0,10,0,0,'Legacy reward')"""),
                {"id": tid, "u": uid},
            )
            await conn.execute(
                text("""INSERT INTO referral_rewards (id,user_id,milestone,amount,transaction_id)
                VALUES (:id,:u,3,10,:t)"""),
                {"id": rid, "u": uid, "t": tid},
            )
            if legacy_state in {"spent", "low_balance"}:
                await conn.execute(
                    text("UPDATE wallets SET earned_balance=5 WHERE user_id=:u"),
                    {"u": uid},
                )
            if legacy_state == "spent":
                await conn.execute(
                    text("""INSERT INTO wallet_transactions (id,user_id,transaction_type,amount,
                    available_before,available_after,frozen_before,frozen_after,description)
                    VALUES (:id,:u,'listing_promotion',-5,10,5,0,0,'Already spent')"""),
                    {"id": uuid.uuid4(), "u": uid},
                )
            if legacy_state == "low_total_earned":
                await conn.execute(
                    text("UPDATE wallets SET total_earned=5 WHERE user_id=:u"),
                    {"u": uid},
                )

        async with engine.connect() as conn:
            audit = await read_legacy_rewards(conn)
            assert len(audit) == 1
            assert audit[0]["needs_review"] is needs_review
            assert audit[0]["reward_total"] == 10

        async def upgrade():
            async with engine.begin() as conn:
                await conn.run_sync(
                    lambda sync: apply_revisions(
                        sync,
                        target="0043_referral_bonus_safety",
                        after="0042_referral_program",
                    )
                )

        if needs_review:
            with pytest.raises(DBAPIError, match="REFERRAL_LEGACY_REVIEW_REQUIRED"):
                await upgrade()
        else:
            await upgrade()
        async with engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("SELECT * FROM wallets WHERE user_id=:u"), {"u": uid}
                    )
                )
                .mappings()
                .one()
            )
            if needs_review:
                assert row["earned_balance"] == (10 if legacy_state == "low_total_earned" else 5)
                assert "bonus_balance" not in row
            else:
                assert row["earned_balance"] == 0 and row["bonus_balance"] == 10
                assert row["total_earned"] == 0
                assert (
                    await conn.scalar(
                        text(
                            "SELECT COUNT(*) FROM wallet_transactions WHERE transaction_type='referral_bonus_reclassified'"
                        )
                    )
                    == 1
                )
            assert await conn.scalar(text("SELECT COUNT(*) FROM referral_rewards")) == 1
            assert (
                await conn.scalar(
                    text("SELECT COUNT(*) FROM wallet_transactions WHERE id=:t"),
                    {"t": tid},
                )
                == 1
            )
