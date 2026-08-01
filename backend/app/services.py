import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import (
    AccountListing,
    AdminAction,
    AdminBalanceAdjustment,
    CartItem,
    Conversation,
    ConversationMessage,
    Deal,
    DealMessage,
    Listing,
    ListingImage,
    Notification,
    PriceOffer,
    StarPayment,
    User,
    Wallet,
    WalletTransaction,
    WithdrawalRequest,
)


AF = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value).quantize(AF, rounding=ROUND_HALF_UP)


def wallet_transaction(
    wallet: Wallet,
    transaction_type: str,
    amount: Decimal,
    available_before: Decimal,
    frozen_before: Decimal,
    description: str,
    *,
    deal_id: uuid.UUID | None = None,
    withdrawal_id: uuid.UUID | None = None,
    external_reference: str | None = None,
) -> WalletTransaction:
    return WalletTransaction(
        user_id=wallet.user_id,
        transaction_type=transaction_type,
        amount=money(amount),
        available_before=money(available_before),
        available_after=money(wallet.available_balance),
        frozen_before=money(frozen_before),
        frozen_after=money(wallet.frozen_balance),
        related_deal_id=deal_id,
        related_withdrawal_id=withdrawal_id,
        external_reference=external_reference,
        description=description,
    )


async def create_notification(session: AsyncSession, user_id: uuid.UUID, kind: str, title: str, body: str, payload: dict | None = None) -> Notification:
    notification = Notification(user_id=user_id, notification_type=kind, title=title, body=body, payload=payload or {})
    session.add(notification)
    return notification


async def create_listing(
    session: AsyncSession,
    seller: User,
    payload,
    *,
    listing_type: str,
    pinned: bool = False,
) -> Listing:
    settings = get_settings()
    if listing_type == "unique" and seller.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can create unique listings")

    async with session.begin():
        if listing_type == "regular" and settings.enable_regular_listing_fees:
            existing_count = await session.scalar(
                select(func.count(Listing.id)).where(Listing.seller_id == seller.id, Listing.listing_type == "regular")
            )
            if existing_count and settings.regular_listing_fee_after_first > 0:
                raise HTTPException(status_code=409, detail="Publication fee is configured but payment is not enabled yet")

        now = datetime.now(UTC)
        admin_pinned = seller.role == "admin" and (pinned or payload.promote_for_24h)
        listing = Listing(
            seller_id=seller.id,
            listing_type=listing_type,
            status="active",
            brand=payload.brand,
            model=payload.model,
            power_hp=payload.power_hp,
            max_speed_kph=payload.max_speed_kph,
            price_af_coins=money(payload.price_af_coins),
            pinned=admin_pinned,
            pinned_until=now + timedelta(hours=settings.listing_promotion_hours) if admin_pinned else None,
        )
        session.add(listing)
        await session.flush()
        if payload.promote_for_24h and seller.role != "admin":
            await charge_listing_promotion(session, seller, listing)
        for position, url in enumerate(payload.image_urls):
            session.add(ListingImage(listing_id=listing.id, url=url, position=position))
        if listing_type == "unique":
            session.add(AdminAction(admin_id=seller.id, action="create_unique_listing", target_type="listing", target_id=listing.id))
    await session.refresh(listing)
    return listing


async def charge_listing_promotion(session: AsyncSession, actor: User, listing: Listing) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    listing.pinned = True
    listing.pinned_until = now + timedelta(hours=settings.listing_promotion_hours)
    if actor.role == "admin":
        session.add(AdminAction(admin_id=actor.id, action="pin_listing_free", target_type="listing", target_id=listing.id))
        return
    if listing.seller_id != actor.id:
        raise HTTPException(status_code=403, detail="You can promote only your own listing")
    cost = money(settings.listing_promotion_cost_af_coins)
    wallet = await session.scalar(select(Wallet).where(Wallet.user_id == actor.id).with_for_update())
    if not wallet or wallet.available_balance < cost:
        raise HTTPException(status_code=402, detail="Недостаточно средств для закрепления")
    before_available, before_frozen = wallet.available_balance, wallet.frozen_balance
    wallet.available_balance = money(wallet.available_balance - cost)
    wallet.version += 1
    session.add(wallet_transaction(wallet, "listing_promotion", -cost, before_available, before_frozen, "Закрепление объявления на 24 часа"))


