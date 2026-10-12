"""UI observations and authoritative financial projections; never writes money."""
import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import Date, and_, cast, delete, func, literal, select, union_all
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .admin_operations import date_window
from .auth import get_current_user, require_admin
from .config import get_settings
from .database import SessionLocal, get_session
from .models import (AnalyticsEvent, AnalyticsState, Deal, Listing, Referral, ReferralReward,
                     StarPayment, StarPaymentIntent, TrainingProduct, TrainingPurchase, User,
                     WalletTransaction, WithdrawalRequest)

router = APIRouter(prefix="/api", tags=["analytics"])
CLIENT_EVENTS = {"miniapp_opened", "market_viewed", "listing_viewed", "order_checkout_started",
                 "topup_screen_opened", "topup_failure", "training_list_view", "training_product_view",
                 "training_buy_click", "training_checkout_started", "training_support_opened", "support_opened"}


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_name: Literal["miniapp_opened", "market_viewed", "listing_viewed", "order_checkout_started",
                        "topup_screen_opened", "topup_failure", "training_list_view", "training_product_view",
                        "training_buy_click", "training_checkout_started", "training_support_opened", "support_opened"]
    event_id: uuid.UUID
    session_id: uuid.UUID
    entity_id: uuid.UUID | None = None
    platform: Literal["ios", "android", "tdesktop", "macos", "web", "unknown"] = "unknown"
    source: Literal["navigation", "listing", "training", "profile", "deeplink", "unknown"] = "unknown"
    reason: Literal["network", "cancelled", "telegram_failed", "api_rejected", "unsupported", "unknown"] | None = None

    @model_validator(mode="after")
    def scoped_entity(self):
        needs_entity = self.event_name in {"listing_viewed", "order_checkout_started", "training_product_view", "training_buy_click", "training_checkout_started", "training_support_opened"}
        if needs_entity != (self.entity_id is not None):
            raise ValueError("Entity is required only for product/listing observations")
        if (self.event_name == "topup_failure") != (self.reason is not None):
            raise ValueError("Reason is required only for client-observed payment failures")
        return self


async def record_observation(session, user, payload, now=None):
    now = now or datetime.now(UTC)
    # Serialize a bounded per-account rate limit across all Railway replicas.
    await session.scalar(select(User.id).where(User.id == user.id).with_for_update(key_share=True))
    previous = await session.get(AnalyticsEvent, payload.event_id)
    if previous:
        if previous.user_id != user.id or (previous.event_name, previous.session_id, previous.entity_id, previous.reason) != (payload.event_name, payload.session_id, payload.entity_id, payload.reason):
            raise HTTPException(409, "Event identity already used")
        return False
    if payload.entity_id:
        model = TrainingProduct if payload.event_name.startswith("training_") else Listing
        if not await session.get(model, payload.entity_id):
            raise HTTPException(404, "Product not found")
    bucket = 0 if payload.event_name == "miniapp_opened" else int(now.timestamp()) // 30
    key = hashlib.sha256(f"{payload.session_id}:{payload.event_name}:{payload.entity_id}:{payload.reason}:{bucket}".encode()).hexdigest()
    if await session.scalar(select(AnalyticsEvent.id).where(AnalyticsEvent.user_id == user.id, AnalyticsEvent.dedup_key == key)):
        return False
    count = await session.scalar(select(func.count()).select_from(AnalyticsEvent).where(AnalyticsEvent.user_id == user.id, AnalyticsEvent.created_at >= now - timedelta(hours=1)))
    if count >= 120:
        raise HTTPException(429, "Observation rate limit", headers={"Retry-After": "3600"})
    result = await session.execute(insert(AnalyticsEvent).values(id=payload.event_id, user_id=user.id,
        event_name=payload.event_name, session_id=payload.session_id, entity_id=payload.entity_id,
        platform=payload.platform, source=payload.source, reason=payload.reason, created_at=now, dedup_key=key)
        .on_conflict_do_nothing().returning(AnalyticsEvent.id))
    return result.scalar_one_or_none() is not None


