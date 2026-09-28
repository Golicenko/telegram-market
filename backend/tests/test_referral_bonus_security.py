"""Registration eligibility and actual wallet/deal/withdrawal persistence."""
# ruff: noqa: F811 -- imported pytest fixtures are injected by parameter name

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.schema import CreateTable

from app import referrals
from app.auth import get_current_user
from app.config import Settings
from app.database import get_session
from app.gift_withdrawals import preview_withdrawal
from app.models import (
    AdminAction,
    AdminBalanceAdjustment,
    Referral,
    ReferralReward,
    User,
    Wallet,
    WalletTransaction,
    SupportTicket,
)
from app.routes import router, telegram_webhook
from app.services import (
    adjust_balance,
    cancel_deal,
    complete_deal,
    credit_sale_proceeds,
    process_successful_payment,
    purchase_listing,
    resolve_dispute,
    purchase_training_product,
    update_training_purchase_status,
)
from test_referrals import db as db, login, new_payment, count
from test_chat_lifecycle_db import db as deal_db  # noqa: F401
from test_manual_gift_withdrawals import db as withdrawal_db  # noqa: F401
from test_training_library import FakeSession, product, wallet


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", [False, True])
async def test_existing_bot_user_without_processed_flag_never_becomes_referral(
    db, pending
):
    owner = await login(db, 1)
    other = await login(db, 2)
    existing = User(
        telegram_id=3,
        first_name="Existing bot user",
        bot_started=True,
        pending_referral_code=owner.referral_code if pending else None,
        referral_registration_processed=False,
    )
    db.add(existing)
    await db.flush()
    db.add(Wallet(user_id=existing.id))
    await db.commit()
    settings = Settings(bot_token="referral-test-token")
    for code in (owner.referral_code, other.referral_code, owner.referral_code):
        await telegram_webhook(
            {"message": {"from": {"id": 3}, "text": f"/start {code}"}},
            BackgroundTasks(),
            settings.effective_telegram_webhook_secret,
            db,
            settings,
        )
        await login(db, 3, code)
    assert count(db, Referral) == count(db, ReferralReward) == 0
    await db.commit()
    payment = await new_payment(db, existing)
    assert await process_successful_payment(db, 3, payment)
    assert count(db, ReferralReward) == 0


@pytest.mark.asyncio
async def test_plain_start_before_referral_permanently_disqualifies(db):
    owner = await login(db, 1)
    settings = Settings(bot_token="referral-test-token")
    for command in ("/start", f"/start {owner.referral_code}"):
        await telegram_webhook(
            {"message": {"from": {"id": 2}, "text": command}},
            BackgroundTasks(),
            settings.effective_telegram_webhook_secret,
            db,
            settings,
        )
    await login(db, 2, owner.referral_code)
    assert count(db, Referral) == 0


@pytest.mark.asyncio
async def test_new_direct_and_bot_registrations_keep_first_bound_candidate(db):
    owner = await login(db, 1)
    other = await login(db, 2)
    settings = Settings(bot_token="referral-test-token")
    for code in (owner.referral_code, other.referral_code):
        await telegram_webhook(
            {"message": {"from": {"id": 3}, "text": f"/start {code}"}},
            BackgroundTasks(),
            settings.effective_telegram_webhook_secret,
            db,
            settings,
        )
    bot_user = await login(db, 3, other.referral_code)
    direct = await login(db, 4, owner.referral_code)
    for user in (bot_user, direct):
        assert db.session.get(Referral, user.id).referrer_id == owner.id
        await db.commit()
        await login(db, user.telegram_id, other.referral_code)
        assert db.session.get(Referral, user.id).referrer_id == owner.id
        await db.commit()


