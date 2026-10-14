"""Shared CP1/CP2 slots. Call enforcement under the seller's NO KEY UPDATE lock."""
from fastapi import HTTPException
from sqlalchemy import and_, exists, func, or_, select

from .models import Deal, Listing, PublicationRules


async def active_listing_count(session, seller_id):
    held_sale = exists(select(Deal.id).where(
        Deal.listing_id == Listing.id,
        Deal.status.in_(("paid", "seller_contacted", "transfer_in_progress", "disputed")),
        Deal.frozen_amount > 0,
    ))
    return int(await session.scalar(select(func.count()).select_from(Listing).where(
        Listing.seller_id == seller_id, Listing.listing_type == "regular",
        or_(and_(Listing.status.in_(("active", "reserved")), Listing.deleted_at.is_(None)), held_sale),
    )) or 0)


async def publication_rules(session, user):
    rules = await session.get(PublicationRules, 1)
    limit, price, enabled = (rules.free_limit, rules.price_stars, rules.enabled) if rules else (5, 5, True)
    active = await active_listing_count(session, user.id)
    return {"free_limit": limit, "price_stars": price, "enabled": enabled,
            "active_count": active, "used": active, "remaining": max(0, limit - active),
            "payment_required": enabled and user.role != "admin" and active >= limit}


async def require_free_slot(session, user):
    rules = await publication_rules(session, user)
    if rules["payment_required"]:
        raise HTTPException(402, {"code": "publication_payment_required", **rules,
            "message": "Лимит бесплатных объявлений. Удалите старое или оплатите публикацию."})
