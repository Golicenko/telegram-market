"""Private participant-scoped photos; never put them in public /media or /uploads."""
import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from .auth import get_current_user
from .chat_access import require_active_chat_by_id
from .config import get_settings
from .database import AsyncSession, get_session
from .models import Conversation, ConversationMessage, PrivateChatImage, User
from .schemas import ConversationMessageOut
from .services import send_conversation_message

router = APIRouter(prefix="/api/conversations", tags=["private-chat-media"])


@router.post("/{conversation_id}/photos", response_model=ConversationMessageOut, status_code=201)
async def send_photo(conversation_id: uuid.UUID, request: Request, file: UploadFile = File(...),
    client_message_id: uuid.UUID = Form(...), deal_id: uuid.UUID | None = Form(default=None),
    body: str = Form(default="", max_length=4000), user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)):
    from .routes import normalize_image_content, image_dimensions, image_preview, spooled_file_size
    try:
        await require_active_chat_by_id(session, conversation_id, user)
        previous = await session.scalar(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.sender_id == user.id, ConversationMessage.client_message_id == client_message_id))
        if previous:
            if previous.message_type != "photo" or previous.deal_id != deal_id:
                raise HTTPException(409, "Идентификатор уже связан с другим сообщением")
            return previous
        await session.commit()  # Close read preflight without expiring the authenticated actor.
        if not hasattr(request.app.state, "image_processing_slots"):
            request.app.state.image_processing_slots = asyncio.Semaphore(1)
        async with request.app.state.image_processing_slots:
            size = await run_in_threadpool(spooled_file_size, file)
            if size > min(get_settings().upload_max_bytes, 12*1024*1024):
                raise HTTPException(413, "Фото для чата должно быть не больше 12 МБ")
            await file.seek(0)
            diagnostics = {}
            content, _, _ = await run_in_threadpool(normalize_image_content, file.file, diagnostics)
            if diagnostics.get("detected_format") not in {"JPEG", "PNG", "WEBP", "HEIF", "HEIC"}:
                raise HTTPException(415, "Выберите JPEG, PNG, WebP или HEIC/HEIF")
            width, height = await run_in_threadpool(image_dimensions, content)
            preview = await run_in_threadpool(image_preview, content)
        message, _, _ = await send_conversation_message(session, user, conversation_id, body, client_message_id, deal_id,
            photo={"data": content, "preview": preview, "width": width, "height": height})
        return message
    except SQLAlchemyError as error:
        # Do not emit SQL parameter dumps containing private JPEG/caption data.
        logging.getLogger(__name__).warning("chat_photo_storage_failed error_type=%s", type(error).__name__)
        raise HTTPException(503, "Отправка фото не подтверждена. Проверьте чат или повторите отправку.") from None
    finally:
        await file.close()


@router.get("/{conversation_id}/photos/{image_id}")
async def get_photo(conversation_id: uuid.UUID, image_id: uuid.UUID, preview: bool = True,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    # Authorize in the SQL predicate BEFORE retrieving any private bytes.
    query = select(PrivateChatImage.preview if preview else PrivateChatImage.data).join(
        ConversationMessage, ConversationMessage.media_id == PrivateChatImage.id).join(
        Conversation, Conversation.id == PrivateChatImage.conversation_id).where(
            PrivateChatImage.id == image_id, PrivateChatImage.conversation_id == conversation_id,
            ConversationMessage.conversation_id == conversation_id)
    if user.role != "admin":
        query = query.where(or_(Conversation.buyer_id == user.id, Conversation.seller_id == user.id))
    content = await session.scalar(query)
    if content is None:
        raise HTTPException(404, "Фотография не найдена")
    return Response(content, media_type="image/jpeg", headers={"Cache-Control": "private, no-store",
        "Vary": "X-Telegram-Init-Data", "X-Content-Type-Options": "nosniff"})