async def promote_listing(session: AsyncSession, actor: User, listing_id: uuid.UUID) -> Listing:
    async with session.begin():
        listing = await session.scalar(select(Listing).where(Listing.id == listing_id).with_for_update())
        if not listing or listing.status != "active":
            raise HTTPException(status_code=404, detail="Active listing not found")
        if actor.role != "admin" and listing.seller_id != actor.id:
            raise HTTPException(status_code=403, detail="You can promote only your own listing")
        await charge_listing_promotion(session, actor, listing)
    return listing


async def update_listing(session: AsyncSession, actor: User, listing_id: uuid.UUID, payload) -> Listing:
    async with session.begin():
        listing = await session.scalar(select(Listing).where(Listing.id == listing_id).with_for_update())
        if not listing or listing.status == "deleted":
            raise HTTPException(status_code=404, detail="Listing not found")
        if actor.role != "admin" and (listing.seller_id != actor.id or listing.listing_type != "regular"):
            raise HTTPException(status_code=403, detail="You cannot edit this listing")
        if listing.status == "reserved":
            raise HTTPException(status_code=409, detail="Reserved listing cannot be edited")
        changes = payload.model_dump(exclude_unset=True, exclude={"image_urls", "promote_for_24h"})
        for field, value in changes.items():
            if field == "price_af_coins":
                value = money(value)
            setattr(listing, field, value)
        if payload.image_urls is not None:
            await session.execute(delete(ListingImage).where(ListingImage.listing_id == listing.id))
            for position, url in enumerate(payload.image_urls):
                session.add(ListingImage(listing_id=listing.id, url=url, position=position))
        if payload.promote_for_24h:
            await charge_listing_promotion(session, actor, listing)
        if actor.role == "admin":
            session.add(AdminAction(admin_id=actor.id, action="update_listing", target_type="listing", target_id=listing.id))
    return listing


async def delete_listing(session: AsyncSession, actor: User, listing_id: uuid.UUID) -> None:
    async with session.begin():
        listing = await session.scalar(select(Listing).where(Listing.id == listing_id).with_for_update())
        if not listing or listing.status == "deleted":
            raise HTTPException(status_code=404, detail="Listing not found")
        if actor.role != "admin" and listing.seller_id != actor.id:
            raise HTTPException(status_code=403, detail="You cannot delete this listing")
        active_deal = await session.scalar(
            select(Deal.id).where(Deal.listing_id == listing.id, Deal.status.not_in(["completed", "cancelled"]))
        )
        if active_deal:
            raise HTTPException(status_code=409, detail="Listing with an active deal cannot be deleted")
        listing.status = "deleted"
        listing.deleted_at = datetime.now(UTC)
        await session.execute(delete(CartItem).where(CartItem.listing_id == listing.id))
        if actor.role == "admin":
            session.add(AdminAction(admin_id=actor.id, action="delete_listing", target_type="listing", target_id=listing.id))


async def set_listing_publication(session: AsyncSession, admin: User, listing_id: uuid.UUID, published: bool) -> Listing:
    async with session.begin():
        listing = await session.scalar(select(Listing).where(Listing.id == listing_id).with_for_update())
        if not listing or listing.status in {"deleted", "sold", "reserved"}:
            raise HTTPException(status_code=409, detail="Listing publication state cannot be changed")
        listing.status = "active" if published else "paused"
        session.add(AdminAction(admin_id=admin.id, action="publish_listing" if published else "unpublish_listing", target_type="listing", target_id=listing.id))
    return listing


async def update_special_listing(session: AsyncSession, admin: User, listing_id: uuid.UUID, payload) -> Listing:
    return await update_listing(session, admin, listing_id, payload)


async def delete_special_listing(session: AsyncSession, admin: User, listing_id: uuid.UUID) -> None:
    await delete_listing(session, admin, listing_id)


async def create_account_listing(session: AsyncSession, admin: User, payload) -> AccountListing:
    async with session.begin():
        account = AccountListing(
            seller_id=admin.id,
            status="active",
            title=payload.title.strip(),
            cars_count=payload.cars_count,
            game_currency=payload.game_currency.strip(),
            extra_currency=payload.extra_currency.strip() if payload.extra_currency else None,
            email_binding=payload.email_binding,
            description=payload.description.strip(),
            price_af_coins=money(payload.price_af_coins),
            image_url=payload.image_url,
        )
        session.add(account)
        await session.flush()
        session.add(AdminAction(admin_id=admin.id, action="create_account_listing", target_type="account_listing", target_id=account.id))
    return account


