import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .bot import call_bot_api
from .config import get_settings
from .database import get_session
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


async def referral_url(code):
    global _identity_cache, _identity_expires
    if _identity_cache is None or time.monotonic() >= _identity_expires:
        try:
            result = (await call_bot_api("getMe", {}))["result"]
            username = str(result.get("username") or "")
            if (
                not username
                or not username.replace("_", "").isascii()
                or not username.replace("_", "").isalnum()
            ):
                raise ValueError("Invalid bot username")
        except (HTTPException, KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                503, "Не удалось получить реферальную ссылку. Попробуйте позже."
            ) from exc
        _identity_cache, _identity_expires = result, time.monotonic() + 300
    base = f"https://t.me/{quote(_identity_cache['username'], safe='')}"
    short_name = get_settings().telegram_mini_app_short_name
    if short_name:
        base += f"/{quote(short_name, safe='')}"
    key = (
        "startapp" if short_name or _identity_cache.get("has_main_web_app") else "start"
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
        content_hash = hashlib.sha256(f"{url}\n{message_text}".encode()).hexdigest()
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
                        "type": "article",
                        "id": str(uuid.uuid4()),
                        "title": "AutoFlow Market",
                        "input_message_content": {
                            "message_text": message_text,
                            "link_preview_options": {"is_disabled": True},
                        },
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
