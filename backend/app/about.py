"""Public project facts with real aggregate counts, never screenshot seed values."""
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select

from .auth import get_current_user
from .config import get_settings
from .database import AsyncSession, get_session
from .models import Deal, User

router = APIRouter(prefix="/api", tags=["about"])


def founder_photo():
    value = get_settings().about_founder_photo_url.strip()
    parsed = urlsplit(value)
    # Only an explicitly configured public asset, never the visitor's avatar.
    return value if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password else None


@router.get("/about")
async def project_about(
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "private, no-store"
    users = int(await session.scalar(select(func.count(User.id)).where(User.telegram_id > 0)) or 0)
    completed = int(await session.scalar(select(func.count(Deal.id)).where(
        Deal.status == "completed", Deal.completed_at.is_not(None), Deal.cancelled_at.is_(None),
    )) or 0)
    return {"users": users, "completed_deals": completed, "founded_year": 2026,
            "games": [{"code": "car_parking_1", "title": "Car Parking 1"},
                      {"code": "car_parking_2", "title": "Car Parking 2"}],
            "founder": {"name": "Maxim", "photo_url": founder_photo()},
            "statistics_source": "database", "updated_at": datetime.now(UTC)}
