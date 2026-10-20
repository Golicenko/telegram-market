"""Persisted referral reward state used by the visual-only referral redesign."""
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import referral_routes, referrals
from app.auth import get_current_user
from app.database import get_session
from app.models import Referral, ReferralReward, Wallet, WalletTransaction
from test_referrals import count, db as db, login  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invited,confirmed",
    [
        (0, ()), (1, ()), (2, ()),
        (3, ()), (3, (3,)),
        (8, (3,)),
        (10, (3,)), (10, (3, 10)),
        (17, (3, 10)),
        (20, ()), (20, (3, 10, 20)),
    ],
)
async def test_summary_completed_requires_persisted_reward_not_referral_count(
    db, monkeypatch, invited, confirmed  # noqa: F811 - imported pytest fixture
):
    owner = await login(db, 6001)
    original_code = owner.referral_code
    # Explicit isolated history allows testing the important inconsistent/read
    # state: a threshold exists but there is no confirmed reward ledger row.
    # Normal signed registrations already award atomically in other tests.
    for index in range(invited):
        friend = await login(db, 6002 + index)
        db.add(Referral(referred_user_id=friend.id, referrer_id=owner.id, slot=index + 1))
        await db.commit()

    wallet = db.session.scalar(select(Wallet).where(Wallet.user_id == owner.id))
    rewards = dict(referrals.MILESTONES)
    for threshold in confirmed:
        await referrals.credit_reward(db, wallet, Decimal(rewards[threshold]), milestone=threshold)
    await db.commit()

    async def personal_url(code):
        return f"https://t.me/IsolatedReferralBot?startapp={code}"

    monkeypatch.setattr(referral_routes, "referral_url", personal_url)
    app = FastAPI()
    app.include_router(referral_routes.router)
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: db
    expected_bonus = Decimal(sum(rewards[threshold] for threshold in confirmed))
    expected_milestones = [
        {"count": threshold, "reward": reward, "completed": threshold in confirmed}
        for threshold, reward in referrals.MILESTONES
    ]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        snapshots = []
        for endpoint in (
            "/api/referrals",
            "/api/referrals/me?referralCount=999&completed=true&reward=999&canInvite=true",
        ):
            response = await client.get(endpoint)
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            snapshots.append(response.json())

        # A new database session represents reopening the app. There is no
        # localStorage state or claim request involved in restoring completion.
        db.session.close()
        db.session = Session(db.session.bind, expire_on_commit=False)
        response = await client.get("/api/referrals")
        assert response.status_code == 200, response.text
        snapshots.append(response.json())

    for snapshot in snapshots:
        assert snapshot["referralCode"] == original_code
        assert snapshot["referralUrl"] == await personal_url(original_code)
        assert snapshot["referralCount"] == invited
        assert snapshot["referralLimit"] == 20
        assert snapshot["commissionPercent"] == 5
        assert snapshot["canInvite"] is (invited < 20)
        assert snapshot["milestones"] == expected_milestones

    # Opening cards/refreshing the source endpoint never creates a second reward
    # or changes bonus provenance. Existing finance tests cover actual awards.
    assert count(db, Referral) == invited
    assert count(db, ReferralReward) == count(db, WalletTransaction) == len(confirmed)
    wallet = db.session.scalar(select(Wallet).where(Wallet.user_id == owner.id))
    assert wallet.bonus_balance == expected_bonus
    assert wallet.earned_balance == wallet.total_earned == wallet.purchased_balance == 0
