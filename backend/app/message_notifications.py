"""Durable, recipient-scoped Telegram outbox. Never replay an ambiguous send."""
import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select, update, or_

from .chat_access import active_thread_clause
from .config import get_settings
from .database import SessionLocal
from .frontend import versioned_webapp_url
from .models import Conversation, ConversationMessage, Notification, User

logger = logging.getLogger("autoflow.message_notifications")


def unread_query(user_id):
    return select(ConversationMessage).join(Conversation, Conversation.id == ConversationMessage.conversation_id).where(
        or_(Conversation.buyer_id == user_id, Conversation.seller_id == user_id),
        or_(Conversation.conversation_type == "dialog", active_thread_clause()),
        ConversationMessage.sender_id != user_id,
        ConversationMessage.is_read.is_(False),
    )


def notification_text(count):
    if count == 1:
        return "🔔 У вас 1 новое уведомление"
    noun = "уведомление" if count % 10 == 1 and count % 100 != 11 else (
        "уведомления" if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14) else "уведомлений")
    adjective = "непрочитанное" if noun == "уведомление" else "непрочитанных"
    return f"🔔 У вас {count} {adjective} {noun}"


def recipient_is_viewing(user, conversation_id, now):
    return bool(user.viewing_conversation_id == conversation_id and user.chat_presence_at
                and user.chat_presence_at > now - timedelta(seconds=45))


async def claim_delivery(session, user_id, now):
    async with session.begin():
        user = await session.scalar(select(User).where(User.id == user_id).with_for_update(skip_locked=True))
        if not user:
            return None
        # No two processes send for this recipient concurrently.
        sending = await session.scalar(select(Notification.id).where(
            Notification.user_id == user_id, Notification.delivery_status == "sending").limit(1))
        if sending:
            return None
        pending = list((await session.scalars(select(Notification).where(
            Notification.user_id == user_id, Notification.delivery_status == "pending",
            or_(Notification.delivery_next_attempt_at.is_(None), Notification.delivery_next_attempt_at <= now),
        ).order_by(Notification.created_at, Notification.id).with_for_update())).all())
        if not pending:
            return None
        if not user.bot_started or user.is_blocked:
            for notice in pending:
                notice.delivery_status = "suppressed"
                notice.delivery_error = "bot_not_started" if not user.bot_started else "application_user_blocked"
            return None
        unread = list((await session.scalars(unread_query(user_id).with_only_columns(ConversationMessage.id))).all())
        unread_ids = {str(message_id) for message_id in unread}
        eligible = []
        for notice in pending:
            if notice.notification_type != "conversation_message":
                continue
            if notice.payload.get("message_id") not in unread_ids:
                notice.delivery_status = "suppressed"
                continue
            conversation_id = uuid.UUID(notice.payload["conversation_id"])
            if recipient_is_viewing(user, conversation_id, now):
                continue  # Wait for read receipt or for the presence lease to expire.
            eligible.append(notice)
        if eligible:
            latest = eligible[-1]
            text = notification_text(len(unread))
            params = {"conversation_id": latest.payload["conversation_id"]}
        else:
            eligible = [notice for notice in pending if notice.notification_type != "conversation_message"][:1]
            if not eligible:
                return None
            latest = eligible[0]
            text = latest.body
            params = ({"admin_user_id": latest.payload["seller_id"]}
                      if latest.notification_type in {"seller_blocked_bot", "seller_notice_failed"} else
                      {"admin_deal_id": latest.payload["admin_deal_id"]} if latest.payload.get("admin_deal_id") else
                      {"support_case": latest.payload["ticket_id"]} if latest.payload.get("ticket_id") else
                      {"deal_id": latest.payload["deal_id"]} if latest.notification_type == "deal_review_status" else
                      {"view": "profile"})
        for notice in eligible:
            notice.delivery_status = "sending"
            notice.delivery_claimed_at = now
            notice.delivery_attempts = int(notice.delivery_attempts or 0) + 1
        return {"ids": [notice.id for notice in eligible], "telegram_id": user.telegram_id, "text": text, "params": params}


async def send_delivery(job):
    settings = get_settings()
    base = settings.externally_reachable_url
    if not settings.bot_token or not base:
        return "failed", "configuration_missing"
    target = versioned_webapp_url(f"{base.rstrip('/')}/?{urlencode(job['params'])}")
    payload = {"chat_id": job["telegram_id"], "text": job["text"], "reply_markup": {
        "inline_keyboard": [[{"text": "Открыть", "web_app": {"url": target}}]]}}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"https://api.telegram.org/bot{settings.bot_token}/sendMessage", json=payload)
        data = response.json()
        if not isinstance(data, dict):
            return "unknown", "invalid_telegram_response"
        if response.is_success and data.get("ok") is True:
            return "sent", None
        if (response.status_code == 403 and data.get("error_code") == 403
                and "bot was blocked by the user" in str(data.get("description", "")).lower()):
            return "blocked", "telegram_bot_blocked_by_user"
        return "failed", f"telegram_http_{response.status_code}"
    except (httpx.HTTPError, ValueError):
        # Telegram has no sendMessage idempotency key. A timeout may mean delivered.
        return "unknown", "delivery_result_unknown"


