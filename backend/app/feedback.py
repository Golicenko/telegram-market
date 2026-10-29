"""Voluntary feedback. No channel publishing, financial commands or general-message capture."""
import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import exists, func, literal, or_, select, text as sql_text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import bot
from .auth import require_admin
from .database import SessionLocal, get_session
from .models import AdminAction, Deal, FeedbackCampaign, FeedbackDelivery, FeedbackRequest, SupportTicket, User, UserFeedback

router = APIRouter(prefix="/api/admin/feedback", tags=["feedback"])
logger = logging.getLogger("autoflow.feedback")
REPEAT_DAYS = 30
REQUEST_DAYS = 7
ACTIVE_REQUESTS = {"pending", "sending", "sent", "waiting"}
INVITATION = ("⭐ Нам важно ваше мнение!\n\nВы уже пользовались AutoFlow Market?\n"
    "Расскажите, что вам понравилось и что мы могли бы улучшить.\n\n"
    "Ваш отзыв поможет нам сделать маркет лучше. Участие добровольное.\n"
    "Нажмите «Оставить отзыв» и напишите несколько слов об опыте в ответ на вопрос бота.")
PROMPT = ("Напишите ваш отзыв одним сообщением в ответ на это сообщение. "
    "Что вам понравилось в AutoFlow Market, а что хотелось бы улучшить?\n\n"
    "Можно отказаться: /cancel_feedback. Команды, сделки и поддержка продолжают работать отдельно.")


def buttons(request_id, consent=False):
    prefix = "feedback"
    options = [("✅ Да, разрешаю", "yes"), ("🔒 Нет, только администрации", "no")] if consent else [("✍️ Оставить отзыв", "write"), ("Не сейчас", "skip")]
    return {"inline_keyboard": [[{"text": text, "callback_data": f"{prefix}:{action}:{request_id}"}] for text, action in options]}


def private_message(message):
    sender, chat = message.get("from") or {}, message.get("chat") or {}
    return bool(chat.get("type") == "private" and type(sender.get("id")) is int and chat.get("id") == sender["id"] and not sender.get("is_bot"))


async def enqueue(session, request, kind, target, feedback=None):
    await session.execute(insert(FeedbackDelivery).values(request_id=request.id, feedback_id=feedback.id if feedback else None,
        target_telegram_id=target, kind=kind, dedup_key=f"{request.id}:{kind}:{target}", status="pending").on_conflict_do_nothing())


def busy_user(user_id):
    return or_(exists(select(Deal.id).where(or_(Deal.buyer_id == user_id, Deal.seller_id == user_id), Deal.status.not_in(["completed", "cancelled"]))),
        exists(select(SupportTicket.id).where(SupportTicket.user_id == user_id, SupportTicket.status.not_in(["closed", "resolved"]))))


class CampaignCreate(BaseModel):
    client_request_id: uuid.UUID
    confirmed: Literal[True]


async def create_campaign(session, admin, request_id):
    now = datetime.now(UTC)
    async with session.begin():
        old = await session.scalar(select(FeedbackCampaign).where(FeedbackCampaign.client_request_id == request_id))
        if old:
            if old.admin_id != admin.id:
                raise HTTPException(403, "Запрос принадлежит другому администратору")
            return old.id
        await session.execute(update(FeedbackRequest).where(FeedbackRequest.status.in_(ACTIVE_REQUESTS), FeedbackRequest.expires_at <= now).values(status="expired"))
        campaign_id = await session.scalar(insert(FeedbackCampaign).values(admin_id=admin.id, client_request_id=request_id, status="queued")
            .on_conflict_do_nothing().returning(FeedbackCampaign.id))
        if not campaign_id:
            old = await session.scalar(select(FeedbackCampaign).where(FeedbackCampaign.client_request_id == request_id))
            if old and old.admin_id == admin.id:
                return old.id
            raise HTTPException(409, "Сбор отзывов уже выполняется. Дождитесь завершения или остановите его.")
        eligible = select(func.gen_random_uuid(), literal(campaign_id), User.id, User.telegram_id,
            literal("pending"), literal(now + timedelta(days=REQUEST_DAYS))).where(
            User.bot_started.is_(True), User.is_blocked.is_(False), User.role == "user", ~busy_user(User.id),
            ~exists(select(FeedbackRequest.id).where(FeedbackRequest.user_id == User.id,
                or_(FeedbackRequest.created_at > now - timedelta(days=REPEAT_DAYS), FeedbackRequest.status.in_(ACTIVE_REQUESTS)))))
        await session.execute(insert(FeedbackRequest).from_select(["id", "campaign_id", "user_id", "telegram_id", "status", "expires_at"], eligible))
        session.add(AdminAction(admin_id=admin.id, action="feedback_campaign_started", target_type="feedback_campaign", target_id=campaign_id,
            reason="Подтверждён добровольный запрос отзывов", metadata_json={"repeat_days": REPEAT_DAYS}))
        return campaign_id


