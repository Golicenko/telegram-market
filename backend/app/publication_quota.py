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
        Listing.product_kind == "car",
        or_(and_(Listing.status.in_(("active", "reserved")), Listing.deleted_at.is_(None)), held_sale),
    )) or 0)


async def publication_rules(session, user):
    rules = await session.get(PublicationRules, 1)
    limit, price, enabled = (rules.free_limit, rules.price_stars, rules.enabled) if rules else (5, 5, True)
    from .seller_vip import active_limits
    vip = await active_limits(session, user.id)
    active = await vip_listing_count(session, user.id, "car") if vip else await active_listing_count(session, user.id)
    if vip:
        limit = vip["car_limit"]
    return {"free_limit": limit, "price_stars": price, "enabled": enabled,
            "active_count": active, "used": active, "remaining": max(0, limit - active),
            "vip_active": bool(vip), "vip_limit_reached": bool(vip and active >= limit),
            "payment_required": not vip and enabled and user.role != "admin" and active >= limit}


async def vip_listing_count(session, seller_id, kind):
    """VIP caps are simultaneous active listings, never lifetime publications."""
    return int(await session.scalar(select(func.count()).select_from(Listing).where(
        Listing.seller_id == seller_id, Listing.product_kind == kind,
        Listing.status == "active", Listing.deleted_at.is_(None),
    )) or 0)


async def require_vip_slot(session, user, kind="car"):
    """Call under the existing seller lock, including paid-draft fulfillment."""
    from .seller_vip import active_limits
    vip = await active_limits(session, user.id)
    if vip:
        limit = vip["account_limit" if kind == "account" else "car_limit"]
        active = await vip_listing_count(session, user.id, kind)
        if active >= limit:
            raise HTTPException(409, {"code": "seller_vip_listing_limit", "limit": limit,
                "active_count": active, "message": "Достигнут лимит активных объявлений вашего VIP. Освободите место."})
    return vip


async def require_free_slot(session, user):
    if await require_vip_slot(session, user):
        return
    rules = await publication_rules(session, user)
    if rules["payment_required"]:
        raise HTTPException(402, {"code": "publication_payment_required", **rules,
            "message": "Лимит бесплатных объявлений. Удалите старое или оплатите публикацию."})