async def update_account_listing(session: AsyncSession, admin: User, account_id: uuid.UUID, payload) -> AccountListing:
    async with session.begin():
        account = await session.scalar(select(AccountListing).where(AccountListing.id == account_id).with_for_update())
        if not account or account.status == "deleted":
            raise HTTPException(status_code=404, detail="Account listing not found")
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            if field == "price_af_coins" and value is not None:
                value = money(value)
            if isinstance(value, str):
                value = value.strip()
            setattr(account, field, value)
        session.add(AdminAction(admin_id=admin.id, action="update_account_listing", target_type="account_listing", target_id=account.id))
    return account


async def delete_account_listing(session: AsyncSession, admin: User, account_id: uuid.UUID) -> None:
    async with session.begin():
        account = await session.scalar(select(AccountListing).where(AccountListing.id == account_id).with_for_update())
        if not account or account.status == "deleted":
            raise HTTPException(status_code=404, detail="Account listing not found")
        account.status = "deleted"
        session.add(AdminAction(admin_id=admin.id, action="delete_account_listing", target_type="account_listing", target_id=account.id))


async def get_or_create_conversation(session: AsyncSession, buyer: User, listing_id: uuid.UUID) -> tuple[Conversation, User]:
    async with session.begin():
        listing = await session.scalar(select(Listing).where(Listing.id == listing_id).with_for_update())
        if not listing or listing.status not in {"active", "reserved", "sold"}:
            raise HTTPException(status_code=404, detail="Listing not found")
        if listing.seller_id == buyer.id:
            raise HTTPException(status_code=400, detail="You cannot start a conversation with yourself")
        conversation = await session.scalar(
            select(Conversation).where(Conversation.listing_id == listing.id, Conversation.buyer_id == buyer.id)
        )
        if not conversation:
            if listing.status != "active":
                raise HTTPException(status_code=409, detail="A new conversation cannot be started for this listing")
            conversation = Conversation(listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id)
            session.add(conversation)
            await session.flush()
            await create_notification(
                session,
                listing.seller_id,
                "conversation_started",
                "Новый диалог по объявлению",
                f"Пользователь хочет обсудить {listing.brand} {listing.model}",
                {"conversation_id": str(conversation.id), "listing_id": str(listing.id)},
            )
        seller = await session.get(User, listing.seller_id)
    return conversation, seller


async def send_conversation_message(session: AsyncSession, sender: User, conversation_id: uuid.UUID, body: str) -> tuple[ConversationMessage, User]:
    async with session.begin():
        conversation = await session.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
        if not conversation or sender.id not in {conversation.buyer_id, conversation.seller_id}:
            raise HTTPException(status_code=404, detail="Conversation not found")
        message = ConversationMessage(conversation_id=conversation.id, sender_id=sender.id, body=body.strip(), message_type="text")
        session.add(message)
        conversation.last_message_at = datetime.now(UTC)
        recipient_id = conversation.seller_id if sender.id == conversation.buyer_id else conversation.buyer_id
        await create_notification(
            session,
            recipient_id,
            "conversation_message",
            "Новое сообщение",
            body.strip()[:240],
            {"conversation_id": str(conversation.id), "listing_id": str(conversation.listing_id)},
        )
        recipient = await session.get(User, recipient_id)
        await session.flush()
    return message, recipient


async def create_price_offer(session: AsyncSession, actor: User, conversation_id: uuid.UUID, amount: Decimal, parent_offer_id: uuid.UUID | None = None) -> tuple[PriceOffer, User]:
    async with session.begin():
        conversation = await session.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
        if not conversation or actor.id not in {conversation.buyer_id, conversation.seller_id}:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if conversation.deal_id:
            deal = await session.get(Deal, conversation.deal_id)
            if deal and deal.status not in {"cancelled"}:
                raise HTTPException(status_code=409, detail="Price cannot be negotiated after purchase")
        if parent_offer_id:
            parent = await session.scalar(select(PriceOffer).where(PriceOffer.id == parent_offer_id).with_for_update())
            if not parent or parent.conversation_id != conversation.id or parent.status != "pending" or parent.offered_by_id == actor.id:
                raise HTTPException(status_code=409, detail="Counter-offer is not allowed")
            parent.status = "countered"
            parent.responded_at = datetime.now(UTC)
        offer = PriceOffer(
            conversation_id=conversation.id,
            offered_by_id=actor.id,
            amount_af_coins=money(amount),
            status="pending",
            parent_offer_id=parent_offer_id,
        )
        session.add(offer)
        await session.flush()
        conversation.last_message_at = datetime.now(UTC)
        session.add(
            ConversationMessage(
                conversation_id=conversation.id,
                sender_id=actor.id,
                body=f"Предложена цена {offer.amount_af_coins} AF Coins",
                message_type="offer",
            )
        )
        recipient_id = conversation.seller_id if actor.id == conversation.buyer_id else conversation.buyer_id
        await create_notification(session, recipient_id, "price_offer", "Новое предложение цены", f"Предложено {offer.amount_af_coins} AF Coins", {"conversation_id": str(conversation.id), "offer_id": str(offer.id)})
        recipient = await session.get(User, recipient_id)
    return offer, recipient