@pytest.mark.asyncio
async def test_milestone_and_commission_are_bonus_not_earned_and_no_cascade(db):
    owner = await login(db, 1)
    for n in range(2, 22):
        await login(db, n, owner.referral_code)
    owner_wallet = db.session.scalar(select(Wallet).where(Wallet.user_id == owner.id))
    assert owner_wallet.bonus_balance == 75
    assert owner_wallet.earned_balance == owner_wallet.total_earned == 0
    await db.commit()
    friend = await login(db, 2)
    for amount, expected in ((100, "80"), (50, "82.50"), (25, "83.75")):
        payment = await new_payment(db, friend, amount)
        assert await process_successful_payment(db, 2, payment)
        assert not await process_successful_payment(db, 2, payment)
        assert owner_wallet.bonus_balance == Decimal(expected)
        assert owner_wallet.earned_balance == 0
    assert count(db, ReferralReward) == 6
    tx = db.session.scalar(
        select(WalletTransaction)
        .where(WalletTransaction.transaction_type == "referral_commission")
        .limit(1)
    )
    assert "bonus_balance" in tx.balance_breakdown
    assert str(friend.telegram_id) not in tx.description


@pytest.mark.asyncio
async def test_direct_reward_retry_is_idempotent(db):
    owner = await login(db, 1)
    for n in range(2, 5):
        await login(db, n, owner.referral_code)
    w = db.session.scalar(select(Wallet).where(Wallet.user_id == owner.id))
    await referrals.credit_reward(db, w, Decimal(10), milestone=3)
    await db.commit()
    assert w.bonus_balance == 10 and count(db, ReferralReward) == 1


@pytest.mark.asyncio
async def test_admin_credit_and_marked_test_payment_do_not_grant_commission(db):
    owner = await login(db, 1)
    buyer = await login(db, 2, owner.referral_code)
    with db.session.bind.begin() as conn:
        for model in (AdminAction, AdminBalanceAdjustment):
            conn.execute(CreateTable(model.__table__))
    await adjust_balance(
        db,
        owner,
        SimpleNamespace(user_id=buyer.id, amount=Decimal(100), reason="Bonus"),
    )
    assert count(db, ReferralReward) == 0
    await db.commit()
    payment = await new_payment(db, buyer)
    with pytest.raises(HTTPException):
        await process_successful_payment(db, 2, payment | {"is_test": True})
    assert count(db, ReferralReward) == 0


@pytest.mark.asyncio
async def test_cancelled_intent_cannot_credit_referrer(db):
    from app.models import StarPaymentIntent

    owner = await login(db, 1)
    buyer = await login(db, 2, owner.referral_code)
    payment = await new_payment(db, buyer)
    intent = db.session.scalar(
        select(StarPaymentIntent).where(
            StarPaymentIntent.invoice_payload == payment["invoice_payload"]
        )
    )
    intent.status = "cancelled"
    await db.commit()
    with pytest.raises(HTTPException):
        await process_successful_payment(db, 2, payment)
    assert count(db, ReferralReward) == 0


@pytest.mark.asyncio
async def test_bonus_cannot_satisfy_withdrawal_or_forged_quote_via_http(withdrawal_db):
    bridge, user, _ = withdrawal_db
    # A previously valid quote must be revalidated against earned funds at reserve.
    quote = await preview_withdrawal(bridge, user, Decimal(30))
    with bridge.session.begin():
        w = bridge.session.scalar(select(Wallet))
        w.earned_balance = 0
        w.bonus_balance = 1000
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: bridge
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/withdrawals",
            json={
                "quote_id": quote["quote_id"],
                "details": "forged",
                "amount": 21.43,
                "payout_method": "manual_gift",
            },
        )
        assert response.status_code == 402, response.text
    with pytest.raises(HTTPException) as err:
        await preview_withdrawal(bridge, user, Decimal(30))
    assert err.value.status_code == 402
    with bridge.session.begin():
        assert w.bonus_balance == 1000 and w.earned_frozen_balance == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", [False, True])
