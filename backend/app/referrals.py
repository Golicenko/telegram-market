"""Referral ledger. All mutation helpers run inside their caller's transaction."""

import re
import secrets
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .models import Referral, ReferralReward, User, Wallet

REFERRAL_LIMIT = 20
COMMISSION_PERCENT = 5
MILESTONES = ((3, 10), (10, 15), (20, 50))


def valid_code(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9]{6,8}", value)
        else None
    )


def new_code():
    return "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(8)
    )


async def ensure_code(session, user):
    # Caller holds the user row lock. A savepoint retries only a code collision.
    if user.referral_code:
        return user.referral_code
    for _ in range(10):
        try:
            async with session.begin_nested():
                user.referral_code = new_code()
                await session.flush()
            return user.referral_code
        except IntegrityError:
            await session.refresh(user)
    raise HTTPException(503, "Не удалось создать реферальную ссылку. Повторите позже.")


async def referral_count(session, user_id):
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Referral)
            .where(Referral.referrer_id == user_id)
        )
        or 0
    )


async def credit_reward(session, wallet, amount, *, milestone=None, payment_id=None):
    from .services import money, wallet_transaction

    reward_id = uuid.uuid4()
    before_available, before_frozen = wallet.available_balance, wallet.frozen_balance
    wallet.earned_balance = money(wallet.earned_balance + amount)
    wallet.total_earned = money(wallet.total_earned + amount)
    wallet.version += 1
    kind = "referral_milestone" if milestone else "referral_commission"
    description = (
        f"Награда за {milestone} приглашённых друзей"
        if milestone
        else "Реферальный бонус с платного пополнения"
    )
    transaction = wallet_transaction(
        wallet,
        kind,
        amount,
        before_available,
        before_frozen,
        description,
        external_reference=f"referral:{reward_id}",
    )
    session.add(transaction)
    await session.flush()
    session.add(
        ReferralReward(
            id=reward_id,
            user_id=wallet.user_id,
            milestone=milestone,
            payment_id=payment_id,
            amount=amount,
            transaction_id=transaction.id,
        )
    )
    await session.flush()


async def qualify_first_login(session, user, signed_start_param):
    """Called only after signature verification, while holding this user's row lock.

    Existing users are marked processed by migration. Bot /start is only a candidate;
    it cannot earn rewards until a verified Mini App login.
    """
    if user.referral_registration_processed:
        return
    candidate = valid_code(user.pending_referral_code) or valid_code(signed_start_param)
    user.referral_registration_processed = True
    user.pending_referral_code = None
    if not candidate or candidate == user.referral_code:
        return
    # A referrer must have already qualified their own first login. This also
    # prevents mutual attribution/deadlocks between two concurrently new accounts.
    referrer = await session.scalar(
        select(User)
        .where(
            User.referral_code == candidate,
            User.id != user.id,
            User.referral_registration_processed.is_(True),
            User.is_blocked.is_(False),
        )
        # PostgreSQL NO KEY UPDATE serializes referral admission but permits
        # concurrent ledger FK checks while we wait for the wallet row.
        .with_for_update(key_share=True)
    )
    if referrer is None:
        return
    count = await referral_count(session, referrer.id)
    if count >= REFERRAL_LIMIT:
        return
    session.add(
        Referral(referred_user_id=user.id, referrer_id=referrer.id, slot=count + 1)
    )
    await session.flush()
    for threshold, amount in MILESTONES:
        if count + 1 != threshold:
            continue
        wallet = await session.scalar(
            select(Wallet).where(Wallet.user_id == referrer.id).with_for_update()
        )
        if wallet is None:
            raise HTTPException(
                409, "Не удалось начислить реферальную награду. Повторите вход."
            )
        await credit_reward(session, wallet, Decimal(amount), milestone=threshold)


async def payment_wallets(session, user_id):
    """Lock the payer and (if present) referrer wallets in canonical UUID order."""
    referrer_id = await session.scalar(
        select(Referral.referrer_id).where(Referral.referred_user_id == user_id)
    )
    wallets = {}
    for owner_id in sorted({user_id, referrer_id} - {None}, key=str):
        wallet = await session.scalar(
            select(Wallet).where(Wallet.user_id == owner_id).with_for_update()
        )
        if wallet is None:
            raise HTTPException(409, "Wallet not found")
        wallets[owner_id] = wallet
    return wallets[user_id], wallets.get(referrer_id)


async def credit_payment_commission(session, referrer_wallet, payment):
    if referrer_wallet is None:
        return
    # Every paid top-up is represented once by StarPayment; payment_id is also
    # UNIQUE in rewards. No bonus, manual adjustment or refund calls this helper.
    amount = (payment.af_coin_amount * Decimal(COMMISSION_PERCENT) / 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if amount > 0:
        await session.flush()
        await credit_reward(session, referrer_wallet, amount, payment_id=payment.id)


def invitation_text(first_name):
    name = (first_name or "").strip()
    heading = (
        f"{name} приглашает тебя в AutoFlow Market 🚗"
        if name and name != "Telegram User"
        else "Тебя приглашают в AutoFlow Market 🚗"
    )
    return (
        f"{heading}\n\nЗарабатывай вместе со мной в AutoFlow Market.\n\n"
        "Покупай и продавай товары для Car Parking Multiplayer, приглашай друзей и получай бонусы.\n\n"
        f"За приглашённых друзей можно получать AF и {COMMISSION_PERCENT}% с каждого их платного пополнения."
    )