async def respond_price_offer(session: AsyncSession, actor: User, offer_id: uuid.UUID, accept: bool) -> tuple[PriceOffer, User]:
    async with session.begin():
        offer = await session.scalar(select(PriceOffer).where(PriceOffer.id == offer_id).with_for_update())
        if not offer or offer.status != "pending":
            raise HTTPException(status_code=404, detail="Pending offer not found")
        conversation = await session.scalar(select(Conversation).where(Conversation.id == offer.conversation_id).with_for_update())
        if not conversation or actor.id not in {conversation.buyer_id, conversation.seller_id} or actor.id == offer.offered_by_id:
            raise HTTPException(status_code=403, detail="Only the other participant can respond")
        offer.status = "accepted" if accept else "rejected"
        offer.responded_at = datetime.now(UTC)
        if accept:
            conversation.accepted_price_af_coins = offer.amount_af_coins
        conversation.last_message_at = datetime.now(UTC)
        session.add(
            ConversationMessage(
                conversation_id=conversation.id,
                sender_id=actor.id,
                body="Предложение принято" if accept else "Предложение отклонено",
                message_type="system",
            )
        )
        recipient = await session.get(User, offer.offered_by_id)
        await create_notification(session, offer.offered_by_id, "price_offer_response", "Ответ на предложение цены", "Предложение принято" if accept else "Предложение отклонено", {"conversation_id": str(conversation.id), "offer_id": str(offer.id)})
    return offer, recipient


async def checkout_cart(session: AsyncSession, buyer: User) -> tuple[list[Deal], list[int]]:
    seller_telegram_ids: list[int] = []
    async with session.begin():
        cart_items = list(
            (await session.scalars(select(CartItem).where(CartItem.user_id == buyer.id).with_for_update())).all()
        )
        if not cart_items:
            raise HTTPException(status_code=400, detail="Cart is empty")
        listing_ids = [item.listing_id for item in cart_items]
        listings = list(
            (await session.scalars(select(Listing).where(Listing.id.in_(listing_ids)).with_for_update())).all()
        )
        by_id = {item.id: item for item in listings}
        ordered = [by_id[item_id] for item_id in listing_ids if item_id in by_id]
        if len(ordered) != len(listing_ids) or any(item.status != "active" for item in ordered):
            raise HTTPException(status_code=409, detail="One or more items have already been sold")
        if any(item.seller_id == buyer.id for item in ordered):
            raise HTTPException(status_code=400, detail="You cannot buy your own listing")

        conversations = list(
            (
                await session.scalars(
                    select(Conversation)
                    .where(Conversation.buyer_id == buyer.id, Conversation.listing_id.in_(listing_ids))
                    .with_for_update()
                )
            ).all()
        )
        conversations_by_listing = {item.listing_id: item for item in conversations}
        effective_prices = {
            item.id: money(conversations_by_listing[item.id].accepted_price_af_coins)
            if item.id in conversations_by_listing and conversations_by_listing[item.id].accepted_price_af_coins is not None
            else money(item.price_af_coins)
            for item in ordered
        }
        total = money(sum((effective_prices[item.id] for item in ordered), Decimal("0")))
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id).with_for_update())
        if not wallet or wallet.available_balance < total:
            raise HTTPException(status_code=402, detail="Недостаточно средств")
        available_before, frozen_before = wallet.available_balance, wallet.frozen_balance
        wallet.available_balance = money(wallet.available_balance - total)
        wallet.frozen_balance = money(wallet.frozen_balance + total)
        wallet.version += 1

        deals: list[Deal] = []
        for listing in ordered:
            agreed_price = effective_prices[listing.id]
            payout = money(agreed_price * Decimal("0.70"))
            commission = money(agreed_price - payout)
            deal = Deal(
                listing_id=listing.id,
                buyer_id=buyer.id,
                seller_id=listing.seller_id,
                status="paid",
                price_af_coins=agreed_price,
                frozen_amount=agreed_price,
                seller_payout=payout,
                platform_commission=commission,
            )
            session.add(deal)
            await session.flush()
            conversation = conversations_by_listing.get(listing.id)
            if not conversation:
                conversation = Conversation(listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id)
                session.add(conversation)
                await session.flush()
                conversations_by_listing[listing.id] = conversation
            conversation.deal_id = deal.id
            conversation.last_message_at = datetime.now(UTC)
            session.add(
                ConversationMessage(
                    conversation_id=conversation.id,
                    sender_id=buyer.id,
                    body=f"Сделка создана. Зарезервировано {agreed_price} AF Coins.",
                    message_type="system",
                )
            )
            listing.status = "reserved"
            listing.reserved_by_deal_id = deal.id
            deals.append(deal)
            seller = await session.get(User, listing.seller_id)
            if seller:
                seller_telegram_ids.append(seller.telegram_id)
                await create_notification(
                    session,
                    seller.id,
                    "deal_created",
                    "Ваш товар хотят купить",
                    "Откройте AUTOFLOW MARKET, чтобы ответить покупателю",
                    {"deal_id": str(deal.id)},
                )

        session.add(
            wallet_transaction(
                wallet,
                "purchase_reserved",
                -total,
                available_before,
                frozen_before,
                "Средства зарезервированы для покупки",
            )
        )
        await session.execute(delete(CartItem).where(CartItem.user_id == buyer.id))
    return deals, seller_telegram_ids