@router.post("/campaigns", status_code=201)
async def start_campaign(payload: CampaignCreate, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return {"id": await create_campaign(session, admin, payload.client_request_id)}


@router.post("/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    async with session.begin():
        campaign = await session.scalar(select(FeedbackCampaign).where(FeedbackCampaign.id == campaign_id).with_for_update())
        if not campaign:
            raise HTTPException(404, "Запрос не найден")
        if campaign.status in {"queued", "running"}:
            campaign.status = "stopped"
            campaign.completed_at = datetime.now(UTC)
            await session.execute(update(FeedbackRequest).where(FeedbackRequest.campaign_id == campaign_id, FeedbackRequest.status == "pending").values(status="cancelled"))
            session.add(AdminAction(admin_id=admin.id, action="feedback_campaign_stopped", target_type="feedback_campaign", target_id=campaign.id, reason="Остановлено администратором"))
    return {"status": campaign.status}


@router.get("")
async def overview(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    counts = (await session.execute(select(func.count(), func.count().filter(UserFeedback.seen_at.is_(None)), func.count().filter(UserFeedback.consent == "allowed")).select_from(UserFeedback))).one()
    sent = int(await session.scalar(select(func.count()).select_from(FeedbackRequest).where(FeedbackRequest.sent_at.is_not(None))) or 0)
    campaigns = list((await session.scalars(select(FeedbackCampaign).order_by(FeedbackCampaign.created_at.desc()).limit(10))).all())
    stats = {row[0]: row[1:] for row in (await session.execute(select(FeedbackRequest.campaign_id, func.count(),
        func.count().filter(FeedbackRequest.sent_at.is_not(None)), func.count().filter(FeedbackRequest.status == "failed"),
        func.count().filter(FeedbackRequest.status == "received"), func.count().filter(FeedbackRequest.status == "declined"))
        .where(FeedbackRequest.campaign_id.in_([item.id for item in campaigns])).group_by(FeedbackRequest.campaign_id))).all()}
    return {"sent": sent, "received": counts[0], "new": counts[1], "allowed": counts[2], "repeat_days": REPEAT_DAYS,
        "campaigns": [{"id": item.id, "status": item.status, "created_at": item.created_at,
            **dict(zip(["total", "sent", "failed", "received", "declined"], stats.get(item.id, (0, 0, 0, 0, 0))))} for item in campaigns]}


@router.get("/reviews")
async def reviews(filter: Literal["all", "new", "allowed"] = "new", offset: int = Query(0, ge=0), admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    query = select(UserFeedback, User.first_name, User.username).join(User, User.id == UserFeedback.user_id)
    if filter == "new":
        query = query.where(UserFeedback.seen_at.is_(None))
    elif filter == "allowed":
        query = query.where(UserFeedback.consent == "allowed")
    rows = (await session.execute(query.order_by(UserFeedback.created_at.desc(), UserFeedback.id.desc()).offset(offset).limit(31))).all()
    deliveries = (await session.execute(select(FeedbackDelivery.feedback_id, FeedbackDelivery.status, FeedbackDelivery.message_id, FeedbackDelivery.error_type)
        .where(FeedbackDelivery.feedback_id.in_([row[0].id for row in rows[:30]]), FeedbackDelivery.kind == "forward", FeedbackDelivery.target_telegram_id == admin.telegram_id))).all()
    forwarded = {row[0]: {"status": row[1], "message_id": row[2], "error_type": row[3]} for row in deliveries}
    return {"has_more": len(rows) > 30, "items": [{"id": item.id, "text": item.text, "name": name, "username": username,
        "consent": item.consent, "consent_at": item.consent_at, "seen_at": item.seen_at, "created_at": item.created_at,
        "forward": forwarded.get(item.id)} for item, name, username in rows[:30]]}


@router.post("/reviews/{feedback_id}/seen")
async def mark_seen(feedback_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    async with session.begin():
        item = await session.scalar(select(UserFeedback).where(UserFeedback.id == feedback_id).with_for_update())
        if not item:
            raise HTTPException(404, "Отзыв не найден")
        if item.seen_at is None:
            item.seen_at, item.seen_by = datetime.now(UTC), admin.id
            session.add(AdminAction(admin_id=admin.id, action="feedback_seen", target_type="feedback", target_id=item.id, reason="Отзыв просмотрен"))
    return {"seen_at": item.seen_at}


async def handle_callback(session, callback):
    message = callback.get("message") or {}
    sender = callback.get("from") or {}
    if message.get("chat", {}).get("type") != "private" or message.get("chat", {}).get("id") != sender.get("id"):
        return "Откройте личный чат с ботом"
    try:
        _, action, value = callback["data"].split(":", 2)
        request_id = uuid.UUID(value)
    except (KeyError, ValueError):
        return "Некорректная кнопка"
    async with session.begin():
        request = await session.scalar(select(FeedbackRequest).where(FeedbackRequest.id == request_id, FeedbackRequest.telegram_id == sender.get("id")).with_for_update())
        if not request:
            return "Этот запрос вам недоступен"
        user = await session.get(User, request.user_id)
        if user.is_blocked:
            return "Запрос недоступен"
        now = datetime.now(UTC)
        if action in {"yes", "no"}:
            item = await session.scalar(select(UserFeedback).where(UserFeedback.request_id == request.id).with_for_update())
            if not item:
                return "Отзыв ещё не получен"
            choice = "allowed" if action == "yes" else "private"
            if item.consent != choice:
                item.consent, item.consent_at = choice, now
                item.consent_version += 1
                admins = (await session.scalars(select(User).where(User.role == "admin", User.is_blocked.is_(False), User.bot_started.is_(True)))).all()
                for admin in admins:
                    await enqueue(session, request, f"permission_{item.consent_version}", admin.telegram_id, item)
            return "Разрешение сохранено" if choice == "allowed" else "Отзыв только для администрации"
        if action == "skip" and request.status in {"sent", "waiting"}:
            request.status = "declined"
            await session.execute(update(FeedbackDelivery).where(FeedbackDelivery.request_id == request.id, FeedbackDelivery.kind == "prompt", FeedbackDelivery.status == "pending").values(status="cancelled"))
            return "Хорошо, участие необязательно"
        expiry = request.expires_at.replace(tzinfo=UTC) if request.expires_at.tzinfo is None else request.expires_at
        if action != "write" or request.status not in {"sent", "waiting"} or expiry <= now:
            return "Этот запрос уже закрыт"
        if await session.scalar(select(busy_user(user.id))):
            return "Сначала завершите текущую сделку или обращение в поддержку"
        request.status = "waiting"
        await enqueue(session, request, "prompt", request.telegram_id)
        return "Ответьте на сообщение с вопросом. Можно отменить: /cancel_feedback"


async def handle_message(session, update):
    message = update.get("message") or {}
    if not private_message(message):
        return False
    text = message.get("text")
    cancel = text == "/cancel_feedback"
    if not isinstance(text, str) or not text.strip() or len(text) > 4096 or (text.lstrip().startswith(("/", "#")) and not cancel):
        return False
    reply_id = (message.get("reply_to_message") or {}).get("message_id")
    if not cancel and (not reply_id or not update.get("update_id") or not message.get("message_id")):
        return False
    async with session.begin():
        query = select(FeedbackRequest).where(FeedbackRequest.telegram_id == message["from"]["id"], FeedbackRequest.status == "waiting")
        if not cancel:
            query = query.where(FeedbackRequest.prompt_message_id == reply_id)
        request = await session.scalar(query.with_for_update())
        if not request:
            return False
        if cancel:
            request.status = "declined"
            return True
        user = await session.get(User, request.user_id)
        if user.is_blocked or await session.scalar(select(busy_user(user.id))):
            return False
        if request.expires_at <= datetime.now(UTC):
            request.status = "expired"
            return False
        item = UserFeedback(request_id=request.id, user_id=request.user_id, telegram_chat_id=request.telegram_id,
            telegram_message_id=message["message_id"], telegram_update_id=update["update_id"], text=text,
            protected=bool(message.get("has_protected_content")), consent="pending")
        session.add(item)
        await session.flush()
        request.status = "received"
        await enqueue(session, request, "consent", request.telegram_id, item)
        admins = (await session.scalars(select(User).where(User.role == "admin", User.is_blocked.is_(False), User.bot_started.is_(True)))).all()
        for admin in admins:
            await enqueue(session, request, "forward", admin.telegram_id, item)
            await enqueue(session, request, "admin", admin.telegram_id, item)
    return True


def delivery_payload(delivery, request, feedback):
    target = {"chat_id": delivery.target_telegram_id}
    if delivery.kind == "prompt":
        return "sendMessage", {**target, "text": PROMPT, "reply_markup": {"force_reply": True, "selective": True, "input_field_placeholder": "Ваш честный отзыв"}}
    if delivery.kind == "forward":
        if feedback.protected:
            raise ValueError("protected_content")
        return "forwardMessage", {**target, "from_chat_id": feedback.telegram_chat_id, "message_id": feedback.telegram_message_id}
    if delivery.kind == "consent":
        return "sendMessage", {**target, "text": "Спасибо за отзыв! ❤️ Разрешаете опубликовать его в нашем Telegram-канале?", "reply_markup": buttons(request.id, True)}
    permission = {"pending": "Согласие ещё не получено — не публиковать", "allowed": "Разрешено публиковать вручную", "private": "Только администрации — не публиковать"}[feedback.consent]
    return "sendMessage", {**target, "text": f"⭐ Отзыв {feedback.id}\nДата: {feedback.created_at:%Y-%m-%d %H:%M} UTC\n{permission}\nСтатус: {'просмотрен' if feedback.seen_at else 'новый'}.\nПроверьте актуальное согласие в админке перед публикацией. Пересылка зависит от приватности Telegram."}


async def deliver_one(sessions=SessionLocal):
    # A session-level advisory lease survives the claim commit and serializes
    # feedback sends across Railway replicas, independently of news broadcasts.
    # Keep one physical connection, but no idle transaction during Bot API I/O.
    # Binding the short claim/ack sessions to it also works with pool_size=1.
    async with sessions.kw["bind"].connect() as lease:
        acquired = await lease.scalar(sql_text("SELECT pg_try_advisory_lock(74901231)"))
        await lease.commit()
        if not acquired:
            return False
        try:
            sent = await _deliver_one(async_sessionmaker(bind=lease, expire_on_commit=False))
            if sent:
                await asyncio.sleep(1.1)
            return sent
        finally:
            await lease.execute(sql_text("SELECT pg_advisory_unlock(74901231)"))
            await lease.commit()


async def _deliver_one(sessions):
    """Claim BEFORE network I/O. Unknown send results are never auto-retried."""
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        # Replies/consent/forwards have priority over the remaining bulk invites.
        delivery = await session.scalar(select(FeedbackDelivery).where(FeedbackDelivery.status == "pending").order_by(FeedbackDelivery.created_at, FeedbackDelivery.id).with_for_update(skip_locked=True).limit(1))
        request_id = None
        campaign = None if delivery else await session.scalar(select(FeedbackCampaign).where(FeedbackCampaign.status.in_(["queued", "running"])).with_for_update(skip_locked=True).limit(1))
        if campaign:
            campaign.status = "running"
            request = await session.scalar(select(FeedbackRequest).where(FeedbackRequest.campaign_id == campaign.id, FeedbackRequest.status == "pending").order_by(FeedbackRequest.created_at, FeedbackRequest.id).with_for_update(skip_locked=True).limit(1))
            if request:
                user = await session.get(User, request.user_id)
                if user.is_blocked or not user.bot_started or await session.scalar(select(busy_user(user.id))):
                    request.status = "cancelled"
                    return True
                request.status, request.started_at = "sending", now
                request_id = request.id
            else:
                pending = await session.scalar(select(func.count()).select_from(FeedbackRequest).where(FeedbackRequest.campaign_id == campaign.id, FeedbackRequest.status == "sending"))
                if not pending:
                    campaign.status, campaign.completed_at = "completed", now
                request_id = None
        else:
            request_id = None
        if not request_id:
            if not delivery:
                return False
            delivery.status, delivery.started_at = "sending", now
            request = await session.get(FeedbackRequest, delivery.request_id)
            feedback = await session.get(UserFeedback, delivery.feedback_id) if delivery.feedback_id else None
            if delivery.kind == "prompt" and request.status != "waiting":
                delivery.status = "cancelled"
                return True
    error_type, message_id = None, None
    try:
        method, payload = ("sendMessage", {"chat_id": request.telegram_id, "text": INVITATION, "reply_markup": buttons(request.id)}) if request_id else delivery_payload(delivery, request, feedback)
        result = await bot.call_bot_api(method, payload)
        message_id = result["result"]["message_id"]
        if type(message_id) is not int or message_id <= 0:
            raise ValueError("invalid_message_id")
    except asyncio.CancelledError:
        raise
    except (HTTPException, ValueError, KeyError, TypeError) as error:
        detail = str(error.detail).casefold() if isinstance(error, HTTPException) else ""
        error_type = ("protected_content" if isinstance(error, ValueError) and str(error) == "protected_content"
            else "bot_blocked" if "blocked" in detail
            else "rate_limited" if "retry after" in detail or "too many requests" in detail
            else "forward_restricted" if "forward" in detail and ("can't" in detail or "cannot" in detail)
            else "telegram_delivery_failed")
        logger.warning("feedback_delivery_failed request_id=%s kind=%s error_type=%s", request.id, "invitation" if request_id else delivery.kind, error_type)
    async with sessions() as session, session.begin():
        if request_id:
            item = await session.scalar(select(FeedbackRequest).where(FeedbackRequest.id == request_id).with_for_update())
            if item.status == "sending":
                item.status, item.error_type = ("failed" if error_type else "sent"), error_type
                item.invitation_message_id = message_id
                if not error_type:
                    item.sent_at = datetime.now(UTC)
        else:
            item = await session.scalar(select(FeedbackDelivery).where(FeedbackDelivery.id == delivery.id).with_for_update())
            if item.status == "sending":
                item.status, item.error_type, item.message_id = ("failed" if error_type else "sent"), error_type, message_id
                if delivery.kind == "prompt" and not error_type:
                    request = await session.scalar(select(FeedbackRequest).where(FeedbackRequest.id == item.request_id).with_for_update())
                    request.prompt_message_id = message_id
    return True


async def maintenance(sessions=SessionLocal):
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        for model in (FeedbackRequest, FeedbackDelivery):
            await session.execute(update(model).where(model.status == "sending", model.started_at < now - timedelta(minutes=2)).values(status="failed", error_type="unknown_after_restart"))
        await session.execute(update(FeedbackRequest).where(FeedbackRequest.status.in_(ACTIVE_REQUESTS - {"sending"}), FeedbackRequest.expires_at <= now).values(status="expired"))


async def run_feedback_worker():
    while True:
        try:
            await maintenance()
            # One worker for invitations, prompts and forwards, below bulk limits.
            for _ in range(20):
                if not await deliver_one():
                    break
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("feedback_worker_failed error_type=%s", type(error).__name__)
        await asyncio.sleep(5)
