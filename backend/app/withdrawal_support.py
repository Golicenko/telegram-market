"""Public withdrawal presentation and support; no payout arithmetic here."""
import re
from fastapi import HTTPException
from sqlalchemy import select
from .models import WithdrawalRequest, SupportTicket, AdminAction


def validated_username(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", value) else None


def profile_url(user):
    username = validated_username(user.username)
    return f"https://t.me/{username}" if username else f"tg://user?id={int(user.telegram_id)}"


async def withdrawal_support_ticket(session, actor, withdrawal_id):
    async with session.begin():
        request = await session.scalar(select(WithdrawalRequest).where(
            WithdrawalRequest.id == withdrawal_id).with_for_update())
        if not request or (actor.role != "admin" and request.user_id != actor.id):
            raise HTTPException(404, "Заявка не найдена")
        ticket = await session.scalar(select(SupportTicket).where(SupportTicket.withdrawal_id == request.id))
        if not ticket:
            ticket = SupportTicket(user_id=request.user_id, author_id=request.user_id,
                withdrawal_id=request.id, case_type="general", topic=f"Вывод {request.public_id}",
                status="open", unread_by_admin=actor.role != "admin")
            session.add(ticket)
            await session.flush()
        elif ticket.status in {"closed", "resolved"}:
            ticket.status = "open"
            ticket.resolved_at = None
        if actor.role == "admin":
            session.add(AdminAction(admin_id=actor.id, action="open_withdrawal_support",
                target_type="withdrawal", target_id=request.id, reason="Связь по заявке",
                metadata_json={"ticket_id": str(ticket.id), "public_number": request.public_number}))
    return ticket
