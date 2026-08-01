import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .database import get_session
from .models import User, Wallet


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 3600) -> dict:
    if not init_data or not bot_token:
        raise ValueError("Telegram initData or BOT_TOKEN is missing")
    parsed = dict(parse_qsl(init_data, strict_parsing=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise ValueError("Telegram initData hash is missing")
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("Telegram initData signature is invalid")
    auth_date = int(parsed.get("auth_date", "0"))
    if auth_date <= 0 or time.time() - auth_date > max_age_seconds:
        raise ValueError("Telegram initData has expired")
    return json.loads(parsed["user"])


async def get_current_user(
    x_telegram_init_data: str | None = Header(default=None),
    x_dev_telegram_id: int | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    try:
        if x_telegram_init_data:
            telegram_user = validate_init_data(x_telegram_init_data, settings.bot_token)
        elif settings.debug and (x_dev_telegram_id or settings.dev_telegram_id):
            dev_id = x_dev_telegram_id or settings.dev_telegram_id
            telegram_user = {"id": dev_id, "first_name": settings.dev_telegram_name, "username": "local_dev"}
        else:
            raise ValueError("Open the application from Telegram")
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    telegram_id = int(telegram_user["id"])
    role = "admin" if telegram_id in settings.admin_telegram_ids else "user"
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    now = datetime.now(UTC)
    if user is None:
        user = User(
            telegram_id=telegram_id,
            role=role,
            first_name=telegram_user.get("first_name") or "Telegram User",
            last_name=telegram_user.get("last_name"),
            username=telegram_user.get("username"),
            photo_url=telegram_user.get("photo_url"),
            mini_app_last_active_at=now,
        )
        session.add(user)
        await session.flush()
        session.add(Wallet(user_id=user.id))
    else:
        user.role = role
        user.first_name = telegram_user.get("first_name") or user.first_name
        user.last_name = telegram_user.get("last_name")
        user.username = telegram_user.get("username")
        user.photo_url = telegram_user.get("photo_url")
        user.mini_app_last_active_at = now
    await session.commit()
    if user.is_blocked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    return user
