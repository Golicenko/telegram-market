"""Bounded, read-only operational reporting. Never infer missing analytics as zero."""
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import require_admin
from .database import get_session
from .models import (AdminAction, Deal, Listing, Notification, StarPayment,
                     StarPaymentIntent, SupportTicket, TrainingPurchase, User, WithdrawalRequest)

router = APIRouter(prefix="/api/admin", tags=["admin-operations"])


def date_window(start, end, timezone, now=None):
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "Неизвестный часовой пояс") from None
    today = (now or datetime.now(UTC)).astimezone(zone).date()
    start, end = start or today, end or today
    if end < start or (end - start).days > 365 or end > today:
        raise HTTPException(422, "Выберите прошедший период не более 366 дней")
    return (datetime.combine(start, time.min, zone).astimezone(UTC),
            datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(UTC))


async def overview_data(session, start, end, timezone):
    from .training_analytics import confirmed_purchase
    lower, upper = date_window(start, end, timezone)

    async def count(model, field=None, *conditions):
        query = select(func.count()).select_from(model).where(*conditions)
        if field is not None:
            query = query.where(field >= lower, field < upper)
        return int(await session.scalar(query) or 0)

    payments = (await session.execute(select(func.count(), func.coalesce(func.sum(StarPayment.xtr_amount), 0))
        .where(StarPayment.status == "credited", StarPayment.processed_at >= lower, StarPayment.processed_at < upper))).one()
    cohort = dict((await session.execute(select(Deal.status, func.count())
        .where(Deal.created_at >= lower, Deal.created_at < upper).group_by(Deal.status))).all())
    # Status buckets describe today's state of orders created in the selected period,
    # not transitions or a reconstructed conversion funnel.
    metrics = {
        "new_users": await count(User, User.created_at),
        "orders_created": sum(cohort.values()),
        "orders_completed": await count(Deal, Deal.completed_at, Deal.status == "completed"),
        "orders_cancelled": await count(Deal, Deal.cancelled_at, Deal.status == "cancelled"),
        "seller_timeouts": await count(Deal, Deal.seller_timeout_processed_at),
        "topup_intents": await count(StarPaymentIntent, StarPaymentIntent.created_at),
        "credited_payments": int(payments[0]),
        "credited_stars": int(payments[1]),
        "withdrawals_requested": await count(WithdrawalRequest, WithdrawalRequest.created_at),
        "withdrawals_paid": await count(WithdrawalRequest, WithdrawalRequest.paid_at, WithdrawalRequest.status == "paid"),
        "training_paid": await count(TrainingPurchase, TrainingPurchase.created_at, confirmed_purchase()),
    }
    pending = {
        "withdrawals": await count(WithdrawalRequest, None, WithdrawalRequest.status.in_(["pending", "approved"])),
        "support": await count(SupportTicket, None, SupportTicket.status.in_(["new", "open", "in_progress"])),
        "deal_review": await count(Deal, None, Deal.needs_admin_review_at.is_not(None), Deal.status.not_in(["completed", "cancelled"])),
        "active_listings": await count(Listing, None, Listing.status == "active"),
        "notification_failures": await count(Notification, None, Notification.delivery_status == "failed"),
    }
    return {"timezone": timezone, "from_utc": lower, "until_utc_exclusive": upper,
            "generated_at": datetime.now(UTC), "metrics": metrics, "pending_now": pending,
            "created_order_current_statuses": cohort,
            "unavailable": {key: None for key in ("historical_dau", "miniapp_opens", "topup_screen_views", "training_views")},
            "definitions": {
                "new_users": "Созданные аккаунты, включая первый запуск бота",
                "topup_intents": "Созданные Stars-инвойсы всех назначений; не нажатия и не оплаты",
                "credited_payments": "Подтверждённые и зачисленные Stars-платежи всех назначений",
                "orders_cancelled": "Отменённые заказы, не сумма возвратов",
                "training_paid": "Оплаченные заказы обучения, включая впоследствии возвращённые",
                "pending_now": "Текущее состояние всех записей; не ограничено выбранным периодом",
                "unavailable": "Историческая аналитика посещений не собиралась; null не означает 0",
            }}


@router.get("/overview")
async def overview(
    start: date | None = None, end: date | None = None,
    timezone: str = Query(default="Europe/Bratislava", max_length=64),
    admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    return await overview_data(session, start, end, timezone)


@router.get("/audit")
async def audit(
    actor_id: uuid.UUID | None = None, target_id: uuid.UUID | None = None,
    action: str | None = Query(default=None, max_length=96),
    limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    query = select(AdminAction, User.first_name).join(User, User.id == AdminAction.admin_id)
    for field, value in ((AdminAction.admin_id, actor_id), (AdminAction.target_id, target_id), (AdminAction.action, action)):
        if value is not None:
            query = query.where(field == value)
    rows = (await session.execute(query.order_by(AdminAction.created_at.desc(), AdminAction.id.desc())
                                  .offset(offset).limit(limit + 1))).all()
    # Arbitrary historical metadata can contain internal payment payloads. Expose
    # only known balance snapshots, never raw dictionaries/tokens/charge IDs.
    allowed = {"available_before", "available_after", "frozen_before", "frozen_after", "from_status", "to_status"}
    return {"has_more": len(rows) > limit, "items": [
        {"id": entry.id, "actor_id": entry.admin_id, "actor_name": name,
         "action": entry.action, "target_type": entry.target_type, "target_id": entry.target_id,
         "reason": entry.reason, "created_at": entry.created_at,
         "changes": {k: v for k, v in (entry.metadata_json or {}).items() if k in allowed}}
        for entry, name in rows[:limit]]}