@router.post("/analytics/events", status_code=204)
async def observation(payload: Observation, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    if get_settings().analytics_enabled:
        await record_observation(session, user, payload)
        await session.commit()
    return Response(status_code=204)


def financial_projection(lower, upper):
    """Each event projects one existing unique record, not a replayable UI callback."""
    def source(name, model, timestamp, amount=None, unit="count", *conditions):
        return select(literal(name).label("event"), func.count().label("count"),
                      func.coalesce(func.sum(amount), 0).label("amount") if amount is not None else literal(0).label("amount"),
                      literal(unit).label("unit")).select_from(model).where(timestamp >= lower, timestamp < upper, *conditions)
    return union_all(
        source("account_created", User, User.created_at),
        source("listing_created", Listing, Listing.created_at),
        source("order_paid", WalletTransaction, WalletTransaction.created_at, -WalletTransaction.amount, "AF", WalletTransaction.transaction_type == "protection_hold", WalletTransaction.related_deal_id.is_not(None)),
        source("order_completed", WalletTransaction, WalletTransaction.created_at, WalletTransaction.amount, "AF", WalletTransaction.transaction_type == "sale_income", WalletTransaction.related_deal_id.is_not(None)),
        source("order_refunded", WalletTransaction, WalletTransaction.created_at, WalletTransaction.amount, "AF", WalletTransaction.transaction_type.in_(["refund", "dispute_refund"]), WalletTransaction.related_deal_id.is_not(None)),
        source("listing_pinned", WalletTransaction, WalletTransaction.created_at, -WalletTransaction.amount, "AF", WalletTransaction.transaction_type == "listing_promotion"),
        source("seller_order_accepted", Deal, Deal.seller_accepted_at),
        source("seller_timeout", Deal, Deal.seller_timeout_processed_at),
        source("topup_checkout_started", StarPaymentIntent, StarPaymentIntent.created_at),
        source("topup_success", StarPayment, StarPayment.processed_at, StarPayment.xtr_amount, "Stars", StarPayment.status == "credited"),
        source("withdrawal_requested", WithdrawalRequest, WithdrawalRequest.created_at, WithdrawalRequest.amount, "AF"),
        source("withdrawal_paid", WithdrawalRequest, WithdrawalRequest.paid_at, WithdrawalRequest.payout_stars, "Stars", WithdrawalRequest.status == "paid"),
        source("training_paid", TrainingPurchase, TrainingPurchase.created_at, TrainingPurchase.price_af_coins, "AF"),
        source("referral_registered", Referral, Referral.qualified_at),
        source("referral_milestone_paid", ReferralReward, ReferralReward.created_at, ReferralReward.amount, "AF", ReferralReward.milestone.is_not(None)),
        source("referral_topup_commission_paid", ReferralReward, ReferralReward.created_at, ReferralReward.amount, "AF", ReferralReward.payment_id.is_not(None)),
    )


async def report_data(session, start, end, timezone):
    lower, upper = date_window(start, end, timezone)
    state = await session.get(AnalyticsState, 1)
    enabled = get_settings().analytics_enabled
    retained_from = max(state.retained_from, datetime.now(UTC) - timedelta(days=get_settings().analytics_retention_days)) if state else None
    measured_from = max(lower, retained_from) if retained_from else upper
    available = bool(enabled and state and measured_from < upper)
    rows = (await session.execute(financial_projection(lower, upper))).all()
    # Previous calendar period has the same number of LOCAL dates, including DST.
    zone_start = lower.astimezone(ZoneInfo(timezone)).date()
    zone_end = upper.astimezone(ZoneInfo(timezone)).date()
    days = (zone_end - zone_start).days
    previous_lower, previous_upper = date_window(zone_start - timedelta(days=days), zone_start - timedelta(days=1), timezone)
    previous = (await session.execute(financial_projection(previous_lower, previous_upper))).all()
    server = {row.event: {"count": row._mapping["count"], "amount": row.amount, "unit": row.unit} for row in rows}
    previous_server = {row.event: {"count": row._mapping["count"], "amount": row.amount, "unit": row.unit} for row in previous}
    for values, begin, finish in ((server, lower, upper), (previous_server, previous_lower, previous_upper)):
        missing = await session.scalar(select(func.count()).select_from(WithdrawalRequest).where(WithdrawalRequest.status == "paid", WithdrawalRequest.paid_at >= begin, WithdrawalRequest.paid_at < finish, WithdrawalRequest.payout_stars.is_(None)))
        values["withdrawal_paid"]["amount_unknown_records"] = missing
        if missing:
            values["withdrawal_paid"]["amount"] = None
    observations = []
    daily = []
    funnels = None
    if available:
        event_range = [AnalyticsEvent.created_at >= measured_from, AnalyticsEvent.created_at < upper]
        observations = [dict(row._mapping) for row in (await session.execute(select(
            AnalyticsEvent.event_name, AnalyticsEvent.platform, AnalyticsEvent.reason,
            func.count().label("events"), func.count(func.distinct(AnalyticsEvent.user_id)).label("users"))
            .where(*event_range).group_by(AnalyticsEvent.event_name, AnalyticsEvent.platform, AnalyticsEvent.reason))).all()]
        day = cast(func.timezone(timezone, AnalyticsEvent.created_at), Date)
        daily = [dict(row._mapping) for row in (await session.execute(select(day.label("day"),
            func.count(func.distinct(AnalyticsEvent.user_id)).label("dau"), func.count().filter(AnalyticsEvent.event_name == "miniapp_opened").label("opens"))
            .where(*event_range).group_by(day).order_by(day))).all()]
        # Cohorts, not misleading ratios between unrelated event totals.
        opened = select(AnalyticsEvent.user_id, func.min(AnalyticsEvent.created_at).label("first_at")).where(*event_range, AnalyticsEvent.event_name == "topup_screen_opened").group_by(AnalyticsEvent.user_id).subquery()
        intents = select(StarPaymentIntent.id, StarPaymentIntent.user_id, StarPaymentIntent.invoice_payload).join(opened, opened.c.user_id == StarPaymentIntent.user_id).where(StarPaymentIntent.created_at >= opened.c.first_at, StarPaymentIntent.created_at < upper).subquery()
        paid = select(func.count(func.distinct(intents.c.user_id))).select_from(intents).join(StarPayment, StarPayment.raw_payload["invoice_payload"].astext == intents.c.invoice_payload).where(StarPayment.status == "credited", StarPayment.processed_at < upper)
        funnels = {"topup": {"opened_users": await session.scalar(select(func.count()).select_from(opened)),
            "invoice_users": await session.scalar(select(func.count(func.distinct(intents.c.user_id)))),
            "paid_users": await session.scalar(paid)}}
        views = select(AnalyticsEvent.user_id, AnalyticsEvent.entity_id, func.min(AnalyticsEvent.created_at).label("first_at")).where(*event_range, AnalyticsEvent.event_name == "training_product_view").group_by(AnalyticsEvent.user_id, AnalyticsEvent.entity_id).subquery()
        matched = [TrainingPurchase.buyer_id == views.c.user_id, TrainingPurchase.product_id == views.c.entity_id,
                   TrainingPurchase.created_at >= views.c.first_at, TrainingPurchase.created_at < upper]
        paid_training = select(func.count()).select_from(views).join(TrainingPurchase, and_(*matched))
        funnels["training"] = {"viewed_user_products": await session.scalar(select(func.count()).select_from(views)), "paid_user_products": await session.scalar(paid_training)}
    lag = func.extract("epoch", Deal.seller_accepted_at - Deal.created_at)
    timing = (await session.execute(select(func.count(), func.avg(lag), func.percentile_cont(0.5).within_group(lag), func.percentile_cont(0.9).within_group(lag)).where(Deal.created_at >= lower, Deal.created_at < upper, Deal.seller_accepted_at.is_not(None), Deal.seller_accepted_at >= Deal.created_at))).one()
    return {"timezone": timezone, "from_utc": lower, "until_utc_exclusive": upper,
        "collection_started_at": state.started_at if state else None, "retained_from": retained_from,
        "client_data_available": available, "client_period_partial": not available or measured_from > lower,
        "client_observations": observations if available else None, "daily_activity": daily if available else None,
        "funnels": funnels, "server_events": server, "previous_server_events": previous_server,
        "seller_accept_seconds": {"sample": timing[0], "mean": timing[1], "median": timing[2], "p90": timing[3]},
        "definitions": ["Время Europe/Bratislava по умолчанию; события хранятся в UTC.",
            "Клиентские просмотры/ошибки: авторизованные наблюдения, не доказательство оплаты; ограничены частотой.",
            "Денежные события — проекция существующих уникальных записей ledger/payments. Повтор webhook не добавляет новую запись.",
            "Пополнения: все назначения Stars-инвойсов; paid в воронке связан с конкретным invoice_payload на сервере.",
            "Воронки считают одну когорту внутри периода; платёж после конца периода в неё не входит.",
            "Время ответа = явное принятие заказа; только принятые заказы. Это не время первого сообщения.",
            "История до начала сбора/срока хранения отсутствует, а не равна нулю. Отключённая аналитика и сетевые сбои снижают полноту.",
            "listing_pinned учитывает только платные ledger-операции, не бесплатные административные закрепления."]}


@router.get("/admin/analytics/training")
async def training_report(start: date | None = None, end: date | None = None,
    timezone: str = Query(default="Europe/Bratislava", max_length=64),
    limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    lower, upper = date_window(start, end, timezone)
    state = await session.get(AnalyticsState, 1)
    retained_from = max(state.retained_from, datetime.now(UTC) - timedelta(days=get_settings().analytics_retention_days)) if state else upper
    measured_from = max(lower, retained_from)
    available = bool(get_settings().analytics_enabled and state and measured_from < upper)
    views = select(AnalyticsEvent.entity_id, func.count().label("views"), func.count(func.distinct(AnalyticsEvent.user_id)).label("viewers")).where(AnalyticsEvent.event_name == "training_product_view", AnalyticsEvent.created_at >= measured_from, AnalyticsEvent.created_at < upper).group_by(AnalyticsEvent.entity_id).subquery()
    sales = select(TrainingPurchase.product_id, func.count().label("paid"), func.count().filter(TrainingPurchase.delivery_status == "failed").label("delivery_failed"), func.count().filter((TrainingPurchase.delivery_status == "delivered") | (TrainingPurchase.status == "completed")).label("fulfilled")).where(TrainingPurchase.created_at >= lower, TrainingPurchase.created_at < upper).group_by(TrainingPurchase.product_id).subquery()
    rows = (await session.execute(select(TrainingProduct.id, TrainingProduct.title,
        func.coalesce(views.c.views, 0).label("views"), func.coalesce(views.c.viewers, 0).label("viewers"),
        func.coalesce(sales.c.paid, 0).label("paid"), func.coalesce(sales.c.delivery_failed, 0).label("delivery_failed"), func.coalesce(sales.c.fulfilled, 0).label("fulfilled"))
        .outerjoin(views, views.c.entity_id == TrainingProduct.id).outerjoin(sales, sales.c.product_id == TrainingProduct.id)
        .order_by(func.coalesce(views.c.views, 0).desc(), TrainingProduct.id).limit(limit + 1).offset(offset))).all()
    items = [dict(row._mapping) for row in rows[:limit]]
    if not available:
        for item in items:
            item["views"] = item["viewers"] = None
    return {"items": items, "has_more": len(rows) > limit, "views_partial": not available or measured_from > lower,
            "definition": "Просмотры и оплаты за период; выдача/ошибки — текущее состояние этих покупок. Это не когортная конверсия."}


@router.get("/admin/analytics")
async def report(start: date | None = None, end: date | None = None,
                 timezone: str = Query(default="Europe/Bratislava", max_length=64),
                 admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return await report_data(session, start, end, timezone)


async def prune_observations(session, now=None):
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=get_settings().analytics_retention_days)
    state = await session.scalar(select(AnalyticsState).where(AnalyticsState.id == 1).with_for_update())
    if state:
        state.retained_from = max(state.retained_from, cutoff if get_settings().analytics_enabled else now)
    batch = select(AnalyticsEvent.id).where(AnalyticsEvent.created_at < cutoff).order_by(AnalyticsEvent.created_at).limit(10000)
    result = await session.execute(delete(AnalyticsEvent).where(AnalyticsEvent.id.in_(batch)))
    return result.rowcount


async def run_analytics_retention():
    while True:
        try:
            async with SessionLocal() as session, session.begin():
                await prune_observations(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.getLogger(__name__).warning("analytics_retention_failed type=%s", type(exc).__name__)
        await asyncio.sleep(3600)
