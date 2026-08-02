import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query, UploadFile, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user, require_admin
from .bot import (
    answer_pre_checkout_query,
    create_star_invoice_link,
    send_bot_notification,
    send_bot_photo,
)
from .config import Settings, get_settings
from .database import get_session
from .models import AccountListing, AdminAction, Advertisement, CartItem, Conversation, ConversationMessage, Deal, DealMessage, Favorite, Listing, ListingImage, Notification, PriceOffer, StarPayment, StarPaymentIntent, SupportMessage, SupportTicket, User, Wallet, WalletTransaction, WithdrawalRequest
from .schemas import (
    AccountListingCreate,
    AccountListingOut,
    AccountListingUpdate,
    AdvertisementOut,
    AdvertisementUpsert,
    AdminWithdrawalOut,
    BalanceAdjustmentCreate,
    ConversationMessageOut,
    CounterOfferCreate,
    DealResolution,
    DealOut,
    ListingCreate,
    ListingOut,
    ListingUpdate,
    MeOut,
    MessageCreate,
    MessageOut,
    NotificationOut,
    PriceOfferCreate,
    PriceOfferOut,
    ProfileOut,
    StarPaymentIntentCreate,
    StarPaymentIntentOut,
    StarPaymentStatusOut,
    SupportReplyCreate,
    SupportMessageOut,
    SupportStatusUpdate,
    SupportTicketCreate,
    SupportTicketOut,
    UniqueListingCreate,
    UserOut,
    WalletOut,
    WithdrawalCreate,
    WithdrawalDecision,
    WithdrawalOut,
)
from .services import (
    adjust_balance,
    cancel_deal,
    cancel_withdrawal,
    checkout_cart,
    complete_deal,
    create_account_listing,
    create_listing,
    create_notification,
    create_price_offer,
    create_star_payment_intent,
    create_withdrawal,
    decide_withdrawal,
    delete_account_listing,
    delete_listing,
    delete_special_listing,
    get_or_create_conversation,
    process_successful_payment,
    promote_listing,
    resolve_dispute,
    respond_price_offer,
    send_conversation_message,
    set_deal_status,
    set_listing_publication,
    update_account_listing,
    update_listing,
    update_special_listing,
    validate_star_pre_checkout,
)


router = APIRouter(prefix="/api")
UPLOAD_DIR = Path(get_settings().upload_dir) if get_settings().upload_dir else Path(__file__).resolve().parents[1] / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def listing_out(session: AsyncSession, listing: Listing, buyer_id: uuid.UUID | None = None) -> ListingOut:
    images = list((await session.scalars(select(ListingImage.url).where(ListingImage.listing_id == listing.id).order_by(ListingImage.position))).all())
    effective_price = None
    if buyer_id:
        effective_price = await session.scalar(
            select(Conversation.accepted_price_af_coins).where(
                Conversation.listing_id == listing.id,
                Conversation.buyer_id == buyer_id,
            )
        )
    is_pinned = bool(listing.pinned and listing.pinned_until and listing.pinned_until > datetime.now(UTC))
    return ListingOut.model_validate(listing).model_copy(
        update={"images": images, "pinned": is_pinned, "effective_price_af_coins": effective_price}
    )


async def expire_promotions(session: AsyncSession) -> None:
    result = await session.execute(
        update(Listing)
        .where(Listing.pinned.is_(True), Listing.pinned_until <= datetime.now(UTC))
        .values(pinned=False, pinned_until=None)
    )
    if result.rowcount:
        await session.commit()


async def conversation_details(session: AsyncSession, conversation: Conversation, viewer: User | None = None, allow_admin: bool = False) -> dict:
    if viewer and not allow_admin and viewer.id not in {conversation.buyer_id, conversation.seller_id}:
        raise HTTPException(status_code=404, detail="Conversation not found")
    listing = await session.get(Listing, conversation.listing_id)
    deal = await session.get(Deal, conversation.deal_id) if conversation.deal_id else None
    other_id = conversation.seller_id if viewer and viewer.id == conversation.buyer_id else conversation.buyer_id
    other = await session.get(User, other_id)
    offers = list((await session.scalars(select(PriceOffer).where(PriceOffer.conversation_id == conversation.id).order_by(PriceOffer.created_at))).all())
    return {
        "id": str(conversation.id),
        "listing": await listing_out(session, listing, viewer.id if viewer else None),
        "deal": DealOut.model_validate(deal) if deal else None,
        "buyer_id": str(conversation.buyer_id),
        "seller_id": str(conversation.seller_id),
        "accepted_price_af_coins": conversation.accepted_price_af_coins,
        "counterparty": {
            "id": str(other.id),
            "name": " ".join(filter(None, [other.first_name, other.last_name])),
            "username": other.username,
            "photo_url": other.photo_url,
            "mini_app_last_active_at": other.mini_app_last_active_at,
        },
        "offers": [PriceOfferOut.model_validate(item) for item in offers],
        "created_at": conversation.created_at,
        "last_message_at": conversation.last_message_at,
    }


async def ensure_deal_participant(session: AsyncSession, deal_id: uuid.UUID, user: User) -> Deal:
    deal = await session.get(Deal, deal_id)
    if not deal or user.id not in {deal.buyer_id, deal.seller_id}:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


