import asyncio
import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .bot import call_bot_api
from .config import get_settings
from .database import get_session
from .frontend import WEBAPP_DIR
from .models import ReferralReward, ReferralShare, User
from .referrals import (
    COMMISSION_PERCENT,
    MILESTONES,
    REFERRAL_LIMIT,
    ensure_code,
    invitation_text,
    referral_count,
)

router = APIRouter(prefix="/api/referrals", tags=["referrals"])
_identity_cache = None
_identity_expires = 0
_identity_task = None
_IDENTITY_TTL_SECONDS = 300
_IDENTITY_TIMEOUT_SECONDS = 8
# Content-addressed, unmodified owner-supplied JPEG, packaged by the existing Docker COPY.
# When replacing it, use a new hash filename so Telegram cannot reuse the old photo.
REFERRAL_PHOTO_PATH = "/images/referral-share.ffadf191b10c.jpg"


def referral_photo_url():
    base = get_settings().externally_reachable_url or ""
    parts = urlsplit(base)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.hostname in {"localhost", "127.0.0.1", "::1"}
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or not (WEBAPP_DIR / REFERRAL_PHOTO_PATH.lstrip("/")).is_file()
    ):
        raise HTTPException(503, "Фото приглашения временно недоступно. Попробуйте позже.")
    # The configured deployment URL, never a client-controlled Host/JSON value.
    return base.rstrip("/") + REFERRAL_PHOTO_PATH


async def _fetch_bot_identity():
    global _identity_cache, _identity_expires
    try:
        async with asyncio.timeout(_IDENTITY_TIMEOUT_SECONDS):
            result = (await call_bot_api("getMe", {}))["result"]
        username = str(result.get("username") or "")
        if (
            not username
            or not username.replace("_", "").isascii()
            or not username.replace("_", "").isalnum()
        ):
            raise ValueError("Invalid bot username")
    except (TimeoutError, HTTPException, KeyError, TypeError, ValueError):
        raise HTTPException(
            503, "Не удалось получить реферальную ссылку. Попробуйте позже."
        ) from None
    _identity_cache, _identity_expires = result, time.monotonic() + _IDENTITY_TTL_SECONDS
    return result


def _identity_finished(task):
    global _identity_task
    if _identity_task is task:
        _identity_task = None
    # A disconnected caller does not own the shared request. Retrieve an error
    # even when all waiters have left; the next request can retry normally.
    if not task.cancelled():
        task.exception()


async def _verified_bot_identity():
    global _identity_task
    if _identity_cache is not None and time.monotonic() < _identity_expires:
        return _identity_cache
    loop = asyncio.get_running_loop()
    if _identity_task is None or _identity_task.done() or _identity_task.get_loop() is not loop:
        _identity_task = loop.create_task(_fetch_bot_identity(), name="referral_bot_identity")
        _identity_task.add_done_callback(_identity_finished)
    # One cancelled HTTP request must not cancel verification for other users.
    # The shared operation itself has an eight-second deadline, below the
    # existing Mini App GET timeout. Expired identities are never served.
    return await asyncio.shield(_identity_task)


async def warm_referral_identity():
    if get_settings().bot_token:
        await _verified_bot_identity()


async def shutdown_referral_identity():
    global _identity_task
    task = _identity_task
    if task is not None and task.get_loop() is asyncio.get_running_loop():
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if _identity_task is task:
            _identity_task = None


async def referral_url(code):
    identity = await _verified_bot_identity()
    base = f"https://t.me/{quote(identity['username'], safe='')}"
    short_name = get_settings().telegram_mini_app_short_name
    if short_name:
        base += f"/{quote(short_name, safe='')}"
    key = (
        "startapp" if short_name or identity.get("has_main_web_app") else "start"
    )
    return f"{base}?{urlencode({key: code})}"


