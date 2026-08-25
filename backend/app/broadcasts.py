import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .bot import send_bot_notification, send_broadcast_message
from .database import SessionLocal
from .models import AdminBroadcast, AdminBroadcastRecipient, User


BROADCAST_COMMANDS = ("#рассылка", "/рассылка")
logger = logging.getLogger("autoflow.broadcasts")


async def send_with_bounded_rate_limit(telegram_id: int, *, text: str, photo: str | None):
    result = await send_broadcast_message(telegram_id, text=text, photo=photo)
    if (
        not result.success
        and result.error_type == "rate_limited"
        and result.retry_after is not None
        and 0 < result.retry_after <= 30
    ):
        await asyncio.sleep(result.retry_after)
        result = await send_broadcast_message(telegram_id, text=text, photo=photo)
    return result


def parse_broadcast_command(value: str | None) -> str | None:
    """Return the broadcast body, or None when the message is not a command."""
    text = (value or "").strip()
    folded = text.casefold()
    for command in BROADCAST_COMMANDS:
        if folded == command:
            return ""
        prefix = f"{command} "
        if folded.startswith(prefix):
            return text[len(prefix):].strip()
    return None


async def create_admin_broadcast(
    session: AsyncSession,
    *,
    telegram_update_id: int | None,
    admin_telegram_id: int,
    content_type: str,
    text: str,
    photo_file_id: str | None = None,
    client_request_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Create one job and a durable snapshot of its eligible recipients."""
    statement = (
        pg_insert(AdminBroadcast)
        .values(
            telegram_update_id=telegram_update_id,
            client_request_id=client_request_id,
            admin_telegram_id=admin_telegram_id,
            content_type=content_type,
            text=text,
            photo_file_id=photo_file_id,
            status="queued",
        )
        # Covers a retried Telegram update/client request and an already active job.
        .on_conflict_do_nothing()
        .returning(AdminBroadcast.id)
    )
    broadcast_id = await session.scalar(statement)
    if broadcast_id is None:
        await session.rollback()
        return None
    recipients = list((await session.execute(
        select(User.id, User.telegram_id)
        .where(User.bot_started.is_(True))
        .order_by(User.telegram_id)
    )).all())
    unique_recipients = {telegram_id: user_id for user_id, telegram_id in recipients}
    session.add_all([
        AdminBroadcastRecipient(
            broadcast_id=broadcast_id,
            user_id=user_id,
            telegram_id=telegram_id,
            status="pending",
        )
        for telegram_id, user_id in unique_recipients.items()
    ])
    broadcast = await session.get(AdminBroadcast, broadcast_id)
    if broadcast:
        broadcast.total_recipients = len(unique_recipients)
    await session.commit()
    logger.info(
        "broadcast_queued broadcast_id=%s total_recipients=%s status=queued",
        broadcast_id,
        len(unique_recipients),
    )
    return broadcast_id


async def run_admin_broadcast(broadcast_id: uuid.UUID) -> None:
    """Send each durable recipient at most once, even with concurrent workers."""
    admin_telegram_id = None
    async with SessionLocal() as session:
        async with session.begin():
            broadcast = await session.scalar(
                select(AdminBroadcast).where(AdminBroadcast.id == broadcast_id).with_for_update()
            )
            if not broadcast or broadcast.status not in {"queued", "running"}:
                return
            broadcast.status = "running"
            broadcast.started_at = broadcast.started_at or datetime.now(UTC)
            content_type = broadcast.content_type
            text = broadcast.text
            photo_file_id = broadcast.photo_file_id
            admin_telegram_id = broadcast.admin_telegram_id
            broadcast.sent_count = int(await session.scalar(select(func.count()).select_from(AdminBroadcastRecipient).where(
                AdminBroadcastRecipient.broadcast_id == broadcast_id,
                AdminBroadcastRecipient.status == "sent",
            )) or 0)
            broadcast.failed_count = int(await session.scalar(select(func.count()).select_from(AdminBroadcastRecipient).where(
                AdminBroadcastRecipient.broadcast_id == broadcast_id,
                AdminBroadcastRecipient.status == "failed",
            )) or 0)
            started_at = broadcast.started_at
            total_recipients = broadcast.total_recipients
    logger.info(
        "broadcast_started broadcast_id=%s started_at=%s total_recipients=%s status=running",
        broadcast_id, started_at, total_recipients,
    )

    try:
        while True:
            async with SessionLocal() as session:
                async with session.begin():
                    recipient = await session.scalar(
                        select(AdminBroadcastRecipient)
                        .where(
                            AdminBroadcastRecipient.broadcast_id == broadcast_id,
                            AdminBroadcastRecipient.status == "pending",
                        )
                        .order_by(AdminBroadcastRecipient.telegram_id)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    if not recipient:
                        break
                    recipient.status = "sending"
                    recipient.attempts += 1
                    recipient.started_at = datetime.now(UTC)
                    recipient_id = recipient.id
                    telegram_id = recipient.telegram_id

            result = await send_with_bounded_rate_limit(
                telegram_id,
                text=text,
                photo=photo_file_id if content_type == "photo" else None,
            )

            async with SessionLocal() as session:
                async with session.begin():
                    recipient = await session.scalar(
                        select(AdminBroadcastRecipient)
                        .where(AdminBroadcastRecipient.id == recipient_id)
                        .with_for_update()
                    )
                    if not recipient or recipient.status != "sending":
                        continue
                    recipient.status = "sent" if result.success else "failed"
                    recipient.error_type = result.error_type
                    recipient.error_message = result.error_message
                    recipient.completed_at = datetime.now(UTC)
                    broadcast = await session.scalar(
                        select(AdminBroadcast).where(AdminBroadcast.id == broadcast_id).with_for_update()
                    )
                    if broadcast and broadcast.status == "running":
                        if result.success:
                            broadcast.sent_count += 1
                        else:
                            broadcast.failed_count += 1
            if not result.success:
                logger.warning(
                    "broadcast_recipient_failed broadcast_id=%s telegram_id=%s error_type=%s",
                    broadcast_id, telegram_id, result.error_type or "unknown",
                )
    except Exception as exc:
        async with SessionLocal() as session:
            async with session.begin():
                broadcast = await session.scalar(
                    select(AdminBroadcast).where(AdminBroadcast.id == broadcast_id).with_for_update()
                )
                if broadcast and broadcast.status == "running":
                    broadcast.status = "failed"
                    broadcast.completed_at = datetime.now(UTC)
                    broadcast.error = type(exc).__name__
        logger.exception("broadcast_failed broadcast_id=%s status=failed", broadcast_id)
        if admin_telegram_id:
            await send_bot_notification(admin_telegram_id, "❌ Рассылка остановлена из-за внутренней ошибки.")
        return

    async with SessionLocal() as session:
        async with session.begin():
            broadcast = await session.scalar(
                select(AdminBroadcast).where(AdminBroadcast.id == broadcast_id).with_for_update()
            )
            if not broadcast or broadcast.status != "running":
                return
            active_count = int(await session.scalar(select(func.count()).select_from(AdminBroadcastRecipient).where(
                AdminBroadcastRecipient.broadcast_id == broadcast_id,
                AdminBroadcastRecipient.status.in_({"pending", "sending"}),
            )) or 0)
            if active_count:
                return
            sent_count = int(await session.scalar(select(func.count()).select_from(AdminBroadcastRecipient).where(
                AdminBroadcastRecipient.broadcast_id == broadcast_id,
                AdminBroadcastRecipient.status == "sent",
            )) or 0)
            failed_count = int(await session.scalar(select(func.count()).select_from(AdminBroadcastRecipient).where(
                AdminBroadcastRecipient.broadcast_id == broadcast_id,
                AdminBroadcastRecipient.status == "failed",
            )) or 0)
            broadcast.status = "completed"
            broadcast.sent_count = sent_count
            broadcast.failed_count = failed_count
            broadcast.completed_at = datetime.now(UTC)
            total_recipients = broadcast.total_recipients
            completed_at = broadcast.completed_at

    logger.info(
        "broadcast_completed broadcast_id=%s completed_at=%s total_recipients=%s sent=%s failed=%s status=completed",
        broadcast_id, completed_at, total_recipients, sent_count, failed_count,
    )
    if admin_telegram_id:
        await send_bot_notification(
            admin_telegram_id,
            "✅ Рассылка завершена.\n\n"
            f"Отправлено: {sent_count}\n"
            f"Ошибок: {failed_count}\n"
            f"Всего: {total_recipients}",
        )


async def recover_admin_broadcasts() -> None:
    """Resume only unfinished jobs; completed broadcasts are never selected."""
    async with SessionLocal() as session:
        async with session.begin():
            active = list((await session.scalars(
                select(AdminBroadcast).where(AdminBroadcast.status.in_({"queued", "running"})).with_for_update(skip_locked=True)
            )).all())
            active_ids = [item.id for item in active]
            if active_ids:
                await session.execute(
                    update(AdminBroadcastRecipient)
                    .where(
                        AdminBroadcastRecipient.broadcast_id.in_(active_ids),
                        AdminBroadcastRecipient.status == "sending",
                    )
                    .values(
                        status="failed",
                        error_type="worker_interrupted",
                        error_message="Предыдущая отправка была прервана; повтор отключён для защиты от дубля",
                        completed_at=datetime.now(UTC),
                    )
                )
    for broadcast_id in active_ids:
        await run_admin_broadcast(broadcast_id)