async def queue_counterparty_notification(
    session: AsyncSession,
    background_tasks: BackgroundTasks,
    deal: Deal,
    actor: User,
    text: str,
) -> None:
    recipient_id = deal.seller_id if actor.id == deal.buyer_id else deal.buyer_id
    recipient = await session.get(User, recipient_id)
    if recipient and recipient.bot_started:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, text)


async def support_ticket_out(session: AsyncSession, ticket: SupportTicket) -> SupportTicketOut:
    messages = list(
        (
            await session.scalars(
                select(SupportMessage)
                .where(SupportMessage.ticket_id == ticket.id)
                .order_by(SupportMessage.created_at)
            )
        ).all()
    )
    return SupportTicketOut.model_validate(ticket).model_copy(
        update={"messages": [SupportMessageOut.model_validate(message) for message in messages]}
    )


def validate_image_content(content: bytes, content_type: str | None) -> str:
    signatures = {
        "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
        "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
        "image/webp": (b"RIFF", ".webp"),
    }
    signature = signatures.get(content_type or "")
    if not signature:
        raise HTTPException(status_code=415, detail="Разрешены только JPG, PNG и WEBP")
    prefix, extension = signature
    if not content.startswith(prefix) or (content_type == "image/webp" and content[8:12] != b"WEBP"):
        raise HTTPException(status_code=415, detail="Содержимое файла не соответствует изображению")
    return extension


@router.get("/health")
async def health():
    return {"status": "ok", "currency": "AF Coins", "stars_invoice_enabled": bool(get_settings().bot_token)}


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
    return MeOut(user=user, wallet=wallet)


@router.post("/uploads", status_code=201)
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    max_bytes = get_settings().upload_max_bytes
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="Image exceeds 5 MB")
    extension = validate_image_content(content, file.content_type)
    filename = f"{user.id}-{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / filename).write_bytes(content)
    return {"url": f"/uploads/{filename}"}


@router.post("/admin/advertisement/upload", status_code=201)
async def upload_advertisement_image(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
):
    max_bytes = 2 * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="Рекламное изображение не должно превышать 2 МБ")
    extension = validate_image_content(content, file.content_type)
    filename = f"advertisement-{admin.id}-{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / filename).write_bytes(content)
    return {"url": f"/uploads/{filename}"}


@router.get("/advertisement", response_model=AdvertisementOut | None)
async def active_advertisement(session: AsyncSession = Depends(get_session)):
    return await session.scalar(
        select(Advertisement)
        .where(Advertisement.is_active.is_(True))
        .order_by(Advertisement.updated_at.desc())
        .limit(1)
    )