@router.get("")
@router.get("/me")
async def referral_summary(
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    async with session.begin():
        locked_user = await session.scalar(
            select(User).where(User.id == user.id).with_for_update(key_share=True)
        )
        code = await ensure_code(session, locked_user)
        count = await referral_count(session, user.id)
        completed = set(
            (
                await session.scalars(
                    select(ReferralReward.milestone).where(
                        ReferralReward.user_id == user.id,
                        ReferralReward.milestone.is_not(None),
                    )
                )
            ).all()
        )
    return {
        "referralCode": code,
        "referralUrl": await referral_url(code),
        "referralCount": count,
        "referralLimit": REFERRAL_LIMIT,
        "commissionPercent": COMMISSION_PERCENT,
        "canInvite": count < REFERRAL_LIMIT,
        "milestones": [
            {"count": threshold, "reward": amount, "completed": threshold in completed}
            for threshold, amount in MILESTONES
        ],
        "shareText": invitation_text(user.first_name),
    }


def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


@router.post("/share-message")
async def prepare_referral_share(
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    # Refresh the actual bot/app target before consulting the durable message
    # cache, so a changed username/launch mode never reuses an old inline button.
    async with session.begin():
        if await referral_count(session, user.id) >= REFERRAL_LIMIT:
            raise HTTPException(409, "Лимит приглашений достигнут")
    url_prefix = await referral_url("")
    photo_url = referral_photo_url()
    now = datetime.now(UTC)
    # Short DB claim; no wallet locks or HTTP requests inside the transaction.
    async with session.begin():
        user = await session.scalar(
            select(User).where(User.id == user.id).with_for_update(key_share=True)
        )
        if await referral_count(session, user.id) >= REFERRAL_LIMIT:
            raise HTTPException(409, "Лимит приглашений достигнут")
        code = await ensure_code(session, user)
        url = url_prefix + code
        message_text = invitation_text(user.first_name)
        content_hash = hashlib.sha256(
            f"photo-v1\n{url}\n{message_text}\n{photo_url}".encode()
        ).hexdigest()
        cached = await session.get(ReferralShare, user.id)
        if (
            cached
            and cached.prepared_message_id
            and cached.content_hash == content_hash
            and utc(cached.expires_at) > now + timedelta(seconds=30)
        ):
            return {"preparedMessageId": cached.prepared_message_id}
        if cached and utc(cached.requested_at) > now - timedelta(seconds=25):
            raise HTTPException(
                429, "Пересылка уже готовится. Повторите через несколько секунд."
            )
        if cached is None:
            cached = ReferralShare(user_id=user.id, requested_at=now)
            session.add(cached)
        cached.requested_at = now
    try:
        result = (
            await call_bot_api(
                "savePreparedInlineMessage",
                {
                    "user_id": user.telegram_id,
                    "allow_user_chats": True,
                    "allow_bot_chats": True,
                    "allow_group_chats": True,
                    "allow_channel_chats": True,
                    "result": {
                        "type": "photo",
                        "id": str(uuid.uuid4()),
                        "title": "AutoFlow Market",
                        "photo_url": photo_url,
                        "thumbnail_url": photo_url,
                        "caption": message_text,
                        # No input_message_content: it would replace the photo with text.
                        "reply_markup": {
                            "inline_keyboard": [
                                [{"text": "Перейти в маркет", "url": url}]
                            ]
                        },
                    },
                },
            )
        )["result"]
        message_id = result["id"]
        expires_at = datetime.fromtimestamp(result["expiration_date"], UTC)
        if not isinstance(message_id, str) or not message_id or expires_at <= now:
            raise ValueError("Invalid prepared message")
    except (HTTPException, KeyError, ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(
            502, "Не удалось подготовить пересылку. Попробуйте ещё раз."
        ) from exc
    async with session.begin():
        cached = await session.scalar(
            select(ReferralShare)
            .where(ReferralShare.user_id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        # Re-read even when expire_on_commit=False retained the earlier ORM row.
        # Do not overwrite a newer claim if a slow Telegram request finishes late.
        if utc(cached.requested_at) == now:
            cached.prepared_message_id = message_id
            cached.content_hash = content_hash
            cached.expires_at = expires_at
    return {"preparedMessageId": message_id}
