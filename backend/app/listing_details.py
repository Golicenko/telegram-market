"""Read-only public car context; no wallet/deal mutations or private user fields."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import and_, func, select

from .auth import get_current_user
from .bot import bot_private_chat_link
from .database import AsyncSession, get_session
from .models import Deal, Favorite, Listing, User
from .schemas import ListingOut

router = APIRouter(prefix="/api/listings", tags=["listing-details"])


class SellerContext(BaseModel):
    name: str
    photo_url: str | None
    completed_sales: int
    saved_by_me: bool
    other_active_count: int
    items: list[ListingOut]
    has_more: bool


async def car(session, listing_id):
    listing = await session.get(Listing, listing_id)
    if (
        not listing
        or listing.product_kind != "car"
        or listing.deleted_at
        or listing.status == "deleted"
    ):
        raise HTTPException(404, "Объявление не найдено")
    return listing


@router.get("/{listing_id}/seller-context", response_model=SellerContext)
async def seller_context(
    listing_id: uuid.UUID,
    limit: int = Query(default=12, ge=1, le=24),
    offset: int = Query(default=0, ge=0, le=10000),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    response: Response = None,
):
    from .routes import listing_collection_out

    if response is not None:
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "X-Telegram-Init-Data"
    listing = await car(session, listing_id)
    seller = await session.get(User, listing.seller_id)
    if not seller:
        raise HTTPException(404, "Продавец не найден")
    visible = (
        Listing.seller_id == seller.id,
        Listing.id != listing.id,
        Listing.product_kind == "car",
        Listing.status == "active",
        Listing.deleted_at.is_(None),
        Listing.reserved_by_deal_id.is_(None),
    )
    total = (
        int(await session.scalar(select(func.count(Listing.id)).where(*visible)) or 0)
        if not seller.is_blocked
        else 0
    )
    items = (
        list(
            (
                await session.scalars(
                    select(Listing)
                    .where(*visible)
                    .order_by(
                        and_(
                            Listing.pinned.is_(True),
                            Listing.pinned_until > datetime.now(UTC),
                        )
                        .is_(True)
                        .desc(),
                        Listing.created_at.desc(),
                        Listing.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        if total
        else []
    )
    completed = int(
        await session.scalar(
            select(func.count(Deal.id)).where(
                Deal.seller_id == seller.id,
                Deal.status == "completed",
                Deal.completed_at.is_not(None),
                Deal.cancelled_at.is_(None),
            )
        )
        or 0
    )
    saved = bool(
        await session.scalar(
            select(Favorite.id).where(
                Favorite.user_id == user.id,
                Favorite.listing_id == listing.id,
            )
        )
    )
    return SellerContext(
        name=" ".join(filter(None, [seller.first_name, seller.last_name])).strip()
        or seller.username
        or "Продавец",
        photo_url=seller.photo_url,
        completed_sales=completed,
        saved_by_me=saved,
        other_active_count=total,
        items=await listing_collection_out(session, items, user.id),
        has_more=offset + len(items) < total,
    )


@router.get("/{listing_id}/share-link")
async def share_link(
    listing_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await car(session, listing_id)
    return {"url": f"{await bot_private_chat_link()}?startapp=listing_{listing_id}"}
