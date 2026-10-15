"""Bound multipart traffic before parsing/spooling, not only after upload."""
import asyncio
import json
import logging
from time import monotonic

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse

from .config import get_settings


class ImageUploadGuard:
    def __init__(self, app):
        self.app = app
        self.slots = asyncio.Semaphore(2)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").rstrip("/") != "/api/uploads" or scope.get("method") != "POST":
            return await self.app(scope, receive, send)
        limit = get_settings().upload_max_bytes + 128 * 1024  # multipart envelope
        headers = dict(scope.get("headers", []))
        status = None
        detail = None

        async def reject(code, reason):
            logging.getLogger("autoflow.api").warning("image_upload_guard %s", json.dumps({
                "stage": "multipart_receive", "status": code,
                "error_id": headers.get(b"x-autoflow-error-id", b"")[:16].decode("ascii", "replace"),
            }))
            await JSONResponse({"detail": reason}, status_code=code)(scope, receive, send)

        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await reject(400, "Некорректный размер загрузки")
        if length > limit:
            return await reject(413, "Размер загрузки превышает лимит сервера")
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=5)
        except TimeoutError:
            return await reject(429, "Сервис обработки фотографий занят. Повторите через несколько секунд.")
        received = 0
        deadline = monotonic() + 120

        async def bounded_receive():
            nonlocal received, status, detail
            try:
                message = await asyncio.wait_for(receive(), timeout=max(.001, deadline - monotonic()))
            except TimeoutError:
                status, detail = 408, "Загрузка фотографии заняла слишком много времени. Повторите попытку."
                # Starlette closes every spool when the parser raises this type.
                raise MultiPartException(detail)
            if message.get("type") == "http.disconnect":
                # ClientDisconnect is not caught by this Starlette multipart
                # parser. Translate it so a dropped mobile connection closes
                # partially written spools immediately, not only during GC.
                status, detail = 400, "Соединение прервано во время загрузки фотографии"
                raise MultiPartException(detail)
            received += len(message.get("body", b""))
            if received > limit:
                status, detail = 413, "Размер загрузки превышает лимит сервера"
                raise MultiPartException(detail)
            return message

        async def guarded_send(message):
            # Request.form converts MultiPartException to 400. Replace it with
            # the accurate 413/408 only after the parser has cleaned its files.
            if status is None:
                await send(message)

        try:
            await self.app(scope, bounded_receive, guarded_send)
            if status:
                await reject(status, detail)
        finally:
            self.slots.release()