async def queue_blocked_seller_alert(session, notice_id):
    """One durable admin alert per failed inactivity notice, never an application ban."""
    async with session.begin():
        notice = await session.scalar(select(Notification).where(Notification.id == notice_id).with_for_update())
        if (not notice or notice.delivery_status not in {"blocked", "failed", "unknown", "suppressed"}
                or notice.notification_type != "seller_timeout_cancelled"
                or notice.payload.get("admin_delivery_alert_queued")):
            return False
        seller = await session.get(User, notice.user_id)
        if not seller:
            return False
        settings = get_settings()
        administrators = list((await session.scalars(select(User).where(or_(
            User.telegram_id.in_(settings.admin_telegram_ids), User.role == "admin",
        )))).all())
        if not administrators:
            return False  # Keep the event pending for an administrator registered later.
        name = " ".join(filter(None, (seller.first_name, seller.last_name))) or "Пользователь"
        blocked = notice.delivery_status == "blocked"
        title = "Продавец заблокировал бота" if blocked else "Не удалось уведомить продавца"
        explanation = ("Telegram подтвердил блокировку бота пользователем." if blocked else
            "Доставка не подтверждена. Причина может быть связана с сетью или ограничениями Telegram; блокировка бота не подтверждена.")
        for admin in administrators:
            session.add(Notification(user_id=admin.id, notification_type="seller_blocked_bot" if blocked else "seller_notice_failed",
                title=title,
                body=f"⚠️ {title}\n\nИмя: {name}\nTelegram ID: {seller.telegram_id}\n\n"
                     "Его активные объявления сняты с публикации за неактивность. "
                     f"{explanation} "
                     "Это не блокировка пользователя в AutoFlow.",
                payload={"seller_id": str(seller.id), "source_notification_id": str(notice.id),
                         "deal_id": notice.payload.get("deal_id")}, delivery_status="pending"))
        notice.payload = {**notice.payload, "admin_delivery_alert_queued": True}
        return True


async def recover_message_notifications():
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        async with session.begin():
            await session.execute(update(Notification).where(
                Notification.delivery_status == "sending",
                Notification.delivery_claimed_at < now - timedelta(minutes=2),
            ).values(delivery_status="unknown", delivery_error="interrupted_delivery_unknown"))
    async with SessionLocal() as session:
        recipients = list((await session.scalars(select(Notification.user_id).where(
            Notification.delivery_status == "pending",
            or_(Notification.delivery_next_attempt_at.is_(None), Notification.delivery_next_attempt_at <= now),
        ).distinct().limit(100))).all())
    for user_id in recipients:
        try:
            async with SessionLocal() as session:
                job = await claim_delivery(session, user_id, now)
            if not job:
                continue
            status, error = await send_delivery(job)
            logger.info("message_delivery_result user_id=%s status=%s count=%s", user_id, status, len(job["ids"]))
            async with SessionLocal() as session:
                async with session.begin():
                    await session.execute(update(Notification).where(
                        Notification.id.in_(job["ids"]), Notification.delivery_status == "sending",
                    ).values(delivery_status=status, delivery_sent_at=datetime.now(UTC) if status == "sent" else None,
                             delivery_error=error))
                    if status == "failed":
                        # Only an explicit failure is retryable, never an ambiguous timeout.
                        await session.execute(update(Notification).where(
                            Notification.id.in_(job["ids"]), Notification.delivery_status == "failed",
                            Notification.delivery_attempts < 3,
                        ).values(delivery_status="pending", delivery_next_attempt_at=datetime.now(UTC) + timedelta(minutes=2)))
        except Exception as exc:
            logger.error("message_delivery_failed user_id=%s error_type=%s", user_id, type(exc).__name__)

    # Also recover a crash after recording Telegram's 403 but before enqueueing the admin notice.
    async with SessionLocal() as session:
        blocked_ids = list((await session.scalars(select(Notification.id).where(
            Notification.delivery_status.in_(("blocked", "failed", "unknown", "suppressed")), Notification.notification_type == "seller_timeout_cancelled",
            Notification.payload["admin_delivery_alert_queued"].as_boolean().is_not(True),
        ).limit(100))).all())
    for notice_id in blocked_ids:
        async with SessionLocal() as session:
            await queue_blocked_seller_alert(session, notice_id)


async def run_message_notification_worker():
    logger.info("message_notification_worker_started poll_seconds=5")
    while True:
        try:
            await recover_message_notifications()
        except Exception as exc:
            logger.error("message_worker_failed error_type=%s", type(exc).__name__)
        await asyncio.sleep(5)