async def test_bonus_market_reserve_refund_or_settlement_persists(deal_db, finish):
    bridge, buyer, seller, listing = deal_db
    with bridge.session.begin():
        bw = bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        bw.purchased_balance, bw.earned_balance, bw.bonus_balance = 20, 30, 50
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    assert (
        deal.purchased_frozen_amount,
        deal.earned_frozen_amount,
        deal.bonus_frozen_amount,
    ) == (20, 30, 50)
    bridge.session.expire_all()
    with bridge.session.begin():
        bridge.session.refresh(deal)
        bridge.session.refresh(buyer)
        if finish:
            # SQLite timestamps do not retain timezone; set a proper test datetime.
            deal.status = "transfer_in_progress"
            deal.transfer_started_at = datetime.now(UTC) - timedelta(minutes=2)
    if finish:
        await complete_deal(bridge, buyer, deal.id)
    else:
        await cancel_deal(bridge, buyer, deal.id)
    with bridge.session.begin():
        bw = bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        sw = bridge.session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
        assert bw.frozen_balance == 0
        if finish:
            assert bw.available_balance == 0
            assert sw.earned_balance == 50 and sw.bonus_balance == 50
        else:
            assert (bw.purchased_balance, bw.earned_balance, bw.bonus_balance) == (
                20,
                30,
                50,
            )
        tx = bridge.session.scalar(
            select(WalletTransaction).where(
                WalletTransaction.transaction_type == "protection_hold"
            )
        )
        assert tx.balance_breakdown["funding"] == {
            "purchased": "20.00",
            "earned": "30.00",
            "bonus": "50.00",
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "refund"])
async def test_admin_resolution_does_not_convert_bonus_to_earned(deal_db, outcome):
    bridge, buyer, seller, listing = deal_db
    with bridge.session.bind.begin() as conn:
        for model in (AdminAction, SupportTicket):
            conn.execute(CreateTable(model.__table__))
    with bridge.session.begin():
        bw = bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        bw.purchased_balance, bw.bonus_balance = 0, 100
        admin = User(id=uuid.uuid4(), telegram_id=3, first_name="Admin", role="admin")
        bridge.add(admin)
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    request_id = uuid.uuid4()
    for _ in range(2):
        await resolve_dispute(
            bridge,
            admin,
            deal.id,
            outcome,
            "Reviewed",
            allow_active=True,
            request_id=request_id,
        )
    with bridge.session.begin():
        sw = bridge.session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
        assert sw.earned_balance == bw.earned_balance == 0
        assert sw.bonus_balance == (100 if outcome == "complete" else 0)
        assert bw.bonus_balance == (0 if outcome == "complete" else 100)
        assert bw.bonus_frozen_balance == 0


@pytest.mark.parametrize(
    "bonus,expected", [("100", "70"), ("50", "35"), ("0.01", "0.01")]
)
def test_sale_income_cannot_launder_bonus_through_another_account(bonus, expected):
    seller = wallet(uuid.uuid4())
    credit_sale_proceeds(seller, Decimal(70), Decimal(100), Decimal(bonus))
    assert seller.bonus_balance == Decimal(expected)
    assert seller.earned_balance == 70 - Decimal(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("personal", [False, True])
async def test_bonus_spending_on_training_preserves_nonwithdrawable_origin(personal):
    buyer = User(id=uuid.uuid4(), telegram_id=1, first_name="Buyer")
    seller = User(id=uuid.uuid4(), telegram_id=2, first_name="Admin", role="admin")
    course = product(seller.id, "personal" if personal else "automatic")
    bw, sw = wallet(buyer.id), wallet(seller.id)
    bw.bonus_balance = Decimal(100)
    values = (
        [course, None]
        + ([] if personal else [uuid.uuid4()])
        + [bw]
        + ([] if personal else [sw])
    )
    purchase, created = await purchase_training_product(
        FakeSession(values), buyer, course.id
    )
    assert created
    if personal:
        assert purchase.bonus_frozen_amount == 100 and sw.earned_balance == 0
        await update_training_purchase_status(
            FakeSession([purchase]), seller, purchase.id, "in_progress"
        )
        await update_training_purchase_status(
            FakeSession([purchase, bw, sw]), seller, purchase.id, "completed"
        )
    assert bw.frozen_balance == 0 and bw.available_balance == 0
    assert sw.bonus_balance == purchase.seller_payout and sw.earned_balance == 0