async def set_deal_status(session: AsyncSession, actor: User, deal_id: uuid.UUID, next_status: str) -> Deal:
    allowed = {
        "seller_contacted": {"paid"},
        "transfer_in_progress": {"paid", "seller_contacted"},
        "disputed": {"paid", "seller_contacted", "transfer_in_progress"},
    }
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if not deal or actor.id not in {deal.buyer_id, deal.seller_id}:
            raise HTTPException(status_code=404, detail="Deal not found")
        if deal.status not in allowed[next_status]:
            raise HTTPException(status_code=409, detail=f"Cannot change {deal.status} to {next_status}")
        if next_status in {"seller_contacted", "transfer_in_progress"} and actor.id != deal.seller_id:
            raise HTTPException(status_code=403, detail="Only the seller can change this status")
        deal.status = next_status
        if next_status == "transfer_in_progress":
            deal.transfer_started_at = datetime.now(UTC)
        other_id = deal.seller_id if actor.id == deal.buyer_id else deal.buyer_id
        await create_notification(session, other_id, "deal_status", "Статус сделки изменён", f"Новый статус: {next_status}", {"deal_id": str(deal.id)})
    return deal


async def complete_deal(session: AsyncSession, buyer: User, deal_id: uuid.UUID) -> Deal:
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if not deal or deal.buyer_id != buyer.id:
            raise HTTPException(status_code=404, detail="Deal not found")
        if deal.status != "transfer_in_progress" or not deal.transfer_started_at:
            raise HTTPException(status_code=409, detail="Transfer has not started")
        if datetime.now(UTC) - deal.transfer_started_at < timedelta(minutes=5):
            raise HTTPException(status_code=409, detail="Confirmation becomes available five minutes after transfer starts")
        listing = await session.scalar(select(Listing).where(Listing.id == deal.listing_id).with_for_update())
        buyer_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == deal.buyer_id).with_for_update())
        seller_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == deal.seller_id).with_for_update())
        if not listing or not buyer_wallet or not seller_wallet or buyer_wallet.frozen_balance < deal.frozen_amount:
            raise HTTPException(status_code=409, detail="Settlement state is inconsistent")

        buyer_avail_before, buyer_frozen_before = buyer_wallet.available_balance, buyer_wallet.frozen_balance
        seller_avail_before, seller_frozen_before = seller_wallet.available_balance, seller_wallet.frozen_balance
        buyer_wallet.frozen_balance = money(buyer_wallet.frozen_balance - deal.frozen_amount)
        buyer_wallet.version += 1
        seller_wallet.available_balance = money(seller_wallet.available_balance + deal.seller_payout)
        seller_wallet.total_earned = money(seller_wallet.total_earned + deal.seller_payout)
        seller_wallet.version += 1

        now = datetime.now(UTC)
        deal.status = "completed"
        deal.buyer_confirmed_at = now
        deal.completed_at = now
        listing.status = "sold"
        listing.sold_at = now
        listing.reserved_by_deal_id = None
        session.add(wallet_transaction(buyer_wallet, "purchase_completed", Decimal("0"), buyer_avail_before, buyer_frozen_before, "Покупка завершена", deal_id=deal.id))
        session.add(wallet_transaction(seller_wallet, "sale_income", deal.seller_payout, seller_avail_before, seller_frozen_before, "70% стоимости сделки начислено продавцу", deal_id=deal.id))
        await create_notification(session, deal.seller_id, "deal_completed", "Сделка завершена", f"Начислено {deal.seller_payout} AF Coins", {"deal_id": str(deal.id)})
    return deal


