"""Validate durable uploaded photos without invalidating legacy media URLs."""
import uuid
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import select

from .models import UploadedImage


async def validate_listing_media(session, urls, owner_id):
    if urls is None:
        return
    for url in urls:
        try:
            parsed = urlsplit(url)
        except ValueError:
            raise HTTPException(422, "Некорректный адрес фотографии")
        if parsed.scheme not in {"", "https", "http"} or (not parsed.scheme and not url.startswith("/")) or url.startswith("//"):
            raise HTTPException(422, "Некорректный адрес фотографии")
        if parsed.path.startswith("/api/support/"):
            raise HTTPException(422, "Снимок поддержки нельзя использовать в публичном объявлении")
        if not parsed.path.startswith("/api/media/"):
            # Existing external/legacy uploads remain supported. New WebApp
            # uploads always return /api/media/{uuid}; no filesystem migration.
            continue
        try:
            image_id = uuid.UUID(parsed.path.removeprefix("/api/media/"))
        except ValueError:
            raise HTTPException(422, "Некорректный адрес сохранённой фотографии")
        owner = await session.scalar(select(UploadedImage.owner_id).where(UploadedImage.id == image_id, UploadedImage.support_private.is_(False)))
        if owner != owner_id:
            raise HTTPException(422, "Фотография не найдена или принадлежит другому пользователю. Загрузите её заново.")
