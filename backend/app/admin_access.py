"""Server-owned staff permissions; no client-supplied role or financial bypass."""
from fastapi import Depends, HTTPException

from .auth import get_current_user
from .config import get_settings
from .models import User


def staff_access(user):
    settings = get_settings()
    if getattr(user, "is_blocked", False):
        return {"role": "user", "tabs": []}
    if user.role == "admin":
        role = "owner" if getattr(user, "telegram_id", None) == settings.admin_id and settings.admin_id else "admin"
        return {"role": role, "tabs": ["overview", "analytics", "users", "training", "listings", "deals",
                                       "withdrawals", "support", "audit", "advertisement", "broadcasts"]}
    if getattr(user, "telegram_id", None) in settings.support_telegram_ids:
        return {"role": "support", "tabs": ["support"]}
    return {"role": "user", "tabs": []}


def can_support(user):
    return staff_access(user)["role"] in {"owner", "admin", "support"}


async def require_support(user: User = Depends(get_current_user)) -> User:
    if not can_support(user):
        raise HTTPException(403, "Требуется сотрудник поддержки")
    return user
