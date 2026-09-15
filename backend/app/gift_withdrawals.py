"""Server-quoted, manually fulfilled gifts. This module never calls sendGift."""
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from .config import get_settings
from .models import GiftWithdrawalQuote, WithdrawalRequest, Wallet, User


async def available_gifts():
    token = get_settings().bot_token
    if not token:
        raise HTTPException(503, "Каталог подарков временно недоступен. Попробуйте позже.")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"https://api.telegram.org/bot{token}/getAvailableGifts")
        data = response.json()
        if response.status_code != 200 or not data.get("ok"):
            raise ValueError("catalog unavailable")
        gifts = data["result"]["gifts"]
        # Only unlimited, non-premium gifts: no stock reservation is possible while
        # an administrator fulfils a pending request from their Telegram account.
        return sorted([
            {"id": gift["id"], "star_count": gift["star_count"]}
            for gift in gifts
            if isinstance(gift.get("id"), str) and type(gift.get("star_count")) is int
            and gift["star_count"] > 0 and not gift.get("is_premium")
            and not any(key in gift for key in ("total_count", "remaining_count", "personal_total_count", "personal_remaining_count"))
        ], key=lambda gift: (gift["star_count"], gift["id"]))
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        # Never expose/log the HTTP URL containing BOT_TOKEN.
        raise HTTPException(503, "Не удалось получить каталог подарков. Попробуйте позже.") from None


def calculate_quote(budget, gifts):
    budget = Decimal(budget)
    # The existing product requirement limits ordinary gift payouts to 350 Stars.
    ceiling = get_settings().payout_nft_threshold_stars
    limit = min(int((budget * Decimal("0.70")).to_integral_value(rounding=ROUND_FLOOR)), ceiling)
    plans = [None] * (limit + 1)
    plans[0] = []
    for amount in range(1, limit + 1):
        for gift in gifts:
            cost = gift["star_count"]
            if cost <= amount and plans[amount - cost] is not None:
                candidate = plans[amount - cost] + [gift["id"]]
                if plans[amount] is None or len(candidate) < len(plans[amount]):
                    plans[amount] = candidate
    payout = next((value for value in range(limit, 0, -1) if plans[value]), 0)
    if not payout:
        raise HTTPException(400, "Недостаточно заработанных AF Coins для доступного подарка и комиссии 30%.")
    gross = (Decimal(payout) / Decimal("0.70")).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    counts = Counter(plans[payout])
    costs = {gift["id"]: gift["star_count"] for gift in gifts}
    return {
        "gross_af": gross, "fee_af": gross - payout, "payout_stars": payout,
        "unspent_af": budget - gross,
        "gift_plan": [{"gift_id": key, "star_count": costs[key], "quantity": count} for key, count in counts.items()],
    }


async def preview_withdrawal(session, user, budget):
    gifts = await available_gifts()
    async with session.begin():
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
        if not wallet or wallet.earned_balance < budget:
            raise HTTPException(402, "Для вывода доступны только заработанные AF Coins. Уменьшите сумму.")
        values = calculate_quote(budget, gifts)
        quote = GiftWithdrawalQuote(user_id=user.id, budget=budget,
            gross_af=values["gross_af"], fee_af=values["fee_af"], payout_stars=values["payout_stars"],
            gift_plan=values["gift_plan"], expires_at=datetime.now(UTC) + timedelta(minutes=5))
        session.add(quote)
        await session.flush()
    return {"quote_id": str(quote.id), "expires_at": quote.expires_at, **values}


async def reserve_gift_withdrawal(session, user, quote_id, details):
    from .services import create_notification, money, wallet_snapshot, wallet_transaction
    # An identical quote is the idempotency key, including after admin completion.
    async with session.begin():
        existing = await session.scalar(select(WithdrawalRequest).where(WithdrawalRequest.gift_quote_id == quote_id, WithdrawalRequest.user_id == user.id))
        if existing:
            return existing
    catalog = {gift["id"]: gift["star_count"] for gift in await available_gifts()}
    async with session.begin():
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id).with_for_update())
        existing = await session.scalar(select(WithdrawalRequest).where(WithdrawalRequest.gift_quote_id == quote_id, WithdrawalRequest.user_id == user.id))
        if existing:
            return existing
        quote = await session.get(GiftWithdrawalQuote, quote_id)
        if not quote or quote.user_id != user.id:
            raise HTTPException(404, "Расчёт заявки не найден")
        expiry = quote.expires_at.replace(tzinfo=UTC) if quote.expires_at.tzinfo is None else quote.expires_at
        if expiry <= datetime.now(UTC):
            raise HTTPException(409, "Расчёт устарел. Рассчитайте заявку заново.")
        if any(catalog.get(item["gift_id"]) != item["star_count"] for item in quote.gift_plan):
            raise HTTPException(409, "Каталог подарков изменился. Рассчитайте заявку заново.")
        if not wallet or wallet.earned_balance < quote.gross_af:
            raise HTTPException(402, "Недостаточно заработанных AF Coins для подарков и комиссии.")
        before_available, before_frozen = wallet_snapshot(wallet)
        wallet.earned_balance = money(wallet.earned_balance - quote.gross_af)
        wallet.earned_frozen_balance = money(wallet.earned_frozen_balance + quote.gross_af)
        wallet.version += 1
        request = WithdrawalRequest(user_id=user.id, amount=quote.gross_af, payout_method="manual_gift",
            details=details or "Подарки Telegram", status="pending", gift_quote_id=quote.id,
            fee_af=quote.fee_af, payout_stars=quote.payout_stars, gift_plan=quote.gift_plan)
        session.add(request)
        await session.flush()
        session.add(wallet_transaction(wallet, "withdrawal_reserved", -request.amount, before_available, before_frozen,
            f"Резерв ручной выдачи подарков: {quote.payout_stars} Stars стоимости, комиссия {quote.fee_af} AF", withdrawal_id=request.id))
        admins = list((await session.scalars(select(User).where(User.role == "admin"))).all())
        plan = ", ".join(f'{item["quantity"]} × {item["star_count"]} Stars (ID {item["gift_id"]})' for item in quote.gift_plan)
        for admin in admins:
            await create_notification(session, admin.id, "withdrawal_created", "Новая заявка на подарки",
                f"Заявка {request.id}\nПользователь: {user.first_name}\n"
                f"Username: {'@' + user.username if user.username else 'не указан'}\nTelegram ID: {user.telegram_id}\n"
                f"Доступно до: {before_available} AF\nРезерв: {request.amount} AF\nКомиссия: {quote.fee_af} AF\n"
                f"Отправить: {plan}\nЗавершите заявку вручную только после отправки всех подарков.",
                {"withdrawal_id": str(request.id), "admin_withdrawal_id": str(request.id)})
    return request
