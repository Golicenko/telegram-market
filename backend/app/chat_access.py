"""One server-side definition of a live user-facing deal thread."""
from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from .models import Conversation, Deal, Listing, PriceOffer

# Keep the existing financial workflow's detailed statuses.
ACTIVE_DEAL_STATUSES = ("paid", "seller_contacted", "transfer_in_progress", "buyer_confirmed", "disputed")
ACTIVE_OFFER_STATUSES = ("pending", "accepted")


def active_thread_clause():
    purchase = select(Deal.id).where(
        Deal.id == Conversation.deal_id,
        Deal.conversation_id == Conversation.id,
        Deal.buyer_id == Conversation.buyer_id,
        Deal.seller_id == Conversation.seller_id,
        Deal.status.in_(ACTIVE_DEAL_STATUSES),
    ).correlate(Conversation).exists()
    offer = select(PriceOffer.id).join(Listing, Listing.id == PriceOffer.listing_id).where(
        PriceOffer.conversation_id == Conversation.id,
        PriceOffer.listing_id == Conversation.listing_id,
        PriceOffer.status.in_(ACTIVE_OFFER_STATUSES),
        Listing.status == "active",
        Listing.deleted_at.is_(None),
    ).correlate(Conversation).exists()
    return and_(
        Conversation.conversation_type == "deal",
        Conversation.archived_at.is_(None),
        or_(purchase, and_(Conversation.deal_id.is_(None), offer)),
    )


async def require_active_chat(session, conversation, actor):
    if not conversation or actor.id not in {conversation.buyer_id, conversation.seller_id}:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.conversation_type == "dialog":
        return conversation
    active = await session.scalar(select(Conversation.id).where(
        Conversation.id == conversation.id, active_thread_clause(),
    ))
    if not active:
        raise HTTPException(status_code=409, detail="Чат сделки закрыт или не имеет активного предложения/покупки")
    return conversation


async def require_active_chat_by_id(session, conversation_id, actor):
    conversation = await session.get(Conversation, conversation_id)
    return await require_active_chat(session, conversation, actor)