@router.get("/admin/advertisement", response_model=AdvertisementOut | None)
async def get_advertisement(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return await session.scalar(select(Advertisement).order_by(Advertisement.updated_at.desc()).limit(1))


@router.put("/admin/advertisement", response_model=AdvertisementOut)
async def upsert_advertisement(
    payload: AdvertisementUpsert,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        advertisement = await session.scalar(
            select(Advertisement).order_by(Advertisement.updated_at.desc()).with_for_update().limit(1)
        )
        if advertisement:
            advertisement.image_url = payload.image_url
            advertisement.link_url = payload.link_url
            advertisement.is_active = payload.is_active
            advertisement.admin_id = admin.id
        else:
            advertisement = Advertisement(
                image_url=payload.image_url,
                link_url=payload.link_url,
                is_active=payload.is_active,
                admin_id=admin.id,
            )
            session.add(advertisement)
            await session.flush()
        session.add(
            AdminAction(
                admin_id=admin.id,
                action="advertisement_upsert",
                target_type="advertisement",
                target_id=advertisement.id,
            )
        )
    await session.refresh(advertisement)
    return advertisement


@router.delete("/admin/advertisement", status_code=204)
async def delete_advertisement(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        advertisement = await session.scalar(
            select(Advertisement).order_by(Advertisement.updated_at.desc()).with_for_update().limit(1)
        )
        if not advertisement:
            raise HTTPException(status_code=404, detail="Реклама не найдена")
        advertisement_id = advertisement.id
        await session.delete(advertisement)
        session.add(
            AdminAction(
                admin_id=admin.id,
                action="advertisement_delete",
                target_type="advertisement",
                target_id=advertisement_id,
            )
        )


@router.get("/listings", response_model=list[ListingOut])
async def list_listings(
    listing_type: str = Query(alias="type", pattern="^(regular|unique)$"),
    brand: str | None = None,
    model: str | None = None,
    max_price: Decimal | None = Query(default=None, ge=50),
    min_power: int | None = Query(default=None, gt=0),
    min_speed: int | None = Query(default=None, gt=0),
    session: AsyncSession = Depends(get_session),
):
    await expire_promotions(session)
    query = select(Listing).where(Listing.listing_type == listing_type, Listing.status.in_(["active", "reserved"]))
    if brand:
        query = query.where(Listing.brand == brand)
    if model:
        query = query.where(Listing.model == model)
    if max_price:
        query = query.where(Listing.price_af_coins <= max_price)
    if min_power:
        query = query.where(Listing.power_hp >= min_power)
    if min_speed:
        query = query.where(Listing.max_speed_kph >= min_speed)
    listings = list((await session.scalars(query.order_by(Listing.pinned.desc(), Listing.created_at.desc()))).all())
    return [await listing_out(session, item) for item in listings]


@router.post("/listings", response_model=ListingOut, status_code=201)
async def add_regular_listing(
    payload: ListingCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    listing = await create_listing(session, user, payload, listing_type="regular")
    return await listing_out(session, listing)


@router.get("/listings/{listing_id}", response_model=ListingOut)
async def get_listing_details(
    listing_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    listing = await session.get(Listing, listing_id)
    if not listing or listing.status == "deleted":
        raise HTTPException(status_code=404, detail="Объявление не найдено")
    if listing.seller_id != user.id:
        listing.views_count += 1
        await session.commit()
        await session.refresh(listing)
    return await listing_out(session, listing, user.id)


@router.patch("/listings/{listing_id}", response_model=ListingOut)
async def edit_own_listing(listing_id: uuid.UUID, payload: ListingUpdate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    listing = await update_listing(session, user, listing_id, payload)
    return await listing_out(session, listing, user.id)


@router.delete("/listings/{listing_id}", status_code=204)
async def remove_own_listing(listing_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await delete_listing(session, user, listing_id)


@router.post("/listings/{listing_id}/promote", response_model=ListingOut)
async def promote_own_listing(listing_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    listing = await promote_listing(session, user, listing_id)
    return await listing_out(session, listing, user.id)


@router.post("/admin/listings/unique", response_model=ListingOut, status_code=201)
async def add_unique_listing(
    payload: UniqueListingCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    listing = await create_listing(session, admin, payload, listing_type="unique", pinned=payload.pinned)
    return await listing_out(session, listing)


@router.patch("/admin/listings/{listing_id}", response_model=ListingOut)
async def edit_unique_listing(
    listing_id: uuid.UUID,
    payload: ListingUpdate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    listing = await update_listing(session, admin, listing_id, payload)
    return await listing_out(session, listing)


@router.delete("/admin/listings/{listing_id}", status_code=204)
async def remove_unique_listing(
    listing_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await delete_listing(session, admin, listing_id)


@router.get("/accounts", response_model=list[AccountListingOut])
async def list_account_listings(session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(AccountListing).where(AccountListing.status == "active").order_by(AccountListing.created_at.desc()))).all())


@router.post("/admin/accounts", response_model=AccountListingOut, status_code=201)
async def add_account_listing(payload: AccountListingCreate, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return await create_account_listing(session, admin, payload)


@router.patch("/admin/accounts/{account_id}", response_model=AccountListingOut)
async def edit_account_listing(account_id: uuid.UUID, payload: AccountListingUpdate, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return await update_account_listing(session, admin, account_id, payload)


@router.delete("/admin/accounts/{account_id}", status_code=204)
async def remove_account_listing(account_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    await delete_account_listing(session, admin, account_id)


@router.get("/cart", response_model=list[ListingOut])
async def get_cart(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    listing_ids = list((await session.scalars(select(CartItem.listing_id).where(CartItem.user_id == user.id).order_by(CartItem.created_at))).all())
    if not listing_ids:
        return []
    listings = list((await session.scalars(select(Listing).where(Listing.id.in_(listing_ids)))).all())
    by_id = {item.id: item for item in listings}
    return [await listing_out(session, by_id[item_id], user.id) for item_id in listing_ids if item_id in by_id]


@router.post("/cart/items/{listing_id}", status_code=201)
async def add_to_cart(listing_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    listing = await session.get(Listing, listing_id)
    if not listing or listing.status != "active":
        raise HTTPException(status_code=409, detail="Listing is not available")
    if listing.seller_id == user.id:
        raise HTTPException(status_code=400, detail="You cannot add your own listing to cart")
    if not await session.scalar(select(CartItem.id).where(CartItem.user_id == user.id, CartItem.listing_id == listing_id)):
        session.add(CartItem(user_id=user.id, listing_id=listing_id))
        await session.commit()
    return {"ok": True}


@router.delete("/cart/items/{listing_id}", status_code=204)
async def delete_from_cart(listing_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await session.execute(delete(CartItem).where(CartItem.user_id == user.id, CartItem.listing_id == listing_id))
    await session.commit()


@router.post("/cart/checkout", response_model=list[DealOut])
async def checkout(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    deals, seller_ids = await checkout_cart(session, user)
    for telegram_id in seller_ids:
        background_tasks.add_task(send_bot_notification, telegram_id, "Ваш товар хотят купить. Откройте AUTOFLOW MARKET, чтобы ответить покупателю")
    return deals


@router.get("/favorites", response_model=list[ListingOut])
async def get_favorites(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    listing_ids = list((await session.scalars(select(Favorite.listing_id).where(Favorite.user_id == user.id).order_by(Favorite.created_at.desc()))).all())
    if not listing_ids:
        return []
    listings = list((await session.scalars(select(Listing).where(Listing.id.in_(listing_ids)))).all())
    by_id = {item.id: item for item in listings}
    return [await listing_out(session, by_id[item_id]) for item_id in listing_ids if item_id in by_id]


@router.post("/favorites/{listing_id}", status_code=201)
async def add_favorite(listing_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    if not await session.get(Listing, listing_id):
        raise HTTPException(status_code=404, detail="Listing not found")
    if not await session.scalar(select(Favorite.id).where(Favorite.user_id == user.id, Favorite.listing_id == listing_id)):
        session.add(Favorite(user_id=user.id, listing_id=listing_id))
        await session.commit()
    return {"ok": True}


@router.delete("/favorites/{listing_id}", status_code=204)
async def remove_favorite(listing_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await session.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.listing_id == listing_id))
    await session.commit()


@router.post("/conversations/listing/{listing_id}", status_code=201)
async def start_conversation(
    listing_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conversation, seller = await get_or_create_conversation(session, user, listing_id)
    if seller and seller.bot_started:
        background_tasks.add_task(send_bot_notification, seller.telegram_id, "Вам хотят написать по объявлению в AUTOFLOW MARKET")
    return await conversation_details(session, conversation, user)


@router.get("/conversations")
async def list_conversations(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    values = list(
        (
            await session.scalars(
                select(Conversation)
                .where(or_(Conversation.buyer_id == user.id, Conversation.seller_id == user.id))
                .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc())
            )
        ).all()
    )
    return [await conversation_details(session, item, user) for item in values]

@router.get("/conversations/unread-summary")
async def conversation_unread_summary(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conversations = list(
        (
            await session.scalars(
                select(Conversation).where(
                    or_(
                        Conversation.buyer_id == user.id,
                        Conversation.seller_id == user.id,
                    )
                )
            )
        ).all()
    )

    conversation_ids = [conversation.id for conversation in conversations]

    if not conversation_ids:
        return {
            "total_unread": 0,
            "conversations": [],
        }

    unread_rows = (
        await session.execute(
            select(
                ConversationMessage.conversation_id,
                func.count(ConversationMessage.id),
            )
            .where(
                ConversationMessage.conversation_id.in_(conversation_ids),
                ConversationMessage.sender_id != user.id,
                ConversationMessage.is_read.is_(False),
            )
            .group_by(ConversationMessage.conversation_id)
        )
    ).all()

    unread_by_conversation = {
        str(conversation_id): unread_count
        for conversation_id, unread_count in unread_rows
    }

    return {
        "total_unread": sum(unread_by_conversation.values()),
        "conversations": [
            {
                "conversation_id": conversation_id,
                "unread_count": unread_count,
            }
            for conversation_id, unread_count in unread_by_conversation.items()
        ],
    }
    
@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    conversation = await session.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await conversation_details(session, conversation, user)


@router.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessageOut])
async def get_conversation_messages(conversation_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    conversation = await session.get(Conversation, conversation_id)
    if not conversation or user.id not in {conversation.buyer_id, conversation.seller_id}:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return list((await session.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id).order_by(ConversationMessage.created_at))).all())
    
@router.post("/conversations/{conversation_id}/read", status_code=204)
async def mark_conversation_as_read(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conversation = await session.get(Conversation, conversation_id)

    if not conversation or user.id not in {
        conversation.buyer_id,
        conversation.seller_id,
    }:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    await session.execute(
        update(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.sender_id != user.id,
            ConversationMessage.is_read.is_(False),
        )
        .values(
            is_read=True,
            read_at=datetime.now(UTC),
        )
    )

    await session.commit()


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationMessageOut, status_code=201)
async def add_conversation_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    message, recipient = await send_conversation_message(session, user, conversation_id, payload.body)
    if recipient and recipient.bot_started:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, "Новое сообщение в AUTOFLOW MARKET. Откройте приложение, чтобы ответить")
    return message


@router.post("/conversations/{conversation_id}/offers", response_model=PriceOfferOut, status_code=201)
async def add_price_offer(
    conversation_id: uuid.UUID,
    payload: PriceOfferCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    offer, recipient = await create_price_offer(session, user, conversation_id, payload.amount_af_coins)
    if recipient and recipient.bot_started:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, f"Новое предложение цены: {offer.amount_af_coins} AF Coins")
    return offer


@router.post("/conversations/{conversation_id}/offers/counter", response_model=PriceOfferOut, status_code=201)
async def counter_price_offer(
    conversation_id: uuid.UUID,
    payload: CounterOfferCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    offer, recipient = await create_price_offer(session, user, conversation_id, payload.amount_af_coins, payload.parent_offer_id)
    if recipient and recipient.bot_started:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, f"Встречное предложение: {offer.amount_af_coins} AF Coins")
    return offer


@router.post("/offers/{offer_id}/{action}", response_model=PriceOfferOut)
async def answer_price_offer(
    offer_id: uuid.UUID,
    action: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if action not in {"accept", "reject"}:
        raise HTTPException(status_code=404, detail="Unknown offer action")
    offer, recipient = await respond_price_offer(session, user, offer_id, action == "accept")
    if recipient and recipient.bot_started:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, "Ваше предложение цены принято" if action == "accept" else "Ваше предложение цены отклонено")
    return offer


@router.get("/deals", response_model=list[DealOut])
async def list_deals(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(Deal).where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id)).order_by(Deal.updated_at.desc()))).all())


@router.get("/deals/{deal_id}")
async def get_deal(deal_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    deal = await ensure_deal_participant(session, deal_id, user)
    listing = await session.get(Listing, deal.listing_id)
    other_id = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    other = await session.get(User, other_id)
    conversation_id = await session.scalar(select(Conversation.id).where(Conversation.deal_id == deal.id))
    return {
        "deal": DealOut.model_validate(deal),
        "listing": await listing_out(session, listing),
        "counterparty": {
            "id": str(other.id),
            "name": " ".join(filter(None, [other.first_name, other.last_name])),
            "username": other.username,
            "photo_url": other.photo_url,
            "mini_app_last_active_at": other.mini_app_last_active_at,
        },
        "buyer_confirmation_available_at": deal.transfer_started_at,
        "conversation_id": str(conversation_id) if conversation_id else None,
    }


@router.get("/deals/{deal_id}/messages", response_model=list[MessageOut])
async def get_messages(deal_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await ensure_deal_participant(session, deal_id, user)
    return list((await session.scalars(select(DealMessage).where(DealMessage.deal_id == deal_id).order_by(DealMessage.created_at))).all())


@router.post("/deals/{deal_id}/messages", response_model=MessageOut, status_code=201)
async def send_message(
    deal_id: uuid.UUID,
    payload: MessageCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    deal = await ensure_deal_participant(session, deal_id, user)
    message = DealMessage(deal_id=deal.id, sender_id=user.id, body=payload.body.strip())
    session.add(message)
    recipient_id = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    await create_notification(session, recipient_id, "deal_message", "Новое сообщение по сделке", payload.body[:240], {"deal_id": str(deal.id)})
    recipient = await session.get(User, recipient_id)
    await session.commit()
    await session.refresh(message)
    if recipient:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, "Новое сообщение в AUTOFLOW MARKET. Откройте приложение, чтобы ответить")
    return message


@router.post("/deals/{deal_id}/seller-contacted", response_model=DealOut)
async def seller_contacted(deal_id: uuid.UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    deal = await set_deal_status(session, user, deal_id, "seller_contacted")
    await queue_counterparty_notification(session, background_tasks, deal, user, "Продавец ответил по сделке в AUTOFLOW MARKET")
    return deal


@router.post("/deals/{deal_id}/transfer", response_model=DealOut)
async def transfer_started(deal_id: uuid.UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    deal = await set_deal_status(session, user, deal_id, "transfer_in_progress")
    await queue_counterparty_notification(session, background_tasks, deal, user, "Продавец начал передачу товара. Откройте сделку в AUTOFLOW MARKET")
    return deal


@router.post("/deals/{deal_id}/confirm", response_model=DealOut)
async def confirm_received(deal_id: uuid.UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    deal = await complete_deal(session, user, deal_id)
    await queue_counterparty_notification(session, background_tasks, deal, user, "Покупатель подтвердил получение. Сделка завершена, 70% начислено в AF Coins")
    return deal


@router.post("/deals/{deal_id}/dispute", response_model=DealOut)
async def dispute(deal_id: uuid.UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    deal = await set_deal_status(session, user, deal_id, "disputed")
    await queue_counterparty_notification(session, background_tasks, deal, user, "По сделке открыта проблема. Откройте AUTOFLOW MARKET")
    return deal


@router.post("/deals/{deal_id}/cancel", response_model=DealOut)
async def cancel(deal_id: uuid.UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    deal = await cancel_deal(session, user, deal_id)
    await queue_counterparty_notification(session, background_tasks, deal, user, "Сделка отменена. Резерв покупателя возвращён")
    return deal


@router.get("/wallet", response_model=WalletOut)
async def wallet(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return await session.scalar(select(Wallet).where(Wallet.user_id == user.id))


@router.post("/wallet/star-payments/intent", response_model=StarPaymentIntentOut, status_code=201)
async def add_star_payment_intent(
    payload: StarPaymentIntentCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    intent = await create_star_payment_intent(session, user, payload.amount, create_star_invoice_link)
    return StarPaymentIntentOut(id=intent.id, invoice_url=intent.invoice_link, amount=intent.xtr_amount, status=intent.status)


@router.get("/wallet/star-payments/intents/{intent_id}", response_model=StarPaymentStatusOut)
async def star_payment_status(
    intent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    intent = await session.get(StarPaymentIntent, intent_id)
    if not intent or intent.user_id != user.id:
        raise HTTPException(status_code=404, detail="Счёт не найден")
    wallet_value = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
    return StarPaymentStatusOut(id=intent.id, status=intent.status, amount=intent.xtr_amount, wallet=wallet_value)


@router.get("/withdrawals", response_model=list[WithdrawalOut])
async def withdrawals(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(WithdrawalRequest).where(WithdrawalRequest.user_id == user.id).order_by(WithdrawalRequest.created_at.desc()))).all())


@router.post("/withdrawals", response_model=WithdrawalOut, status_code=201)
async def add_withdrawal(payload: WithdrawalCreate, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    withdrawal = await create_withdrawal(session, user, payload)
    admin_telegram_ids = list((await session.scalars(select(User.telegram_id).where(User.role == "admin", User.bot_started.is_(True)))).all())
    for telegram_id in admin_telegram_ids:
        background_tasks.add_task(send_bot_notification, telegram_id, f"Новая заявка на вывод: {withdrawal.amount} AF Coins от Telegram ID {user.telegram_id}")
    return withdrawal


@router.post("/withdrawals/{withdrawal_id}/cancel", response_model=WithdrawalOut)
async def cancel_own_withdrawal(withdrawal_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return await cancel_withdrawal(session, user, withdrawal_id)


@router.get("/admin/users")
async def admin_users(
    q: str | None = None,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    query = select(User).order_by(User.created_at.desc()).limit(100)
    if q:
        pattern = f"%{q.strip()}%"
        conditions = [User.first_name.ilike(pattern), User.username.ilike(pattern)]
        if q.strip().isdigit():
            conditions.append(User.telegram_id == int(q.strip()))
        query = query.where(or_(*conditions))
    users = list((await session.scalars(query)).all())
    result = []
    for item in users:
        wallet_value = await session.scalar(select(Wallet).where(Wallet.user_id == item.id))
        result.append({
            "user": UserOut.model_validate(item),
            "wallet": WalletOut.model_validate(wallet_value),
            "listings_count": await session.scalar(select(func.count(Listing.id)).where(Listing.seller_id == item.id)),
            "deals_count": await session.scalar(select(func.count(Deal.id)).where(or_(Deal.buyer_id == item.id, Deal.seller_id == item.id))),
        })
    return result


@router.get("/admin/users/{user_id}")
async def admin_user_details(user_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    wallet_value = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
    listings = list((await session.scalars(select(Listing).where(Listing.seller_id == user.id).order_by(Listing.created_at.desc()))).all())
    deals = list((await session.scalars(select(Deal).where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id)).order_by(Deal.created_at.desc()))).all())
    return {"user": UserOut.model_validate(user), "wallet": WalletOut.model_validate(wallet_value), "listings": [await listing_out(session, item) for item in listings], "deals": [DealOut.model_validate(item) for item in deals]}


@router.post("/admin/users/{user_id}/{action}")
async def admin_user_block_action(user_id: uuid.UUID, action: str, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    if action not in {"block", "unblock"}:
        raise HTTPException(status_code=404, detail="Unknown user action")
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Administrator cannot block themselves")
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_blocked = action == "block"
    session.add(AdminAction(admin_id=admin.id, action=f"user_{action}", target_type="user", target_id=user.id))
    await session.commit()
    return {"ok": True, "is_blocked": user.is_blocked}


@router.get("/admin/listings", response_model=list[ListingOut])
async def admin_listings(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    await expire_promotions(session)
    values = list((await session.scalars(select(Listing).where(Listing.status != "deleted").order_by(Listing.created_at.desc()))).all())
    return [await listing_out(session, item) for item in values]


@router.post("/admin/listings/{listing_id}/promote", response_model=ListingOut)
async def admin_promote_listing(listing_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    listing = await promote_listing(session, admin, listing_id)
    return await listing_out(session, listing)


@router.post("/admin/listings/{listing_id}/{action}", response_model=ListingOut)
async def admin_listing_publication(listing_id: uuid.UUID, action: str, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    if action not in {"publish", "unpublish"}:
        raise HTTPException(status_code=404, detail="Unknown listing action")
    listing = await set_listing_publication(session, admin, listing_id, action == "publish")
    return await listing_out(session, listing)


@router.get("/admin/deals", response_model=list[DealOut])
async def admin_deals(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(Deal).order_by(Deal.updated_at.desc()).limit(200))).all())


@router.post("/admin/deals/{deal_id}/resolve", response_model=DealOut)
async def admin_resolve_deal(
    deal_id: uuid.UUID,
    payload: DealResolution,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    deal = await resolve_dispute(session, admin, deal_id, payload.outcome, payload.reason)
    participants = list((await session.scalars(select(User).where(User.id.in_([deal.buyer_id, deal.seller_id]), User.bot_started.is_(True)))).all())
    for participant in participants:
        background_tasks.add_task(send_bot_notification, participant.telegram_id, "Администратор рассмотрел спор по сделке в AUTOFLOW MARKET")
    return deal


@router.get("/admin/conversations/{conversation_id}")
async def admin_conversation(conversation_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    conversation = await session.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    details = await conversation_details(session, conversation, admin, allow_admin=True)
    details["messages"] = [ConversationMessageOut.model_validate(item) for item in (await session.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id).order_by(ConversationMessage.created_at))).all()]
    return details


@router.get("/admin/withdrawals", response_model=list[AdminWithdrawalOut])
async def admin_withdrawals(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(WithdrawalRequest, User)
            .join(User, User.id == WithdrawalRequest.user_id)
            .order_by(WithdrawalRequest.created_at.desc())
        )
    ).all()

    return [
        AdminWithdrawalOut(
            **WithdrawalOut.model_validate(withdrawal).model_dump(),
            user_telegram_id=user.telegram_id,
            user_name=" ".join(
                filter(None, [user.first_name, user.last_name])
            ),
            user_username=user.username,
        )
        for withdrawal, user in rows
    ]

@router.post("/admin/withdrawals/{withdrawal_id}/{action}", response_model=WithdrawalOut)
async def admin_withdrawal_action(
    withdrawal_id: uuid.UUID,
    action: str,
    payload: WithdrawalDecision,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if action not in {"approve", "paid", "reject"}:
        raise HTTPException(status_code=404, detail="Unknown withdrawal action")
    withdrawal = await decide_withdrawal(session, admin, withdrawal_id, action, payload.reason)
    owner = await session.get(User, withdrawal.user_id)
    if owner and owner.bot_started:
        background_tasks.add_task(send_bot_notification, owner.telegram_id, f"Статус заявки на вывод изменён: {withdrawal.status}")
    return withdrawal


@router.get("/admin/users/{user_id}/financial-history")
async def admin_user_financial_history(user_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
    transactions = list((await session.scalars(select(WalletTransaction).where(WalletTransaction.user_id == user_id).order_by(WalletTransaction.created_at.desc()).limit(200))).all())
    payments = list((await session.scalars(select(StarPayment).where(StarPayment.user_id == user_id).order_by(StarPayment.created_at.desc()).limit(100))).all())
    withdrawals = list((await session.scalars(select(WithdrawalRequest).where(WithdrawalRequest.user_id == user_id).order_by(WithdrawalRequest.created_at.desc()).limit(100))).all())
    return {
        "user": {"id": str(user.id), "telegram_id": user.telegram_id, "name": " ".join(filter(None, [user.first_name, user.last_name]))},
        "wallet": WalletOut.model_validate(wallet),
        "wallet_transactions": [
            {"id": str(item.id), "type": item.transaction_type, "amount": item.amount, "description": item.description, "created_at": item.created_at}
            for item in transactions
        ],
        "star_payments": [
            {"id": str(item.id), "telegram_payment_charge_id": item.telegram_payment_charge_id, "xtr_amount": item.xtr_amount, "af_coin_amount": item.af_coin_amount, "status": item.status, "created_at": item.created_at}
            for item in payments
        ],
        "withdrawals": [WithdrawalOut.model_validate(item) for item in withdrawals],
    }


@router.post("/admin/balance-adjustments", response_model=WalletOut)
async def admin_balance_adjustment(
    payload: BalanceAdjustmentCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return await adjust_balance(session, admin, payload)


@router.get("/notifications", response_model=list[NotificationOut])
async def notifications(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100))).all())


@router.post("/notifications/{notification_id}/read", status_code=204)
async def read_notification(notification_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    notification = await session.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read_at = datetime.now(UTC)
    await session.commit()


@router.get("/support/tickets", response_model=list[SupportTicketOut])
async def support_tickets(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tickets = list(
        (
            await session.scalars(
                select(SupportTicket)
                .where(SupportTicket.user_id == user.id)
                .order_by(SupportTicket.updated_at.desc())
            )
        ).all()
    )
    return [await support_ticket_out(session, ticket) for ticket in tickets]


@router.post("/support/tickets", response_model=SupportTicketOut, status_code=201)
async def create_support_ticket(
    payload: SupportTicketCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        ticket = SupportTicket(
            user_id=user.id,
            topic=payload.topic.strip(),
            status="open",
            screenshot_url=payload.screenshot_url,
        )
        session.add(ticket)
        await session.flush()
        session.add(SupportMessage(ticket_id=ticket.id, sender_id=user.id, body=payload.message.strip()))
        administrators = list(
            (
                await session.scalars(
                    select(User).where(User.role == "admin", User.bot_started.is_(True))
                )
            ).all()
        )
        for administrator in administrators:
            await create_notification(
                session,
                administrator.id,
                "support_ticket",
                "Новое обращение в поддержку",
                payload.topic.strip(),
                {"ticket_id": str(ticket.id)},
            )
    for administrator in administrators:
        background_tasks.add_task(
            send_bot_notification,
            administrator.telegram_id,
            "Новое обращение в поддержку AUTOFLOW MARKET",
        )
    return await support_ticket_out(session, ticket)


@router.post("/support/tickets/{ticket_id}/messages", response_model=SupportMessageOut, status_code=201)
async def reply_to_support_ticket(
    ticket_id: uuid.UUID,
    payload: SupportReplyCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ticket = await session.get(SupportTicket, ticket_id)
    if not ticket or ticket.user_id != user.id:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    if ticket.status == "closed":
        raise HTTPException(status_code=409, detail="Закрытое обращение нельзя дополнить")
    message = SupportMessage(ticket_id=ticket.id, sender_id=user.id, body=payload.message.strip())
    ticket.status = "open"
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message


@router.get("/admin/support/tickets", response_model=list[SupportTicketOut])
async def admin_support_tickets(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    tickets = list(
        (
            await session.scalars(
                select(SupportTicket).order_by(SupportTicket.updated_at.desc())
            )
        ).all()
    )
    return [await support_ticket_out(session, ticket) for ticket in tickets]


@router.post("/admin/support/tickets/{ticket_id}/messages", response_model=SupportMessageOut, status_code=201)
async def admin_reply_to_support_ticket(
    ticket_id: uuid.UUID,
    payload: SupportReplyCreate,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    ticket = await session.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    owner = await session.get(User, ticket.user_id)
    message = SupportMessage(ticket_id=ticket.id, sender_id=admin.id, body=payload.message.strip())
    ticket.status = "in_progress"
    session.add(message)
    await create_notification(
        session,
        ticket.user_id,
        "support_reply",
        "Ответ поддержки",
        payload.message.strip()[:240],
        {"ticket_id": str(ticket.id)},
    )
    await session.commit()
    await session.refresh(message)
    if owner and owner.bot_started:
        background_tasks.add_task(
            send_bot_notification,
            owner.telegram_id,
            "Поддержка AUTOFLOW MARKET ответила на ваше обращение",
        )
    return message


@router.patch("/admin/support/tickets/{ticket_id}", response_model=SupportTicketOut)
async def update_support_ticket_status(
    ticket_id: uuid.UUID,
    payload: SupportStatusUpdate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    ticket = await session.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    ticket.status = payload.status
    session.add(
        AdminAction(
            admin_id=admin.id,
            action=f"support_{payload.status}",
            target_type="support_ticket",
            target_id=ticket.id,
        )
    )
    await session.commit()
    await session.refresh(ticket)
    return await support_ticket_out(session, ticket)


@router.get("/profile", response_model=ProfileOut)
async def profile(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    wallet_value = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
    active = list((await session.scalars(select(Listing).where(Listing.seller_id == user.id, Listing.status.in_(["active", "reserved"])).order_by(Listing.created_at.desc()))).all())
    sold = list((await session.scalars(select(Listing).where(Listing.seller_id == user.id, Listing.status == "sold").order_by(Listing.sold_at.desc()))).all())
    purchase_deals = list((await session.scalars(select(Deal).where(Deal.buyer_id == user.id, Deal.status == "completed"))).all())
    purchases = [await session.get(Listing, item.listing_id) for item in purchase_deals]
    active_deals = list((await session.scalars(select(Deal).where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id), Deal.status.not_in(["completed", "cancelled"])))).all())
    conversation_values = list((await session.scalars(select(Conversation).where(or_(Conversation.buyer_id == user.id, Conversation.seller_id == user.id)).order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc()))).all())
    transactions = list((await session.scalars(select(WalletTransaction).where(WalletTransaction.user_id == user.id).order_by(WalletTransaction.created_at.desc()).limit(100))).all())
    withdrawal_values = list((await session.scalars(select(WithdrawalRequest).where(WithdrawalRequest.user_id == user.id).order_by(WithdrawalRequest.created_at.desc()))).all())
    return ProfileOut(
        user=user,
        wallet=wallet_value,
        active_listings=[await listing_out(session, item, user.id) for item in active],
        sold_listings=[await listing_out(session, item, user.id) for item in sold],
        purchases=[await listing_out(session, item, user.id) for item in purchases if item],
        active_deals=active_deals,
        conversations=[await conversation_details(session, item, user) for item in conversation_values],
        wallet_transactions=[
            {
                "id": str(item.id),
                "type": item.transaction_type,
                "amount": item.amount,
                "available_before": item.available_before,
                "available_after": item.available_after,
                "frozen_before": item.frozen_before,
                "frozen_after": item.frozen_after,
                "description": item.description,
                "created_at": item.created_at,
            }
            for item in transactions
        ],
        withdrawals=withdrawal_values,
    )


@router.post("/telegram/webhook")
async def telegram_webhook(
    update: dict,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    pre_checkout = update.get("pre_checkout_query") or {}
    if pre_checkout.get("id"):
        sender = pre_checkout.get("from") or {}
        accepted, error_message = await validate_star_pre_checkout(
            session,
            int(sender.get("id") or 0),
            str(pre_checkout.get("invoice_payload") or ""),
            str(pre_checkout.get("currency") or ""),
            int(pre_checkout.get("total_amount") or 0),
        )
        await answer_pre_checkout_query(pre_checkout["id"], accepted, error_message)
        return {"ok": True}
    message = update.get("message") or {}
    sender = message.get("from") or {}
        # Админская рассылка
    if sender.get("id") in settings.admin_telegram_ids:

        if (message.get("text") or "").startswith("#рассылка"):

            text = (message.get("text") or "").replace("#рассылка", "", 1).strip()

            users = list(
                (
                    await session.scalars(
                        select(User).where(User.bot_started.is_(True))
                    )
                ).all()
            )

           sent_count = 0
failed_count = 0

for item in users:
    sent = await send_bot_notification(item.telegram_id, text)

    if sent:
        sent_count += 1
    else:
        failed_count += 1

await send_bot_notification(
    int(sender["id"]),
    (
        "✅ Рассылка завершена.\n\n"
        f"Получили: {sent_count}\n"
        f"Не удалось отправить: {failed_count}"
    ),
)

return {
    "ok": True,
    "sent": sent_count,
    "failed": failed_count,
}

        if message.get("photo"):

            caption = message.get("caption") or ""

            if caption.startswith("#рассылка"):

                caption = caption.replace("#рассылка", "", 1).strip()

                photo = message["photo"][-1]["file_id"]

                users = list(
                    (
                        await session.scalars(
                            select(User).where(User.bot_started.is_(True))
                        )
                    ).all()
                )

sent_count = 0
failed_count = 0

for item in users:
    sent = await send_bot_photo(
        item.telegram_id,
        photo,
        caption,
    )

    if sent:
        sent_count += 1
    else:
        failed_count += 1

await send_bot_notification(
    int(sender["id"]),
    (
        "✅ Рассылка завершена.\n\n"
        f"Получили: {sent_count}\n"
        f"Не удалось отправить: {failed_count}"
    ),
)

return {
    "ok": True,
    "sent": sent_count,
    "failed": failed_count,
}
    if message.get("text") == "/start" and sender.get("id"):
        user = await session.scalar(select(User).where(User.telegram_id == int(sender["id"])))
        if not user:
            telegram_id = int(sender["id"])
            user = User(
                telegram_id=telegram_id,
                role="admin" if telegram_id in settings.admin_telegram_ids else "user",
                first_name=sender.get("first_name") or "Telegram User",
                last_name=sender.get("last_name"),
                username=sender.get("username"),
                bot_started=True,
            )
            session.add(user)
            await session.flush()
            session.add(Wallet(user_id=user.id))
        else:
            user.bot_started = True
        await session.commit()
    payment = message.get("successful_payment")
    if payment and sender.get("id"):
        credited = await process_successful_payment(session, int(sender["id"]), payment)
        if credited:
            background_tasks.add_task(send_bot_notification, int(sender["id"]), f"Баланс AUTOFLOW MARKET пополнен на {payment['total_amount']} AF Coins")
    return {"ok": True}
