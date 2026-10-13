"""Seller progress/notification policy. Financial settlement stays in services."""
from datetime import UTC, datetime, timedelta
import logging
from sqlalchemy import select, or_
from .config import get_settings
from .models import Deal, DealEvent, Notification
from .deal_lifecycle import audit_deal

logger = logging.getLogger("autoflow.seller_orders")


def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def paid_order_body(deal, listing):
    game = {"car_parking_1":"Car Parking 1", "car_parking_2":"Car Parking 2"}.get(listing.game_version, "")
    return (f"🚗 Вашу машину купили — заказ #{str(deal.id)[:8]}\n"
        f"Автомобиль: {listing.brand} {listing.model} · {game}\nСумма: {deal.price_af_coins} AF\n"
        "Откройте заказ, примите его, проверьте ID покупателя и передайте машину.\n"
        f"Срок передачи: {utc(deal.seller_delivery_deadline):%d.%m.%Y %H:%M} UTC. "
        "Если ID ещё не указан — дождитесь его в сделке. Деньги пока удерживаются.")


async def queue_seller_order_reminder(session, deal_id, now=None):
    now = now or datetime.now(UTC)
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if (not deal or deal.status not in {"paid", "seller_contacted"}
                or deal.seller_accepted_at or deal.seller_responded_at or deal.transfer_started_at
                or deal.cancelled_at or deal.completed_at or not deal.seller_delivery_deadline):
            return False
        deadline = min(filter(None, (utc(deal.seller_delivery_deadline), utc(deal.seller_response_deadline))))
        if deadline <= now:
            return False
        # A real message before the buyer entered ID is still a meaningful reply.
        replied = await session.scalar(select(DealEvent.id).where(DealEvent.deal_id == deal.id,
            DealEvent.actor_id == deal.seller_id, DealEvent.event_type == "message_sent").limit(1))
        if replied:
            return False
        offsets = get_settings().seller_order_reminder_seconds
        due = [i + 1 for i, seconds in enumerate(offsets) if utc(deal.created_at) + timedelta(seconds=seconds) <= now]
        stage = max(due, default=0)
        if stage <= deal.seller_reminder_stage:
            return False
        # After downtime coalesce missed slots into one notice, not a burst.
        # Suppress older pending slots at claim time, not here: the outbox locks
        # User -> Notification, while inserting here obtains a User FK lock.
        # Taking an existing Notification lock here first would reverse that order.
        deal.seller_reminder_stage = stage
        body = (f"🚗 Заказ #{str(deal.id)[:8]} ожидает вашего ответа.\n"
            "Откройте сделку и нажмите «Принять заказ», если готовы передать машину.\n"
            f"Срок передачи: {utc(deal.seller_delivery_deadline):%d.%m.%Y %H:%M} UTC. "
            "Если заказ не принят — по истечении срока будет возврат. Если принят, но не передан — проверка администратора.")
        session.add(Notification(user_id=deal.seller_id, notification_type="seller_order_reminder",
            title="Заказ ожидает ответа", body=body, delivery_status="pending",
            payload={"deal_id":str(deal.id), "stage":stage}))
        audit_deal(session, deal, "seller_reminder_queued", details={"stage":stage, "offset_seconds":offsets[stage - 1]})
        return True


async def recover_seller_order_reminders():
    from .database import SessionLocal
    offsets = get_settings().seller_order_reminder_seconds
    if not offsets:
        return
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        ids = list((await session.scalars(select(Deal.id).where(
            Deal.status.in_(("paid", "seller_contacted")), Deal.seller_accepted_at.is_(None),
            Deal.seller_responded_at.is_(None), Deal.seller_reminder_stage < len(offsets),
            Deal.seller_delivery_deadline > now,
            or_(Deal.seller_response_deadline.is_(None), Deal.seller_response_deadline > now),
            or_(*( (Deal.seller_reminder_stage < i + 1) & (Deal.created_at <= now - timedelta(seconds=seconds))
                   for i, seconds in enumerate(offsets))),
            ~select(DealEvent.id).where(DealEvent.deal_id == Deal.id, DealEvent.actor_id == Deal.seller_id,
                DealEvent.event_type == "message_sent").exists(),
        ).order_by(Deal.created_at).limit(100))).all())
    for deal_id in ids:
        try:
            async with SessionLocal() as session:
                await queue_seller_order_reminder(session, deal_id, now)
        except Exception:
            logger.exception("Seller reminder failed for deal %s", deal_id)
