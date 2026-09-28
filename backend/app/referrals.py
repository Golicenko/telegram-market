"""Referral ledger. All mutation helpers run inside their caller's transaction."""

import asyncio
import re
import logging
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
logger = logging.getLogger(__name__)


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


async def backfill_referral_codes(session_factory=None, batch_size=100):
    """Small, resumable commits; assigning a code never qualifies a referral."""
    if session_factory is None:
        from .database import SessionLocal

        session_factory = SessionLocal
    total = 0
    while True:
        async with session_factory() as session, session.begin():
            users = list(
                (
                    await session.scalars(
                        select(User)
                        .where(User.referral_code.is_(None))
                        .order_by(User.id)
                        .limit(batch_size)
                        .with_for_update(key_share=True, skip_locked=True)
                    )
                ).all()
            )
            for user in users:
                await ensure_code(session, user)
            total += len(users)
            remaining = bool(
                await session.scalar(
                    select(User.id).where(User.referral_code.is_(None)).limit(1)
                )
            )
        if not remaining:
            logger.info("referral_codes_backfilled count=%s", total)
            return total
        # Rows held by auth/other workers are retried without blocking HTTP startup.
        await asyncio.sleep(0 if users else 1)


async def credit_reward(
    session, wallet, amount, *, milestone=None, payment_id=None, source_details=None
):
    from .services import money, wallet_transaction

    source = (
        (ReferralReward.milestone == milestone)
        if milestone
        else (ReferralReward.payment_id == payment_id)
    )
    if await session.scalar(
        select(ReferralReward.id).where(
            ReferralReward.user_id == wallet.user_id, source
        )
    ):
        logger.info(
            "referral_duplicate_prevented user=%s milestone=%s payment=%s",
            wallet.user_id,
            milestone,
            payment_id,
        )
        return
    reward_id = uuid.uuid4()
    before_available, before_frozen = wallet.available_balance, wallet.frozen_balance
    wallet.bonus_balance = money((wallet.bonus_balance or 0) + amount)
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
    transaction.balance_breakdown["referral"] = source_details or {
        "source": "REFERRAL_MILESTONE",
        "milestone": milestone,
        "amount": str(amount),
    }
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
    logger.info(
        "referral_%s_recorded user=%s amount=%s source=%s",
        "milestone" if milestone else "commission",
        wallet.user_id,
        amount,
        milestone or payment_id,
    )


async def qualify_first_login(session, user, signed_start_param):
    """Called only after signature verification, while holding this user's row lock.

    A candidate must have been bound at the actual INSERT of this user, never on
    a later /start or login. Bot-first registration qualifies only on signed login.
    """
    if user.referral_registration_processed:
        if valid_code(signed_start_param):
            logger.info("referral_rejected user=%s reason=existing_account", user.id)
        return
    candidate = (
        valid_code(user.pending_referral_code)
        if user.referral_candidate_at_registration
        else None
    )
    user.referral_registration_processed = True
    user.pending_referral_code = None
    user.referral_candidate_at_registration = False
    if not candidate or candidate == user.referral_code:
        logger.info(
            "referral_rejected user=%s reason=no_registration_candidate_or_self",
            user.id,
        )
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
        logger.info(
            "referral_rejected user=%s reason=unknown_or_ineligible_referrer", user.id
        )
        return
    count = await referral_count(session, referrer.id)
    if count >= REFERRAL_LIMIT:
        logger.info("referral_limit_reached referrer=%s", referrer.id)
        return
    session.add(
        Referral(referred_user_id=user.id, referrer_id=referrer.id, slot=count + 1)
    )
    await session.flush()
    logger.info(
        "referral_created referrer=%s referred=%s count=%s",
        referrer.id,
        user.id,
        count + 1,
    )
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
    from .services import lock_wallets

    referrer_id = await session.scalar(
        select(Referral.referrer_id).where(Referral.referred_user_id == user_id)
    )
    wallets = await lock_wallets(session, user_id, referrer_id)
    if user_id not in wallets or (referrer_id and referrer_id not in wallets):
        raise HTTPException(409, "Wallet not found")
    return wallets[user_id], wallets.get(referrer_id)


async def credit_payment_commission(session, referrer_wallet, payment):
    if referrer_wallet is None or payment.status != "credited":
        return
    # Every paid top-up is represented once by StarPayment; payment_id is also
    # UNIQUE in rewards. No bonus, manual adjustment or refund calls this helper.
    amount = (payment.af_coin_amount * Decimal(COMMISSION_PERCENT) / 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if amount > 0:
        await session.flush()
        await credit_reward(
            session,
            referrer_wallet,
            amount,
            payment_id=payment.id,
            source_details={
                "source": "REAL_PAID_TOPUP",
                "source_topup_id": str(payment.id),
                "topup_amount": str(payment.af_coin_amount),
                "commission_percent": str(COMMISSION_PERCENT),
                "commission_amount": str(amount),
            },
        )


def invitation_text(first_name):
    # Telegram names are short; bound legacy/imported names to fit photo captions.
    name = (first_name or "").strip()[:128]
    heading = (
        f"{name} приглашает тебя в AutoFlow Market 🚗"
        if name and name != "Telegram User"
        else "Тебя приглашают в AutoFlow Market 🚗"
    )
    return (
        f"{heading}\n\nЗарабатывай вместе со мной в AutoFlow Market.\n\n"
        "Покупай и продавай машины из Car Parking 1 и Car Parking 2, приглашай друзей и получай бонусы."
    )