async def cancel_deal(session: AsyncSession, actor: User, deal_id: uuid.UUID) -> Deal:
    """Cancel an unstarted transfer and atomically release the buyer's reservation."""
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if not deal or actor.id not in {deal.buyer_id, deal.seller_id}:
            raise HTTPException(status_code=404, detail="Deal not found")
        if deal.status not in {"paid", "seller_contacted"}:
            raise HTTPException(status_code=409, detail="This deal can no longer be cancelled automatically")

        listing = await session.scalar(select(Listing).where(Listing.id == deal.listing_id).with_for_update())
        buyer_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == deal.buyer_id).with_for_update())
        if not listing or not buyer_wallet or buyer_wallet.frozen_balance < deal.frozen_amount:
            raise HTTPException(status_code=409, detail="Cancellation state is inconsistent")

        available_before, frozen_before = buyer_wallet.available_balance, buyer_wallet.frozen_balance
        buyer_wallet.available_balance = money(buyer_wallet.available_balance + deal.frozen_amount)
        buyer_wallet.frozen_balance = money(buyer_wallet.frozen_balance - deal.frozen_amount)
        buyer_wallet.version += 1
        deal.status = "cancelled"
        deal.cancelled_at = datetime.now(UTC)
        listing.status = "active"
        listing.reserved_by_deal_id = None
        session.add(
            wallet_transaction(
                buyer_wallet,
                "purchase_reservation_released",
                deal.frozen_amount,
                available_before,
                frozen_before,
                "Резерв возвращён после отмены сделки",
                deal_id=deal.id,
            )
        )
        other_id = deal.seller_id if actor.id == deal.buyer_id else deal.buyer_id
        await create_notification(
            session,
            other_id,
            "deal_cancelled",
            "Сделка отменена",
            "Зарезервированные средства возвращены покупателю",
            {"deal_id": str(deal.id)},
        )
    return deal


async def resolve_dispute(session: AsyncSession, admin: User, deal_id: uuid.UUID, outcome: str, reason: str) -> Deal:
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if not deal or deal.status != "disputed":
            raise HTTPException(status_code=404, detail="Disputed deal not found")
        listing = await session.scalar(select(Listing).where(Listing.id == deal.listing_id).with_for_update())
        buyer_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == deal.buyer_id).with_for_update())
        seller_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == deal.seller_id).with_for_update())
        if not listing or not buyer_wallet or not seller_wallet or buyer_wallet.frozen_balance < deal.frozen_amount:
            raise HTTPException(status_code=409, detail="Settlement state is inconsistent")
        buyer_available_before, buyer_frozen_before = buyer_wallet.available_balance, buyer_wallet.frozen_balance
        now = datetime.now(UTC)
        if outcome == "refund":
            buyer_wallet.available_balance = money(buyer_wallet.available_balance + deal.frozen_amount)
            buyer_wallet.frozen_balance = money(buyer_wallet.frozen_balance - deal.frozen_amount)
            buyer_wallet.version += 1
            deal.status = "cancelled"
            deal.cancelled_at = now
            listing.status = "active"
            listing.reserved_by_deal_id = None
            session.add(wallet_transaction(buyer_wallet, "dispute_refund", deal.frozen_amount, buyer_available_before, buyer_frozen_before, f"Возврат по спору: {reason}", deal_id=deal.id))
            buyer_body = "Средства возвращены на доступный баланс"
            seller_body = "Сделка отменена, средства возвращены покупателю"
        else:
            seller_available_before, seller_frozen_before = seller_wallet.available_balance, seller_wallet.frozen_balance
            buyer_wallet.frozen_balance = money(buyer_wallet.frozen_balance - deal.frozen_amount)
            buyer_wallet.version += 1
            seller_wallet.available_balance = money(seller_wallet.available_balance + deal.seller_payout)
            seller_wallet.total_earned = money(seller_wallet.total_earned + deal.seller_payout)
            seller_wallet.version += 1
            deal.status = "completed"
            deal.completed_at = now
            listing.status = "sold"
            listing.sold_at = now
            listing.reserved_by_deal_id = None
            session.add(wallet_transaction(buyer_wallet, "dispute_completed", Decimal("0"), buyer_available_before, buyer_frozen_before, f"Сделка завершена администратором: {reason}", deal_id=deal.id))
            session.add(wallet_transaction(seller_wallet, "sale_income", deal.seller_payout, seller_available_before, seller_frozen_before, f"70% начислено после решения спора: {reason}", deal_id=deal.id))
            buyer_body = "Сделка завершена решением администратора"
            seller_body = f"Сделка завершена, начислено {deal.seller_payout} AF Coins"
        session.add(AdminAction(admin_id=admin.id, action=f"resolve_dispute_{outcome}", target_type="deal", target_id=deal.id, reason=reason))
        await create_notification(session, deal.buyer_id, "dispute_resolved", "Спор рассмотрен", buyer_body, {"deal_id": str(deal.id)})
        await create_notification(session, deal.seller_id, "dispute_resolved", "Спор рассмотрен", seller_body, {"deal_id": str(deal.id)})
    return deal


