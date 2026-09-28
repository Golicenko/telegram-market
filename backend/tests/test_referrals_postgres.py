"""Optional real PostgreSQL concurrency test, isolated in a disposable schema.

Set REFERRAL_TEST_DATABASE_URL to a dedicated TEST database, never DATABASE_URL.
No production data, tables or migrations are modified by this test.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import get_current_user
from app.config import Settings, normalize_database_url
from app.models import Base, Referral, ReferralReward, StarPaymentIntent, Wallet
from app.services import process_successful_payment
from test_referrals import init_data


@pytest.mark.asyncio
async def test_postgres_concurrent_cap_and_duplicate_payment():
    url = os.environ.get("REFERRAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated PostgreSQL test database not configured")
    schema = "referral_test_" + uuid.uuid4().hex
    bootstrap = create_async_engine(normalize_database_url(url))
    async with bootstrap.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        normalize_database_url(url),
        pool_size=5,
        max_overflow=5,
        connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async def login(telegram_id, code=None):
            async with sessions() as session:
                return await get_current_user(
                    Request({"type": "http"}),
                    init_data(telegram_id, code),
                    None,
                    session,
                    Settings(bot_token="referral-test-token", debug=False),
                )

        owner = await login(1)
        # All 25 arrive concurrently; only 20 distinct users can obtain a slot.
        friends = await asyncio.gather(
            *(login(n, owner.referral_code) for n in range(2, 27))
        )
        # Duplicate authenticated first logins cannot duplicate a referral or a wallet.
        await asyncio.gather(*(login(27, owner.referral_code) for _ in range(5)))
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(Referral)) == 20
            )
            assert (
                await session.scalar(select(func.count()).select_from(ReferralReward))
                == 3
            )
            assert (
                await session.scalar(select(Wallet).where(Wallet.user_id == owner.id))
            ).available_balance == Decimal("75")
            referred_id = await session.scalar(
                select(Referral.referred_user_id).limit(1)
            )
            buyer = next(friend for friend in friends if friend.id == referred_id)
            intent = StarPaymentIntent(
                id=uuid.uuid4(),
                user_id=buyer.id,
                invoice_payload=f"autoflow_topup:{uuid.uuid4()}",
                xtr_amount=100,
                purpose="topup",
                status="pending",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            session.add(intent)
            await session.commit()
        payment = {
            "currency": "XTR",
            "invoice_payload": intent.invoice_payload,
            "total_amount": 100,
            "telegram_payment_charge_id": str(uuid.uuid4()),
        }

        async def pay():
            async with sessions() as session:
                return await process_successful_payment(
                    session, buyer.telegram_id, payment
                )

        assert sum(await asyncio.gather(*(pay() for _ in range(8)))) == 1
        async with sessions() as session:
            assert (
                await session.scalar(select(Wallet).where(Wallet.user_id == owner.id))
            ).available_balance == Decimal("80")
            assert (
                await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            ).available_balance == Decimal("100")
            assert (
                await session.scalar(select(func.count()).select_from(ReferralReward))
                == 4
            )
    finally:
        await engine.dispose()
        # Only this test's unpredictable, explicitly created schema is cleaned up.
        assert schema.startswith("referral_test_") and len(schema) == 46
        async with bootstrap.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await bootstrap.dispose()
