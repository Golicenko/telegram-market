"""Seller-requested reminders; existing DealEvent idempotency and notification outbox."""
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .config import get_settings
from .database import get_session
from .deal_lifecycle import audit_deal, delivery_deadline_expired, seller_has_accepted
from .models import Deal, DealEvent, Notification, User

router = APIRouter(prefix="/api/deals", tags=["deals"])


def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


class ReminderCreate(BaseModel):
    request_id: uuid.UUID


async def reminder_state(session, deal):
    gap = timedelta(seconds=get_settings().deal_manual_reminder_cooldown_seconds)
    result = {}
    for kind in ("id", "receipt"):
        last = await session.scalar(select(func.max(DealEvent.created_at)).where(DealEvent.deal_id == deal.id, DealEvent.event_type == f"manual_{kind}_reminder"))
        delivered = await session.scalar(select(func.max(Notification.delivery_sent_at)).where(
            Notification.user_id == deal.buyer_id, Notification.notification_type == "deal_manual_reminder",
            Notification.payload["deal_id"].astext == str(deal.id), Notification.payload["kind"].astext == kind))
        last = max(filter(None, [utc(last), utc(delivered)]), default=None)
        if kind == "receipt" and deal.buyer_transfer_reminder_sent_at:
            last = max(filter(None, [utc(last), utc(deal.buyer_transfer_reminder_sent_at)]))
        result[kind] = utc(last) + gap if last else None
    return result


async def manual_receipt_pause_until(session, deal, now):
    """Caller owns the Deal lock; automatic messages respect the manual outbox."""
    match = (Notification.user_id == deal.buyer_id, Notification.notification_type == "deal_manual_reminder",
             Notification.payload["deal_id"].astext == str(deal.id), Notification.payload["kind"].astext == "receipt")
    gap = timedelta(seconds=get_settings().deal_manual_reminder_cooldown_seconds)
    pending = await session.scalar(select(Notification.id).where(*match, Notification.delivery_status.in_(("pending", "sending"))).limit(1))
    if pending:
        return now+gap
    last = await session.scalar(select(func.max(Notification.delivery_sent_at)).where(*match))
    return utc(last)+gap if last and utc(last)+gap > now else None


async def seller_deal(session, actor, deal_id, lock=False):
    query = select(Deal).where(Deal.id == deal_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    deal = await session.scalar(query)
    if not deal:
        raise HTTPException(404, "Сделка не найдена")
    if actor.id != deal.seller_id:
        raise HTTPException(403, "Напоминание доступно только продавцу этой сделки")
    return deal


@router.get("/{deal_id}/reminders")
async def get_reminders(deal_id: uuid.UUID, actor: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    deal = await seller_deal(session, actor, deal_id)
    return {"next_allowed_at": await reminder_state(session, deal), "cooldown_seconds": get_settings().deal_manual_reminder_cooldown_seconds}


async def request_reminder(session, actor, deal_id, kind, request_id):
    now = datetime.now(UTC)
    async with session.begin():
        deal = await seller_deal(session, actor, deal_id, True)
        previous = await session.scalar(select(DealEvent).where(DealEvent.deal_id == deal.id, DealEvent.request_id == request_id))
        if previous:
            if previous.actor_id != actor.id or previous.event_type != f"manual_{kind}_reminder":
                raise HTTPException(409, "Идентификатор запроса уже использован")
            return {"queued": True, "replayed": True, "next_allowed_at": await reminder_state(session, deal)}
        valid = (deal.status in {"paid", "seller_contacted"} and seller_has_accepted(deal) and not deal.buyer_game_id and not delivery_deadline_expired(deal, now)) if kind == "id" else deal.status == "transfer_in_progress" and bool(deal.transfer_started_at)
        if not valid or deal.cancelled_at or deal.completed_at or deal.buyer_confirmed_at:
            raise HTTPException(409, "На этом этапе напоминание уже не требуется. Обновите сделку.")
        allowed = (await reminder_state(session, deal))[kind]
        if allowed and allowed > now:
            seconds = max(1, math.ceil((allowed-now).total_seconds()))
            raise HTTPException(429, "Напоминание уже отправлено. Повторите позже.", headers={"Retry-After": str(seconds)})
        automatic_queued = kind == "receipt" and deal.buyer_transfer_reminder_status in {"pending", "sending"} and deal.buyer_transfer_reminder_scheduled_at and utc(deal.buyer_transfer_reminder_scheduled_at) <= now + timedelta(seconds=30)
        already_pending = await session.scalar(select(Notification.id).where(Notification.user_id == deal.buyer_id,
            Notification.notification_type == "deal_manual_reminder", Notification.payload["deal_id"].astext == str(deal.id),
            Notification.payload["kind"].astext == kind, Notification.delivery_status.in_(("pending", "sending"))).limit(1))
        if not automatic_queued and not already_pending:
            session.add(Notification(user_id=deal.buyer_id, notification_type="deal_manual_reminder", delivery_status="pending",
                title="Нужен игровой ID" if kind == "id" else "Проверьте получение автомобиля",
                body="Продавец принял сделку и ожидает ваш игровой ID. Укажите ID в AutoFlow Market, чтобы получить автомобиль." if kind == "id" else "Продавец отметил передачу. Проверьте автомобиль на вашем ID и подтвердите получение только если он действительно получен. При проблеме откройте поддержку.",
                payload={"deal_id": str(deal.id), "kind": kind}))
        if kind == "receipt" and not automatic_queued and deal.buyer_transfer_reminder_status == "pending":
            # Only notification scheduling, never the delivery/escrow deadline.
            gap = timedelta(seconds=get_settings().deal_manual_reminder_cooldown_seconds)
            deal.buyer_transfer_reminder_scheduled_at = max(utc(deal.buyer_transfer_reminder_scheduled_at) or now, now+gap)
        audit_deal(session, deal, f"manual_{kind}_reminder", actor.id, details={"automatic_already_queued": bool(automatic_queued)}, request_id=request_id)
        await session.flush()
        return {"queued": True, "replayed": False, "next_allowed_at": await reminder_state(session, deal)}


@router.post("/{deal_id}/reminders/{kind}")
async def send_reminder(deal_id: uuid.UUID, kind: Literal["id", "receipt"], payload: ReminderCreate,
    actor: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return await request_reminder(session, actor, deal_id, kind, payload.request_id)
