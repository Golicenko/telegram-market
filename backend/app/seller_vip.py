"""Seller subscriptions; reuse the wallet ledger, listing pins and Telegram outbox.

Mutation lock order is recipient User -> subscription -> listing/wallet. Helpers
do not commit independently; a debit/allowance and its benefit share one commit.
No subscription operation transfers money to a seller or changes account gates.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .account_sales import is_enabled as account_sales_enabled
from .auth import get_current_user, require_admin
from .database import SessionLocal, get_session
from .models import (
    AdminAction, Listing, Notification, SellerVipAdminCommand, SellerVipPinUsage,
    SellerVipPlan, SellerVipSubscription, User, Wallet,
)
from .services import debit_spendable, money, wallet_snapshot, wallet_transaction

router = APIRouter(prefix="/api", tags=["Seller VIP"])
logger = logging.getLogger("autoflow.seller_vip")


def now_utc():
    return datetime.now(UTC)


def utc(value):
    """SQLite tests return naive timestamps; production PostgreSQL is UTC-aware."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def plan_output(plan):
    return {key: getattr(plan, key) for key in (
        "code", "title", "duration_days", "price_af", "pins_72h", "pins_24h", "car_limit", "account_limit",
    )}


def confirmation_fingerprint(plan, funding):
    values = plan_output(plan)
    values["price_af"] = str(money(values["price_af"]))
    values["funding"] = dict(zip(("purchased", "earned", "bonus"), (str(money(value)) for value in funding)))
    canonical = json.dumps(values, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def active_subscription(session, user_id, lock=False):
    now = now_utc()
    query = select(SellerVipSubscription).where(
        SellerVipSubscription.user_id == user_id,
        SellerVipSubscription.status == "active",
        SellerVipSubscription.starts_at <= now,
        SellerVipSubscription.expires_at > now,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(query)


async def active_limits(session, user_id):
    subscription = await active_subscription(session, user_id)
    return ({"car_limit": subscription.car_limit, "account_limit": subscription.account_limit,
             "subscription_id": subscription.id} if subscription else None)


async def active_listing_counts(session, user_id):
    result = await session.execute(select(Listing.product_kind, func.count()).where(
        Listing.seller_id == user_id, Listing.status == "active", Listing.deleted_at.is_(None),
    ).group_by(Listing.product_kind))
    counts = dict(result.all())
    return {"active_cars": counts.get("car", 0), "active_accounts": counts.get("account", 0)}


async def subscription_output(session, subscription, *, now=None, admin=False):
    now = now or now_utc()
    remaining = max(0, int((utc(subscription.expires_at) - now).total_seconds()))
    effective_status = ("expired" if subscription.status == "active" and remaining == 0 else subscription.status)
    result = {key: getattr(subscription, key) for key in (
        "id", "plan_code", "title", "starts_at", "expires_at", "pins_72h_remaining", "pins_72h_total",
        "pins_24h_remaining", "pins_24h_total", "car_limit", "account_limit",
    )}
    result.update(status=effective_status, remaining_seconds=remaining,
                  **await active_listing_counts(session, subscription.user_id))
    if admin:
        result.update(user_id=subscription.user_id, price_paid=subscription.price_paid,
                      purchased_af=subscription.purchased_af, earned_af=subscription.earned_af,
                      bonus_af=subscription.bonus_af, source=subscription.source,
                      payment_source="mixed" if subscription.bonus_af and (subscription.purchased_af or subscription.earned_af)
                      else "bonus" if subscription.bonus_af else "regular" if subscription.source == "purchase" else "admin")
    return result


async def required_plan(session, code):
    plan = await session.get(SellerVipPlan, code)
    if not plan or not plan.enabled:
        raise HTTPException(404, "Тариф VIP недоступен")
    return plan


def funding_quote(wallet, price):
    available = money(wallet.available_balance if wallet else 0)
    bonus = min(money(wallet.bonus_balance or 0) if wallet else Decimal(0), price)
    purchased = min(money(wallet.purchased_balance or 0) if wallet else Decimal(0), price - bonus)
    earned = min(money(wallet.earned_balance or 0) if wallet else Decimal(0), price - bonus - purchased)
    return {"bonus_af": money(bonus), "regular_af": money(purchased + earned), "purchased_af": money(purchased),
            "earned_af": money(earned), "missing_af": money(max(Decimal(0), price - available)), "available_af": available}


async def purchase_quote(session, user_id, code):
    plan = await required_plan(session, code)
    wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
    active = await active_subscription(session, user_id)
    values = funding_quote(wallet, money(plan.price_af))
    fingerprint = confirmation_fingerprint(plan, (values["purchased_af"], values["earned_af"], values["bonus_af"]))
    return {"server_now": now_utc(), "plan": plan_output(plan), "quote_fingerprint": fingerprint, **values,
            "can_purchase": values["missing_af"] == 0 and not active,
            "active_subscription_id": active.id if active else None}


async def lock_user(session, user_id):
    # NO KEY UPDATE serializes operations without conflicting with ledger FK checks.
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update(key_share=True)
                                .execution_options(populate_existing=True))
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    if user.is_blocked:
        raise HTTPException(403, "Пользователь заблокирован")
    return user


async def expire_stale_locked(session, user_id, now):
    stale = await session.scalar(select(SellerVipSubscription).where(
        SellerVipSubscription.user_id == user_id, SellerVipSubscription.status == "active",
        SellerVipSubscription.expires_at <= now,
    ).with_for_update())
    if stale:
        await mark_expired(session, stale)
        # Release the partial unique index before inserting a new active row.
        await session.flush()


def new_subscription(user_id, plan, request_id, now, *, source, funding=(Decimal(0),) * 3, transaction_id=None):
    purchased, earned, bonus = funding
    return SellerVipSubscription(
        id=uuid.uuid4(), user_id=user_id, request_id=request_id, plan_code=plan.code, title=plan.title,
        quote_fingerprint=confirmation_fingerprint(plan, funding),
        source=source, status="active", price_paid=money(sum(funding)), purchased_af=money(purchased),
        earned_af=money(earned), bonus_af=money(bonus), transaction_id=transaction_id,
        starts_at=now, expires_at=now + timedelta(days=plan.duration_days),
        pins_72h_total=plan.pins_72h, pins_72h_remaining=plan.pins_72h,
        pins_24h_total=plan.pins_24h, pins_24h_remaining=plan.pins_24h,
        car_limit=plan.car_limit, account_limit=plan.account_limit,
    )


class Purchase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_code: str = Field(min_length=1, max_length=32)
    request_id: uuid.UUID
    quote_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_code: str = Field(min_length=1, max_length=32)


async def purchase(session, user_id, payload):
    async with session.begin():
        await lock_user(session, user_id)
        old = await session.scalar(select(SellerVipSubscription).where(
            SellerVipSubscription.user_id == user_id, SellerVipSubscription.request_id == payload.request_id,
        ))
        if old:
            if old.plan_code != payload.plan_code or old.source != "purchase" or old.quote_fingerprint != payload.quote_fingerprint:
                raise HTTPException(409, "Идентификатор запроса уже используется")
            return old, True
        now = now_utc()
        await expire_stale_locked(session, user_id, now)
        if await active_subscription(session, user_id, lock=True):
            raise HTTPException(409, "VIP уже активен. Повторная покупка недоступна до окончания подписки.")
        plan = await required_plan(session, payload.plan_code)
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id).with_for_update()
                                      .execution_options(populate_existing=True))
        price = money(plan.price_af)
        values = funding_quote(wallet, price)
        if values["missing_af"] or not wallet:
            raise HTTPException(402, {"code": "insufficient_balance", **{key: str(value) for key, value in values.items()}})
        fingerprint = confirmation_fingerprint(plan, (values["purchased_af"], values["earned_af"], values["bonus_af"]))
        if payload.quote_fingerprint != fingerprint:
            raise HTTPException(409, {"code": "seller_vip_quote_changed", "message": "Условия тарифа или источники оплаты изменились. Проверьте новый расчёт перед подтверждением."})
        before = wallet_snapshot(wallet)
        funding = debit_spendable(wallet, price)  # Existing bonus -> purchased -> earned semantics.
        wallet.version += 1
        subscription = new_subscription(user_id, plan, payload.request_id, now, source="purchase", funding=funding)
        entry = wallet_transaction(wallet, "seller_vip_purchase", -price, *before,
                                   f"VIP-подписка: {plan.title}", external_reference=f"seller_vip:{subscription.id}", funding=funding)
        entry.id = uuid.uuid4()
        session.add(entry)
        await session.flush()
        subscription.transaction_id = entry.id
        session.add(subscription)
        await session.flush()
        session.add(Notification(user_id=user_id, notification_type="seller_vip_purchased", title="VIP активирован",
                                 body=f"👑 VIP активирован: {plan.title}. До {subscription.expires_at.isoformat()}. "
                                      "Привилегии доступны в разделе «Ещё» → «VIP для продавцов».",
                                 payload={"seller_vip_id": str(subscription.id)}, delivery_status="pending"))
    return subscription, False


