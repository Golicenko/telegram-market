"""Response-required state; ordinary dialogues never refund unrelated deals."""
from datetime import UTC, datetime, timedelta
from sqlalchemy import select
from .config import get_settings
from .models import Conversation, Listing, Notification

SELLER_NOTICE = "⚠️ Ваши объявления были временно сняты с публикации из-за отсутствия ответа покупателю более 24 часов."
BUYER_NOTICE = "✅ Сделка отменена. Средства полностью возвращены на ваш баланс, так как продавец не ответил в течение 24 часов."


def record_buyer_request(conversation, now, deal=None):
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
    now = now or datetime.now(UTC)
    async with session.begin():
        snapshot = await session.get(Conversation, conversation_id)
        if not snapshot:
            return False
        # Listing -> conversation is the same order used by negotiation/purchase.
        await session.scalars(select(Listing).where(Listing.seller_id == snapshot.seller_id,
            Listing.status == "active").order_by(Listing.id).with_for_update())
        conversation = await session.scalar(select(Conversation).where(
            Conversation.id == conversation_id).with_for_update().execution_options(populate_existing=True))
        if (not conversation or conversation.deal_id or conversation.archived_at
                or conversation.inactivity_status != "waiting" or not conversation.inactivity_deadline
                or conversation.inactivity_deadline > now):
            return False
        listing_ids = await hide_active_listings(session, conversation.seller_id)
        conversation.inactivity_status = "processed"
        conversation.inactivity_processed_at = now
        if conversation.conversation_type == "deal":
            conversation.archived_at = now
        # Durable event doubles as recipient-specific outbox item. No fictitious refund notice.
        session.add(Notification(user_id=conversation.seller_id, notification_type="seller_inactive_hidden",
            title="Неактивность продавца обработана", body=SELLER_NOTICE,
            payload={"conversation_id": str(conversation.id), "listing_ids": listing_ids,
                     "reason": "seller_inactive", "processed_at": now.isoformat()},
            delivery_status="pending" if listing_ids else "not_required"))
        return True
