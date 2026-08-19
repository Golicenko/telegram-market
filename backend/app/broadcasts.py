import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .bot import send_bot_notification, send_bot_photo
from .database import SessionLocal
from .models import AdminBroadcast, User


BROADCAST_COMMANDS = ("#рассылка", "/рассылка")


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
    telegram_update_id: int,
    admin_telegram_id: int,
    content_type: str,
    text: str,
    photo_file_id: str | None = None,
) -> uuid.UUID | None:
    """Atomically claim one Telegram update; duplicates return None."""
    statement = (
        pg_insert(AdminBroadcast)
        .values(
            telegram_update_id=telegram_update_id,
            admin_telegram_id=admin_telegram_id,
            content_type=content_type,
            text=text,
            photo_file_id=photo_file_id,
            status="pending",
        )
        # Ignore both a retried update_id and a second command while another
        # broadcast by the same administrator is pending/running.
        .on_conflict_do_nothing()
        .returning(AdminBroadcast.id)
    )
    broadcast_id = await session.scalar(statement)
    await session.commit()
    return broadcast_id


async def run_admin_broadcast(broadcast_id: uuid.UUID) -> None:
    """Run a claimed broadcast once, outside the Telegram webhook response."""
    async with SessionLocal() as session:
        async with session.begin():
            broadcast = await session.scalar(
                select(AdminBroadcast).where(AdminBroadcast.id == broadcast_id).with_for_update()
            )
            if not broadcast or broadcast.status != "pending":
                return
            broadcast.status = "running"
            broadcast.started_at = datetime.now(UTC)
            content_type = broadcast.content_type
            text = broadcast.text
            photo_file_id = broadcast.photo_file_id
            admin_telegram_id = broadcast.admin_telegram_id

        recipients = list(
            (await session.scalars(
                select(User.telegram_id).where(User.bot_started.is_(True)).order_by(User.telegram_id)
            )).all()
        )

    sent_count = 0
    failed_count = 0
    try:
        # telegram_id is unique in users; dict also protects legacy/imported duplicates.
        for telegram_id in dict.fromkeys(recipients):
            if content_type == "photo" and photo_file_id:
                sent = await send_bot_photo(telegram_id, photo_file_id, text)
            else:
                sent = await send_bot_notification(telegram_id, text)
            if sent:
                sent_count += 1
            else:
                failed_count += 1
    except Exception as exc:
        async with SessionLocal() as session:
            async with session.begin():
                broadcast = await session.scalar(
                    select(AdminBroadcast).where(AdminBroadcast.id == broadcast_id).with_for_update()
                )
                if broadcast and broadcast.status == "running":
                    broadcast.status = "failed"
                    broadcast.sent_count = sent_count
                    broadcast.failed_count = failed_count
                    broadcast.completed_at = datetime.now(UTC)
                    broadcast.error = type(exc).__name__
        await send_bot_notification(admin_telegram_id, "❌ Рассылка остановлена из-за внутренней ошибки.")
        return

    async with SessionLocal() as session:
        async with session.begin():
            broadcast = await session.scalar(
                select(AdminBroadcast).where(AdminBroadcast.id == broadcast_id).with_for_update()
            )
            if not broadcast or broadcast.status != "running":
                return
            broadcast.status = "completed"
            broadcast.sent_count = sent_count
            broadcast.failed_count = failed_count
            broadcast.completed_at = datetime.now(UTC)

    await send_bot_notification(
        admin_telegram_id,
        "✅ Рассылка завершена.\n\n"
        f"Получили: {sent_count}\n"
        f"Не удалось отправить: {failed_count}",
    )
