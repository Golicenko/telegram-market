"""Paid seller inactivity and offer expiry are distinct; ordinary chats have no sanctions."""
from datetime import UTC, datetime, timedelta
from sqlalchemy import select
from .config import get_settings
from .models import Conversation, Listing, Notification, PriceOffer

SELLER_NOTICE = "⚠️ Ваши объявления были временно сняты с публикации из-за отсутствия ответа покупателю более 24 часов."
BUYER_NOTICE = "✅ Сделка отменена. Средства полностью возвращены на ваш баланс, так как продавец не ответил в течение 24 часов."


def offer_response_expired(offer, now):
    created = offer.created_at
    if created is None:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created + timedelta(seconds=get_settings().seller_response_timeout_seconds) <= now


def record_buyer_request(conversation, now, deal=None):
    if deal is None:
        return  # Ordinary messages never penalize sellers; offers use their own creation time.
    if conversation.inactivity_status == "processed":
        return
    if deal and deal.status not in {"paid", "seller_contacted"}:
        return  # Transfer/dispute requires the existing support/settlement workflow.
    conversation.response_required_at = now
    conversation.inactivity_deadline = now + timedelta(seconds=get_settings().seller_response_timeout_seconds)
    conversation.inactivity_status = "waiting"
    if deal:
        deal.seller_response_deadline = conversation.inactivity_deadline
        deal.seller_responded_at = None


def record_seller_response(conversation, now):
    conversation.inactivity_status = "answered"
    conversation.inactivity_deadline = None


async def hide_active_listings(session, seller_id):
    listings = list((await session.scalars(select(Listing).where(
        Listing.seller_id == seller_id, Listing.status == "active", Listing.deleted_at.is_(None),
    ).order_by(Listing.id).with_for_update())).all())
    for listing in listings:
        listing.status = "paused"
    return [str(listing.id) for listing in listings]


async def process_unanswered_dialog(session, conversation_id, now=None):
    """Expire unanswered buyer offers only; never hide inventory for negotiation."""
    now = now or datetime.now(UTC)
    async with session.begin():
        snapshot = await session.get(Conversation, conversation_id)
        if not snapshot or snapshot.conversation_type != "deal":
            return False
        # Listing -> conversation is the same order used by negotiation/purchase.
        await session.scalar(select(Listing).where(Listing.id == snapshot.listing_id).with_for_update())
        conversation = await session.scalar(select(Conversation).where(
            Conversation.id == conversation_id).with_for_update().execution_options(populate_existing=True))
        if not conversation or conversation.deal_id or conversation.archived_at:
            return False
        offers = list((await session.scalars(select(PriceOffer).where(
            PriceOffer.conversation_id == conversation.id,
            PriceOffer.offered_by_id == conversation.buyer_id, PriceOffer.status == "pending",
            PriceOffer.created_at <= now - timedelta(seconds=get_settings().seller_response_timeout_seconds),
        ).with_for_update())).all())
        if not offers:
            return False
        for offer in offers:
            offer.status = "cancelled"
            offer.responded_at = now
        await session.flush()
        remaining = await session.scalar(select(PriceOffer.id).where(
            PriceOffer.conversation_id == conversation.id, PriceOffer.status.in_(("pending", "accepted")),
        ).limit(1))
        if not remaining:
            conversation.accepted_price_af_coins = None
            conversation.inactivity_status = "processed"
            conversation.inactivity_processed_at = now
            conversation.archived_at = now
        session.add(Notification(user_id=conversation.buyer_id, notification_type="price_offer_timeout",
            title="Предложение цены отменено",
            body="Предложение цены отменено: продавец не принял и не отклонил его в течение 24 часов.",
            payload={"conversation_id": str(conversation.id), "offer_ids": [str(offer.id) for offer in offers],
                     "reason": "offer_response_timeout", "processed_at": now.isoformat()},
            delivery_status="pending"))
        return True
