"""Deal audit and scheduling only; money stays in the existing services."""
from datetime import UTC, datetime, timedelta
from sqlalchemy import select, func
from fastapi import HTTPException
from .models import Deal, DealEvent, Notification, User, Conversation


ACTIVITY_EVENTS = ("funds_reserved", "message_sent", "status_changed", "admin_resume")


def last_activity_query():
    return select(func.max(DealEvent.created_at)).where(
        DealEvent.deal_id == Deal.id, DealEvent.event_type.in_(ACTIVITY_EVENTS)
    ).correlate(Deal).scalar_subquery()


def audit_deal(session, deal, kind, actor_id=None, previous=None, details=None, request_id=None):
    event = DealEvent(deal_id=deal.id, actor_id=actor_id, event_type=kind,
        from_status=previous, to_status=deal.status, details=details or {}, request_id=request_id)
    session.add(event)
    return event


def stop_reminders(deal):
    deal.buyer_transfer_reminder_status = "skipped"
    deal.buyer_transfer_reminder_scheduled_at = None


def schedule_next_reminder(deal, now):
    round_number = int(deal.buyer_reminder_round or 0) + 1
    # First send immediately; subsequent gaps 2h, 4h, then 12h.
    hours = 2 if round_number == 1 else 4 if round_number == 2 else 12
    deal.buyer_reminder_round = round_number
    deal.buyer_transfer_reminder_status = "pending"
    deal.buyer_transfer_reminder_scheduled_at = now + timedelta(hours=hours)
    deal.buyer_transfer_reminder_claimed_at = None


async def recover_lifecycle_state(session, deal_id, now):
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if not deal or deal.status not in {"paid", "seller_contacted", "transfer_in_progress"}:
            return
        since = deal.transfer_started_at or deal.created_at
        if since.tzinfo is None:  # SQLite tests; PostgreSQL column is timestamptz.
            since = since.replace(tzinfo=UTC)
        last_action = await session.scalar(select(func.max(DealEvent.created_at)).where(
            DealEvent.deal_id == deal.id, DealEvent.event_type.in_(ACTIVITY_EVENTS)))
        if last_action:
            if last_action.tzinfo is None: last_action = last_action.replace(tzinfo=UTC)
            since = max(since, last_action)
        if not deal.needs_admin_review_at and now - since >= timedelta(hours=48):
            deal.needs_admin_review_at = now
            audit_deal(session, deal, "needs_admin_review")
            admins = list((await session.scalars(select(User).where(User.role == "admin"))).all())
            for admin in admins:
                session.add(Notification(user_id=admin.id, notification_type="deal_admin_review",
                    title="Сделка требует проверки", body=f"Сделка {deal.id} ожидает действия более 48 часов. Средства не выплачены автоматически.",
                    payload={"admin_deal_id": str(deal.id)}, delivery_status="pending"))
        if deal.status != "transfer_in_progress":
            return
        status = deal.buyer_transfer_reminder_status
        claimed = deal.buyer_transfer_reminder_claimed_at
        if claimed and claimed.tzinfo is None: claimed = claimed.replace(tzinfo=UTC)
        if status in {"sent", "failed", "not_scheduled"} or (status == "sending" and (not claimed or claimed <= now - timedelta(minutes=2))):
            # A crashed sender may have delivered: never replay that slot immediately.
            audit_deal(session, deal, "reminder_recovered", details={"previous_delivery_status": status})
            schedule_next_reminder(deal, now)


async def admin_nonfinancial_action(session, admin, deal_id, action, reason, request_id):
    if admin.role != "admin": raise HTTPException(403, "Требуется администратор")
    if len(reason.strip()) < 5: raise HTTPException(422, "Укажите причину")
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if not deal: raise HTTPException(404, "Сделка не найдена")
        previous_event = await session.scalar(select(DealEvent).where(DealEvent.deal_id == deal.id, DealEvent.request_id == request_id))
        if previous_event:
            if previous_event.actor_id != admin.id or previous_event.event_type != f"admin_{action}" or previous_event.details.get("reason") != reason:
                raise HTTPException(409, "Идентификатор запроса уже использован")
            return deal
        previous = deal.status
        if action == "review":
            if previous not in {"paid", "seller_contacted", "transfer_in_progress", "disputed"}: raise HTTPException(409, "Закрытая или неоплаченная сделка не может быть открыта повторно")
            deal.status = "disputed"
            stop_reminders(deal)
        elif action == "resume":
            if previous != "disputed": raise HTTPException(409, "Возобновить можно только незавершённый спор")
            from .models import SupportTicket
            active_ticket = await session.scalar(select(SupportTicket.id).where(SupportTicket.deal_id == deal.id, SupportTicket.status.in_(("new", "open", "in_progress"))).limit(1))
            if active_ticket: raise HTTPException(409, "Сначала закройте обращение поддержки с объяснением решения")
            deal.status = "transfer_in_progress" if deal.transfer_started_at else "seller_contacted"
            deal.needs_admin_review_at = None
            if deal.transfer_started_at:
                schedule_next_reminder(deal, datetime.now(UTC))
            elif deal.seller_response_deadline:
                # Explicitly resumed disputes must not inherit an already expired deadline.
                deal.seller_response_deadline = datetime.now(UTC) + timedelta(hours=24)
            if deal.conversation_id:
                conversation = await session.get(Conversation, deal.conversation_id)
                if conversation: conversation.archived_at = None
        elif action != "comment": raise HTTPException(422, "Действие не поддерживается")
        audit_deal(session, deal, f"admin_{action}", admin.id, previous, {"reason": reason}, request_id)
        from .models import AdminAction
        session.add(AdminAction(admin_id=admin.id, action=f"deal_{action}", target_type="deal", target_id=deal.id, reason=reason, metadata_json={"request_id": str(request_id)}))
        if action != "comment":
            for user_id in (deal.buyer_id, deal.seller_id):
                session.add(Notification(user_id=user_id, notification_type="deal_review_status", title="Проверка сделки",
                    body=f"Администратор обновил состояние сделки. {reason}", payload={"deal_id": str(deal.id)}, delivery_status="pending"))
        return deal