@router.get("/seller-vip")
async def overview(response: Response, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "X-Telegram-Init-Data"
    plans = list((await session.scalars(select(SellerVipPlan).where(SellerVipPlan.enabled.is_(True))
                                      .order_by(SellerVipPlan.duration_days, SellerVipPlan.code))).all())
    active = await active_subscription(session, user.id)
    return {"server_now": now_utc(), "plans": [plan_output(plan) for plan in plans],
            "active_subscription": await subscription_output(session, active) if active else None,
            "account_sales_enabled": account_sales_enabled()}


@router.post("/seller-vip/quote")
async def quote(payload: QuoteRequest, response: Response, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    response.headers["Cache-Control"] = "private, no-store"
    return await purchase_quote(session, user.id, payload.plan_code)


@router.post("/seller-vip/purchases")
async def buy(payload: Purchase, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    subscription, replayed = await purchase(session, user.id, payload)
    return {"server_now": now_utc(), "subscription": await subscription_output(session, subscription), "replayed": replayed}


class PinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    listing_id: uuid.UUID
    duration_hours: Literal[24, 72]
    request_id: uuid.UUID


def pin_options(subscription):
    return ([{"duration_hours": hours, "remaining": getattr(subscription, f"pins_{hours}h_remaining"),
              "total": getattr(subscription, f"pins_{hours}h_total"), "cost_af": 0}
             for hours in (72, 24) if getattr(subscription, f"pins_{hours}h_total") > 0] if subscription else [])


def require_pinnable(listing, user_id):
    if not listing or listing.seller_id != user_id:
        raise HTTPException(404, "Объявление не найдено")
    if listing.product_kind != "car" or listing.status != "active" or listing.deleted_at or listing.reserved_by_deal_id:
        raise HTTPException(409, "Можно закрепить только активное объявление автомобиля")


@router.get("/seller-vip/pins/{listing_id}/quote")
async def pin_quote(listing_id: uuid.UUID, response: Response, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    response.headers["Cache-Control"] = "private, no-store"
    listing = await session.get(Listing, listing_id)
    require_pinnable(listing, user.id)
    active = await active_subscription(session, user.id)
    return {"server_now": now_utc(), "listing_id": listing.id,
            "active_subscription_id": active.id if active else None, "options": pin_options(active),
            "already_pinned": bool(listing.pinned and listing.pinned_until and utc(listing.pinned_until) > now_utc()),
            "pinned_until": listing.pinned_until}


async def consume_pin(session, user_id, listing, *, hours, request_id, subscription=None):
    """Caller transaction holds User, subscription and Listing, in that order."""
    require_pinnable(listing, user_id)
    subscription = subscription or await active_subscription(session, user_id, lock=True)
    if not subscription or hours not in (24, 72):
        raise HTTPException(409, "Действующий VIP с нужным закреплением не найден")
    now = now_utc()
    if utc(subscription.expires_at) <= now or subscription.status != "active":
        raise HTTPException(409, "Срок VIP закончился")
    if listing.pinned and listing.pinned_until and utc(listing.pinned_until) > now:
        raise HTTPException(409, "Объявление уже закреплено")
    field = f"pins_{hours}h_remaining"
    remaining = getattr(subscription, field)
    if remaining <= 0:
        raise HTTPException(409, "Бесплатные закрепления этого срока закончились")
    setattr(subscription, field, remaining - 1)
    listing.pinned, listing.pinned_until = True, now + timedelta(hours=hours)
    usage = SellerVipPinUsage(id=uuid.uuid4(), user_id=user_id, subscription_id=subscription.id,
                              listing_id=listing.id, request_id=request_id, duration_hours=hours, pinned_until=listing.pinned_until)
    session.add(usage)
    session.add(Notification(user_id=user_id, notification_type="vip_completed", title="VIP-закрепление активировано",
                             body=f"Объявление закреплено до {listing.pinned_until.isoformat()}. Использовано одно закрепление по подписке.",
                             payload={"listing_id": str(listing.id), "seller_vip_id": str(subscription.id), "pin_usage_id": str(usage.id)},
                             delivery_status="pending"))
    return usage


async def pin(session, user_id, payload):
    async with session.begin():
        await lock_user(session, user_id)
        old = await session.scalar(select(SellerVipPinUsage).where(
            SellerVipPinUsage.user_id == user_id, SellerVipPinUsage.request_id == payload.request_id,
        ))
        if old:
            if old.listing_id != payload.listing_id or old.duration_hours != payload.duration_hours:
                raise HTTPException(409, "Идентификатор запроса уже используется")
            return old, True
        subscription = await active_subscription(session, user_id, lock=True)
        if not subscription:
            raise HTTPException(409, "VIP-подписка не активна")
        listing = await session.scalar(select(Listing).where(Listing.id == payload.listing_id).with_for_update()
                                       .execution_options(populate_existing=True))
        usage = await consume_pin(session, user_id, listing, hours=payload.duration_hours,
                                  request_id=payload.request_id, subscription=subscription)
    return usage, False


@router.post("/seller-vip/pins")
async def use_pin(payload: PinRequest, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    usage, replayed = await pin(session, user.id, payload)
    return {"server_now": now_utc(), "usage_id": usage.id, "listing_id": usage.listing_id,
            "duration_hours": usage.duration_hours, "pinned_until": usage.pinned_until, "replayed": replayed}


class AdminCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    action: Literal["grant", "extend", "disable"]
    request_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=1000)
    confirmed: Literal[True]
    plan_code: str | None = Field(default=None, min_length=1, max_length=32)
    days: int | None = Field(default=None, ge=1, le=365)

    @model_validator(mode="after")
    def valid_command(self):
        self.reason = self.reason.strip()
        if len(self.reason) < 3:
            raise ValueError("Укажите причину")
        if (self.action == "grant" and (not self.plan_code or self.days is not None)
                or self.action == "extend" and (not self.days or self.plan_code is not None)
                or self.action == "disable" and (self.plan_code is not None or self.days is not None)):
            raise ValueError("Параметры не соответствуют действию")
        return self


async def apply_admin_command(session, admin, payload):
    if admin.role != "admin":
        raise HTTPException(403, "Administrator role required")
    parameters = payload.model_dump(mode="json", exclude={"request_id", "confirmed"})
    async with session.begin():
        await lock_user(session, payload.user_id)
        old = await session.scalar(select(SellerVipAdminCommand).where(
            SellerVipAdminCommand.admin_id == admin.id, SellerVipAdminCommand.request_id == payload.request_id,
        ))
        if old:
            if old.parameters != parameters:
                raise HTTPException(409, "Идентификатор запроса уже используется")
            return await session.get(SellerVipSubscription, old.subscription_id), True
        # Actor-scoped key can also target different recipients concurrently; a
        # transaction-scoped advisory lock protects the first command insert.
        if session.bind.dialect.name == "postgresql":
            from sqlalchemy import text
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                                  {"key": f"seller_vip_admin:{admin.id}:{payload.request_id}"})
            old = await session.scalar(select(SellerVipAdminCommand).where(
                SellerVipAdminCommand.admin_id == admin.id, SellerVipAdminCommand.request_id == payload.request_id,
            ))
            if old:
                if old.parameters != parameters:
                    raise HTTPException(409, "Идентификатор запроса уже используется")
                return await session.get(SellerVipSubscription, old.subscription_id), True
        now = now_utc()
        await expire_stale_locked(session, payload.user_id, now)
        subscription = await active_subscription(session, payload.user_id, lock=True)
        before = await subscription_output(session, subscription, admin=True) if subscription else None
        if payload.action == "grant":
            if subscription:
                raise HTTPException(409, "VIP уже активен. Используйте продление без сброса привилегий.")
            plan = await required_plan(session, payload.plan_code)
            subscription = new_subscription(payload.user_id, plan, uuid.uuid4(), now, source="admin")
            session.add(subscription)
            await session.flush()
        elif not subscription:
            raise HTTPException(409, "Действующий VIP не найден")
        elif payload.action == "extend":
            subscription.expires_at = utc(subscription.expires_at) + timedelta(days=payload.days)
            # A fresh warning for the new expiry is allowed, not duplicate for the
            # old expiry. Old notification remains in durable audit history.
            await suppress_pending_notice(session, subscription.warning_notification_id, "seller_vip_extended")
            subscription.warning_notification_id = None
        else:
            subscription.status = "disabled"
            await suppress_pending_notice(session, subscription.warning_notification_id, "seller_vip_disabled")
        after = await subscription_output(session, subscription, admin=True)
        from fastapi.encoders import jsonable_encoder
        session.add(AdminAction(admin_id=admin.id, action=f"seller_vip_{payload.action}", target_type="seller_vip",
                                target_id=subscription.id, reason=payload.reason,
                                metadata_json=jsonable_encoder({"before": before, "after": after, "request_id": payload.request_id})))
        session.add(SellerVipAdminCommand(admin_id=admin.id, user_id=payload.user_id, request_id=payload.request_id,
                                          parameters=parameters, subscription_id=subscription.id))
    return subscription, False


@router.get("/admin/seller-vip")
async def admin_list(user_id: uuid.UUID | None = None, status: Literal["active", "expired", "disabled"] | None = None,
                     limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000),
                     admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    now = now_utc()
    query = select(SellerVipSubscription, User).join(User, User.id == SellerVipSubscription.user_id)
    if user_id:
        query = query.where(SellerVipSubscription.user_id == user_id)
    if status == "active":
        query = query.where(SellerVipSubscription.status == "active", SellerVipSubscription.expires_at > now)
    elif status == "expired":
        query = query.where((SellerVipSubscription.status == "expired") | ((SellerVipSubscription.status == "active") & (SellerVipSubscription.expires_at <= now)))
    elif status:
        query = query.where(SellerVipSubscription.status == status)
    rows = (await session.execute(query.order_by(SellerVipSubscription.created_at.desc(), SellerVipSubscription.id.desc())
                                  .offset(offset).limit(limit + 1))).all()
    items = []
    for subscription, user in rows[:limit]:
        items.append({**await subscription_output(session, subscription, now=now, admin=True),
                      "name": " ".join(filter(None, (user.first_name, user.last_name))),
                      "telegram_id": user.telegram_id, "username": user.username})
    return {"server_now": now, "items": items, "has_more": len(rows) > limit}


@router.post("/admin/seller-vip/actions")
async def admin_action(payload: AdminCommand, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    subscription, replayed = await apply_admin_command(session, admin, payload)
    return {"server_now": now_utc(), "subscription": await subscription_output(session, subscription, admin=True), "replayed": replayed}


async def mark_expired(session, subscription):
    subscription.status = "expired"
    await suppress_pending_notice(session, subscription.warning_notification_id, "seller_vip_already_expired")
    if not subscription.expiry_notification_id:
        notice = Notification(id=uuid.uuid4(), user_id=subscription.user_id, notification_type="seller_vip_expired",
                              title="Срок действия вашего VIP закончился",
                              body="Срок действия вашего VIP закончился.\n\nВы можете приобрести VIP повторно в разделе «Ещё» → «VIP для продавцов».",
                              payload={"seller_vip_id": str(subscription.id)}, delivery_status="pending")
        session.add(notice)
        await session.flush()
        subscription.expiry_notification_id = notice.id


async def suppress_pending_notice(session, notice_id, reason):
    if notice_id:
        notice = await session.scalar(select(Notification).where(Notification.id == notice_id).with_for_update())
        if notice and notice.delivery_status in {"pending", "failed"}:
            notice.delivery_status = "suppressed"
            notice.delivery_error = reason


async def process_expiries(session, *, now=None):
    """Durable once-per-expiry outbox rows, also recovered after server downtime."""
    now = now or now_utc()
    async with session.begin():
        subscriptions = list((await session.scalars(select(SellerVipSubscription).where(
            SellerVipSubscription.status == "active", SellerVipSubscription.expires_at <= now + timedelta(hours=24),
            (SellerVipSubscription.warning_notification_id.is_(None)) | (SellerVipSubscription.expires_at <= now),
        ).order_by(SellerVipSubscription.expires_at, SellerVipSubscription.id).limit(100)
            .with_for_update(skip_locked=True))).all())
        for subscription in subscriptions:
            if utc(subscription.expires_at) <= now:
                await mark_expired(session, subscription)
            elif not subscription.warning_notification_id:
                notice = Notification(id=uuid.uuid4(), user_id=subscription.user_id, notification_type="seller_vip_expiring",
                                      title="Ваш VIP скоро закончится",
                                      body="👑 Ваш VIP скоро закончится\n\nДо окончания VIP-подписки осталось менее 24 часов.",
                                      payload={"seller_vip_id": str(subscription.id), "expires_at": utc(subscription.expires_at).isoformat()},
                                      delivery_status="pending")
                session.add(notice)
                await session.flush()
                subscription.warning_notification_id = notice.id


async def run_worker():
    while True:
        try:
            async with SessionLocal() as session:
                await process_expiries(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("seller_vip_worker_failed error_type=%s", type(exc).__name__)
        await asyncio.sleep(30)