async def create_withdrawal(session: AsyncSession, user: User, payload) -> WithdrawalRequest:
    minimum = money(get_settings().min_withdrawal_af_coins)
    amount = money(payload.amount)
    if amount < minimum:
        raise HTTPException(status_code=400, detail=f"Minimum withdrawal is {minimum} AF Coins")
    async with session.begin():
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id).with_for_update())
        if not wallet or wallet.available_balance < amount:
            raise HTTPException(status_code=402, detail="Недостаточно средств")
        before_available, before_frozen = wallet.available_balance, wallet.frozen_balance
        wallet.available_balance = money(wallet.available_balance - amount)
        wallet.frozen_balance = money(wallet.frozen_balance + amount)
        wallet.version += 1
        withdrawal = WithdrawalRequest(user_id=user.id, amount=amount, payout_method=payload.payout_method, details=payload.details, status="pending")
        session.add(withdrawal)
        await session.flush()
        session.add(wallet_transaction(wallet, "withdrawal_reserved", -amount, before_available, before_frozen, "AF Coins заморожены для заявки на вывод", withdrawal_id=withdrawal.id))
        admins = list((await session.scalars(select(User).where(User.role == "admin"))).all())
        for admin in admins:
            await create_notification(session, admin.id, "withdrawal_created", "Новая заявка на вывод", f"Пользователь {user.telegram_id}: {amount} AF Coins", {"withdrawal_id": str(withdrawal.id)})
    return withdrawal


async def decide_withdrawal(session: AsyncSession, admin: User, withdrawal_id: uuid.UUID, action: str, reason: str | None) -> WithdrawalRequest:
    targets = {"approve": "approved", "paid": "paid", "reject": "rejected"}
    expected = {"approve": {"pending"}, "paid": {"approved"}, "reject": {"pending", "approved"}}[action]
    target = targets[action]
    async with session.begin():
        request = await session.scalar(select(WithdrawalRequest).where(WithdrawalRequest.id == withdrawal_id).with_for_update())
        if not request:
            raise HTTPException(status_code=404, detail="Withdrawal not found")
        if request.status not in expected:
            raise HTTPException(status_code=409, detail=f"Withdrawal must be one of {sorted(expected)}")
        if action == "reject" and not reason:
            raise HTTPException(status_code=400, detail="Rejection reason is required")
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == request.user_id).with_for_update())
        if not wallet:
            raise HTTPException(status_code=409, detail="Wallet not found")
        before_available, before_frozen = wallet.available_balance, wallet.frozen_balance
        now = datetime.now(UTC)
        request.status = target
        request.reviewed_by_id = admin.id
        request.reviewed_at = now
        transaction = None
        if action == "paid":
            if wallet.frozen_balance < request.amount:
                raise HTTPException(status_code=409, detail="Frozen balance is insufficient")
            wallet.frozen_balance = money(wallet.frozen_balance - request.amount)
            request.paid_at = now
            transaction = wallet_transaction(wallet, "withdrawal_paid", -request.amount, before_available, before_frozen, "Ручная выплата отмечена администратором", withdrawal_id=request.id)
        elif action == "reject":
            if wallet.frozen_balance < request.amount:
                raise HTTPException(status_code=409, detail="Frozen balance is insufficient")
            wallet.frozen_balance = money(wallet.frozen_balance - request.amount)
            wallet.available_balance = money(wallet.available_balance + request.amount)
            request.rejection_reason = reason
            transaction = wallet_transaction(wallet, "withdrawal_rejected", request.amount, before_available, before_frozen, f"Заявка отклонена: {reason}", withdrawal_id=request.id)
        wallet.version += 1
        if transaction:
            session.add(transaction)
        session.add(AdminAction(admin_id=admin.id, action=f"withdrawal_{target}", target_type="withdrawal", target_id=request.id, reason=reason))
        await create_notification(session, request.user_id, f"withdrawal_{target}", "Статус заявки на вывод изменён", f"Новый статус: {target}", {"withdrawal_id": str(request.id)})
    return request


