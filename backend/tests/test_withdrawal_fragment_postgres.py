"""Real PostgreSQL row locking and snapshot/filter checks on a disposable schema."""
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app import gift_withdrawals as service
from app.models import Notification, SellerVipPlan, SellerVipSubscription, User, Wallet, WalletTransaction, WithdrawalRequest
from app.routes import admin_withdrawals
from app.services import decide_withdrawal
from test_referral_bonus_postgres import isolated_pg, signed_login


@pytest.mark.asyncio
async def test_parallel_fragment_reserve_and_settlement_once_with_historical_vip_priority(monkeypatch):
    policy = Settings(_env_file=None, fragment_withdrawals_enabled=True)
    monkeypatch.setattr(service, "get_settings", lambda: policy)
    async def catalog():
        return [{"id": "gift15", "star_count": 15}]
    monkeypatch.setattr(service, "available_gifts", catalog)
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 9711)
        admin = await signed_login(sessions, 9712)
        user.username = "Fragment_test_user"
        admin.role = "admin"
        async with sessions() as session, session.begin():
            stored = await session.get(User, user.id)
            stored.username = user.username
            (await session.get(User, admin.id)).role = "admin"
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
            wallet.earned_balance = 500
            wallet.purchased_balance = 700
            wallet.bonus_balance = 900
            plan = SellerVipPlan(code="month", title="VIP на 30 дней", duration_days=30, price_af=79,
                pins_72h=10, pins_24h=0, car_limit=15, account_limit=10)
            session.add(plan)
            await session.flush()
            sub = SellerVipSubscription(user_id=user.id, request_id=uuid.uuid4(), plan_code="month", title=plan.title,
                source="admin", status="active", price_paid=0, purchased_af=0, earned_af=0, bonus_af=0,
                starts_at=datetime.now(UTC)-timedelta(days=1), expires_at=datetime.now(UTC)+timedelta(days=29),
                pins_72h_total=10, pins_72h_remaining=10, pins_24h_total=0, pins_24h_remaining=0,
                car_limit=15, account_limit=10)
            session.add(sub)
        async with sessions() as session:
            quote = await service.preview_withdrawal(session, user, Decimal("75.72"))
        quote_id = uuid.UUID(quote["quote_id"])
        async def reserve():
            async with sessions() as session:
                return await service.reserve_gift_withdrawal(session, user, quote_id, "Isolated test")
        requests = await asyncio.wait_for(asyncio.gather(*(reserve() for _ in range(15))), 30)
        assert len({row.id for row in requests}) == 1
        request = requests[0]
        assert request.payout_stars == 53 and request.amount == Decimal("75.72")
        assert request.fee_af == Decimal("22.72") and request.vip_priority
        async with sessions() as session, session.begin():
            (await session.get(SellerVipSubscription, sub.id)).status = "expired"
        async with sessions() as session:
            ordinary_quote = await service.preview_withdrawal(session, user, Decimal(30))
        async with sessions() as session:
            ordinary = await service.reserve_gift_withdrawal(session, user, uuid.UUID(ordinary_quote["quote_id"]), "")
        assert ordinary.vip_priority is False
        for priority, expected in [(True, [request.id]), (False, [ordinary.id]), (None, [request.id, ordinary.id])]:
            async with sessions() as session:
                rows = await admin_withdrawals(q=None, status=None, limit=50, offset=0, withdrawal_id=None,
                    vip_priority=priority, admin=admin, session=session)
            assert [row.id for row in rows] == expected
            if priority is True:
                assert rows[0].vip_snapshot["subscription_id"] == str(sub.id)
        policy.fragment_withdrawals_enabled = False
        assert (await reserve()).id == request.id
        async def decide(action):
            async with sessions() as session:
                return await decide_withdrawal(session, admin, request.id, action, None, "fragment-test-receipt")
        await asyncio.gather(*(decide("approve") for _ in range(5)))
        await asyncio.gather(*(decide("paid") for _ in range(5)))
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(WithdrawalRequest)) == 2
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "withdrawal_paid")) == 1
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "withdrawal_created")) == 2
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
            assert wallet.earned_balance == Decimal("402.85") and wallet.earned_frozen_balance == Decimal("21.43")
            assert wallet.purchased_balance == 700 and wallet.bonus_balance == 900
