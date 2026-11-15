"""Ticket ACL for screenshots, including preserved local legacy files."""

import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import or_, select
from starlette.concurrency import run_in_threadpool

from .auth import get_current_user
from .config import get_settings
from .database import AsyncSession, get_session
from .models import SupportTicket, UploadedImage, User

router = APIRouter(prefix="/api/support", tags=["support-media"])


def staff(user):
    return (
        user.role == "admin" or user.telegram_id in get_settings().support_telegram_ids
    )


async def validate_attachment(session, url, author_id):
    if not url:
        return
    path = urlparse(url).path
    if path.startswith("/api/support/images/"):
        try:
            image_id = uuid.UUID(path.rsplit("/", 1)[1])
        except ValueError:
            raise HTTPException(422, "Некорректное вложение") from None
        image = await session.get(UploadedImage, image_id)
        if not image or not image.support_private or image.owner_id != author_id:
            raise HTTPException(422, "Загрузите собственный снимок для обращения")


async def photo_response(content, preview):
    from .routes import normalize_image_content, image_preview

    # Legacy uploads can have non-JPEG source bytes; always normalize privately.
    normalized, _, _ = await run_in_threadpool(normalize_image_content, content)
    if preview:
        normalized = await run_in_threadpool(image_preview, normalized)
    return Response(
        normalized,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "Vary": "X-Telegram-Init-Data"},
    )


@router.get("/images/{image_id}")
async def owned_image(
    image_id: uuid.UUID,
    preview: bool = True,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    query = select(UploadedImage.data).where(
        UploadedImage.id == image_id, UploadedImage.support_private.is_(True)
    )
    if not staff(user):
        query = query.where(UploadedImage.owner_id == user.id)
    content = await session.scalar(query)
    if content is None:
        raise HTTPException(404, "Снимок не найден")
    if staff(user):
        linked = await session.scalar(
            select(SupportTicket.id)
            .where(SupportTicket.screenshot_url == f"/api/support/images/{image_id}")
            .limit(1)
        )
        if not linked:
            raise HTTPException(404, "Снимок ещё не привязан к обращению")
    return await photo_response(content, preview)


@router.get("/tickets/{ticket_id}/photo")
async def ticket_photo(
    ticket_id: uuid.UUID,
    preview: bool = True,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    query = select(SupportTicket).where(SupportTicket.id == ticket_id)
    if not staff(user):
        query = query.where(
            or_(
                SupportTicket.user_id == user.id,
                SupportTicket.author_id == user.id,
                SupportTicket.buyer_id == user.id,
                SupportTicket.seller_id == user.id,
            )
        )
    ticket = await session.scalar(query)
    if not ticket or not ticket.screenshot_url:
        raise HTTPException(404, "Снимок не найден")
    source = urlparse(ticket.screenshot_url)
    if source.scheme or source.netloc:
        raise HTTPException(
            404, "Старый внешний файл недоступен через защищённое хранилище"
        )
    if source.path.startswith(("/api/media/", "/api/support/images/")):
        try:
            image_id = uuid.UUID(source.path.rsplit("/", 1)[1])
        except ValueError:
            raise HTTPException(404, "Снимок не найден") from None
        image = await session.get(UploadedImage, image_id)
        if not image or (image.support_private and image.owner_id != ticket.author_id):
            raise HTTPException(404, "Снимок не найден")
        content = image.data
    elif source.path.startswith("/uploads/"):
        from .routes import UPLOAD_DIR

        base = Path(UPLOAD_DIR).resolve()
        path = (base / source.path.removeprefix("/uploads/")).resolve()
        if (
            not path.is_relative_to(base)
            or not path.is_file()
            or path.stat().st_size > get_settings().upload_max_bytes
        ):
            raise HTTPException(404, "Старый файл не сохранился")
        content = await run_in_threadpool(path.read_bytes)
    else:
        raise HTTPException(404, "Снимок не найден")
    return await photo_response(content, preview)