async def cancel_withdrawal(session: AsyncSession, user: User, withdrawal_id: uuid.UUID) -> WithdrawalRequest:
    async with session.begin():
        request = await session.scalar(
            select(WithdrawalRequest).where(WithdrawalRequest.id == withdrawal_id).with_for_update()
        )
        if not request or request.user_id != user.id:
            raise HTTPException(status_code=404, detail="Withdrawal not found")
        if request.status != "pending":
            raise HTTPException(status_code=409, detail="Only a pending withdrawal can be cancelled")
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id).with_for_update())
        if not wallet or wallet.frozen_balance < request.amount:
            raise HTTPException(status_code=409, detail="Withdrawal state is inconsistent")
        before_available, before_frozen = wallet.available_balance, wallet.frozen_balance
        wallet.available_balance = money(wallet.available_balance + request.amount)
        wallet.frozen_balance = money(wallet.frozen_balance - request.amount)
        wallet.version += 1
        request.status = "cancelled"
        session.add(
            wallet_transaction(
                wallet,
                "withdrawal_cancelled",
                request.amount,
                before_available,
                before_frozen,
                "Заявка отменена пользователем, AF Coins возвращены",
                withdrawal_id=request.id,
            )
        )
    return request


async def adjust_balance(session: AsyncSession, admin: User, payload) -> Wallet:
    amount = money(payload.amount)
    async with session.begin():
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == payload.user_id).with_for_update())
        if not wallet:
            raise HTTPException(status_code=404, detail="Wallet not found")
        before_available, before_frozen = wallet.available_balance, wallet.frozen_balance
        if wallet.available_balance + amount < 0:
            raise HTTPException(status_code=409, detail="Adjustment would make balance negative")
        wallet.available_balance = money(wallet.available_balance + amount)
        wallet.version += 1
        transaction = wallet_transaction(wallet, "admin_adjustment", amount, before_available, before_frozen, payload.reason)
        session.add(transaction)
        await session.flush()
        session.add(AdminBalanceAdjustment(admin_id=admin.id, user_id=payload.user_id, amount=amount, reason=payload.reason, wallet_transaction_id=transaction.id))
        session.add(AdminAction(admin_id=admin.id, action="balance_adjustment", target_type="user", target_id=payload.user_id, reason=payload.reason, metadata_json={"amount": str(amount)}))
    return wallet


async def process_successful_payment(session: AsyncSession, telegram_id: int, payment: dict) -> bool:
    if payment.get("currency") != "XTR":
        raise HTTPException(status_code=400, detail="Only XTR top-ups are accepted")
    invoice_payload = str(payment.get("invoice_payload") or "")
    if not invoice_payload.startswith("autoflow_topup:"):
        raise HTTPException(status_code=400, detail="Unknown invoice payload")
    charge_id = payment["telegram_payment_charge_id"]
    xtr_amount = int(payment["total_amount"])
    try:
        expected_amount = int(invoice_payload.rsplit(":", 1)[1])
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid invoice payload") from exc
    if xtr_amount <= 0 or xtr_amount != expected_amount:
        raise HTTPException(status_code=400, detail="Invoice amount mismatch")
    async with session.begin():
        if await session.scalar(select(StarPayment.id).where(StarPayment.telegram_payment_charge_id == charge_id)):
            return False
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id).with_for_update())
        if not wallet:
            raise HTTPException(status_code=409, detail="Wallet not found")
        amount = money(xtr_amount)
        before_available, before_frozen = wallet.available_balance, wallet.frozen_balance
        wallet.available_balance = money(wallet.available_balance + amount)
        wallet.version += 1
        record = StarPayment(
            user_id=user.id,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id=payment.get("provider_payment_charge_id"),
            xtr_amount=xtr_amount,
            af_coin_amount=amount,
            status="credited",
            raw_payload=payment,
            processed_at=datetime.now(UTC),
        )
        session.add(record)
        session.add(wallet_transaction(wallet, "star_payment_credit", amount, before_available, before_frozen, "Telegram Stars converted to AF Coins 1:1", external_reference=charge_id))
        await create_notification(session, user.id, "wallet_topup", "Баланс пополнен", f"Начислено {amount} AF Coins", {"payment_id": charge_id})
    return True
    PriceOffer,
